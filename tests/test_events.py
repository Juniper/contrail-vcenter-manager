import pytest
from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.vnc_api import InstanceIp, Project, VirtualNetwork

from cvm.controllers import VmRenamedHandler, VmReconfiguredHandler, VmwareController
from cvm.database import Database
from cvm.models import VirtualNetworkModel, VlanIdPool
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService)


@pytest.fixture()
def ipam():
    return vnc_api.NetworkIpam(
        name='IPAM',
        parent_obj=vnc_api.Project()
    )


@pytest.fixture()
def vnc_vn_1(ipam):
    vnc_vn = VirtualNetwork(name='DPG1', parent=Project())
    vnc_vn.set_uuid('vnc_vn_uuid_1')
    vnc_vn.set_network_ipam(ipam, None)
    return vnc_vn


@pytest.fixture()
def vnc_vn_2(ipam):
    vnc_vn = VirtualNetwork(name='DPG2', parent=Project())
    vnc_vn.set_uuid('vnc_vn_uuid_2')
    vnc_vn.set_network_ipam(ipam, None)
    return vnc_vn


@pytest.fixture()
def vn_model_1(vnc_vn_1):
    dpg = Mock()
    dpg.key = 'dvportgroup-1'
    dpg.name = 'DPG1'
    dvs = Mock()
    dpg.config.distributedVirtualSwitch = dvs
    dvs.FetchDVPorts.return_value = []
    return VirtualNetworkModel(dpg, vnc_vn_1, VlanIdPool(0, 100))


@pytest.fixture()
def vn_model_2(vnc_vn_2):
    dpg = Mock()
    dpg.key = 'dvportgroup-2'
    dpg.name = 'DPG2'
    dvs = Mock()
    dpg.config.distributedVirtualSwitch = dvs
    dvs.FetchDVPorts.return_value = []
    return VirtualNetworkModel(dpg, vnc_vn_2, VlanIdPool(0, 100))


@pytest.fixture()
def vmware_vm_1():
    vmware_vm = Mock()
    vmware_vm.summary.runtime.host.vm = []
    vmware_vm.config.instanceUuid = '12345678-1234-1234-1234-123456789012'
    backing = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
    backing.port = Mock(portgroupKey='dvportgroup-1', portKey='10')
    vmware_vm.config.hardware.device = [Mock(backing=backing, macAddress='11:11:11:11:11:11')]
    return vmware_vm


@pytest.fixture()
def vm_properties_1():
    return {
        'config.instanceUuid': '12345678-1234-1234-1234-123456789012',
        'name': 'VM1'
    }


@pytest.fixture()
def vm_properties_renamed():
    return {
        'config.instanceUuid': '12345678-1234-1234-1234-123456789012',
        'name': 'VM1-renamed'
    }


def assign_ip_to_instance_ip(instance_ip):
    instance_ip.set_instance_ip_address('192.168.100.5')
    return instance_ip


def wrap_into_update_set(event):
    change = vmodl.query.PropertyCollector.Change()
    change.name = 'latestPage'
    change.val = event
    update_set = vmodl.query.PropertyCollector.UpdateSet()
    filter_update = vmodl.query.PropertyCollector.FilterUpdate()
    object_update = vmodl.query.PropertyCollector.ObjectUpdate()
    object_update.changeSet = [change]
    object_set = [object_update]
    filter_update.objectSet = object_set
    update_set.filterSet = [filter_update]
    return update_set


@pytest.fixture()
def vm_created_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmCreatedEvent())
    event.vm.vm = vmware_vm_1
    return wrap_into_update_set(event)


@pytest.fixture()
def vm_renamed_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmRenamedEvent())
    vmware_vm_1.name = 'VM1-renamed'
    event.vm.vm = vmware_vm_1
    return wrap_into_update_set(event)


@pytest.fixture()
def vm_reconfigure_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmReconfiguredEvent())
    event.vm.vm = vmware_vm_1
    port = Mock(spec=vim.dvs.PortConnection())
    port.portgroupKey = 'dvportgroup-2'
    device = Mock(spec=vim.vm.device.VirtualVmxnet3())
    device.backing.port = port
    device.macAddress = '11:11:11:11:11:11'
    event.configSpec.deviceChange = [device]
    return wrap_into_update_set(event)


@pytest.fixture()
def vnc_api_client():
    vnc_client = Mock()
    vnc_client.read_or_create_project.return_value = Project()
    vnc_client.create_and_read_instance_ip.side_effect = assign_ip_to_instance_ip
    return vnc_client


@pytest.fixture()
def vcenter_api_client():
    vcenter_client = Mock()
    vcenter_client.__enter__ = Mock()
    vcenter_client.__exit__ = Mock()
    vcenter_client.get_ip_pool_for_dpg.return_value = None
    return vcenter_client


@pytest.fixture()
def esxi_api_client(vm_properties_1):
    esxi_api_client = Mock()
    esxi_api_client.read_vm_properties.return_value = vm_properties_1
    return esxi_api_client


def test_vm_created(vcenter_api_client, vn_model_1, vm_created_update,
                    esxi_api_client, vnc_api_client, vnc_vn_1):
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(vcenter_api_client, vnc_api_client, vrouter_api_client, database)
    controller = VmwareController(vm_service, None, vmi_service, [])

    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    vn_model_1.vlan_id_pool.reserve(0)
    vn_model_1.vlan_id_pool.reserve(1)

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # Check if VM Model has been saved properly:
    # - in VNC:
    vnc_api_client.update_or_create_vm.assert_called_once()
    vnc_vm = vnc_api_client.update_or_create_vm.call_args[0][0]
    assert vnc_vm.uuid == '12345678-1234-1234-1234-123456789012'
    assert vnc_vm.name == '12345678-1234-1234-1234-123456789012'

    # - in Database:
    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')
    assert vm_model.uuid == '12345678-1234-1234-1234-123456789012'
    assert vm_model.name == 'VM1'

    # Check if VMI Model has been saved properly:
    # - in VNC
    vnc_api_client.update_or_create_vmi.assert_called_once()
    vnc_vmi = vnc_api_client.update_or_create_vmi.call_args[0][0]
    assert vnc_vmi.get_virtual_machine_interface_mac_addresses().mac_address == ['11:11:11:11:11:11']
    assert vnc_vm.uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_machine_refs()]
    assert vnc_vn_1.uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()]


    # - in Database
    vmi_model = database.get_all_vmi_models()[0]
    assert vmi_model.display_name == 'vmi-DPG1-VM1'

    # Check if VMI Model's Instance IP has been created in VNC:
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    # Check if VMI's vRouter Port has been added:
    vmi_model = vrouter_api_client.add_port.call_args[0][0]
    assert vmi_model.vm_model == vm_model
    assert vmi_model.vn_model == vn_model_1
    assert vmi_model.mac_address == '11:11:11:11:11:11'
    assert vmi_model.vnc_instance_ip.instance_ip_address == '192.168.100.5'
    assert vmi_model.vlan_id == 2

    # Check if VLAN ID has been set using VLAN Override
    vcenter_api_client.set_vlan_id.assert_called_once_with(vmi_model.vn_model.dvs_name, '10', 2)


def test_vm_renamed(vcenter_api_client, vn_model_1, vm_created_update,
                    esxi_api_client, vm_renamed_update,
                    vm_properties_renamed, vnc_api_client):
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(
        vcenter_api_client,
        vnc_api_client,
        vrouter_api_client,
        database
    )
    vm_renamed_handler = VmRenamedHandler(vm_service, vmi_service)
    controller = VmwareController(vm_service, None, vmi_service, [vm_renamed_handler])

    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    vn_model_1.vlan_id_pool.reserve(0)
    vn_model_1.vlan_id_pool.reserve(1)

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # A user renames the VM in vSphere and VmRenamedEvent arrives
    esxi_api_client.read_vm_properties.return_value = vm_properties_renamed
    controller.handle_update(vm_renamed_update)

    # Check if VM Model has been saved properly:
    # - in VNC:
    assert vnc_api_client.update_or_create_vmi.call_count == 2
    vnc_vm = vnc_api_client.update_or_create_vm.call_args[0][0]
    assert vnc_vm.uuid == '12345678-1234-1234-1234-123456789012'
    assert vnc_vm.name == '12345678-1234-1234-1234-123456789012'

    # - in Database:
    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')
    assert vm_model.uuid == '12345678-1234-1234-1234-123456789012'
    assert vm_model.name == 'VM1-renamed'

    # Check if VMI Model has been saved properly:
    # - in VNC
    assert vnc_api_client.update_or_create_vmi.call_count == 2
    vnc_vmi = vnc_api_client.update_or_create_vmi.call_args[0][0]
    assert vnc_vmi.get_virtual_machine_interface_mac_addresses().mac_address == ['11:11:11:11:11:11']
    assert vnc_vm.uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_machine_refs()]

    # - in Database
    vmi_model = database.get_all_vmi_models()[0]
    assert vmi_model.display_name == 'vmi-DPG1-VM1-renamed'

    # Check if VMI Model's Instance IP has been created in VNC:
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    # Check if VMI's vRouter Port has been added:
    vmi_model = vrouter_api_client.add_port.call_args[0][0]
    assert vmi_model.vm_model == vm_model
    assert vmi_model.vn_model == vn_model_1
    assert vmi_model.mac_address == '11:11:11:11:11:11'
    assert vmi_model.vnc_instance_ip.instance_ip_address == '192.168.100.5'
    assert vmi_model.vlan_id == 2

    # Check if VLAN ID has been set using VLAN Override
    vcenter_api_client.set_vlan_id.assert_called_once_with(vmi_model.vn_model.dvs_name, '10', 2)


def test_vm_reconfigured(vcenter_api_client, vn_model_1, vn_model_2, vm_created_update,
                         esxi_api_client, vm_reconfigure_update, vnc_api_client, vnc_vn_2,
                         vmware_vm_1):
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vn_service = VirtualNetworkService(vcenter_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(
        vcenter_api_client,
        vnc_api_client,
        vrouter_api_client,
        database
    )
    vm_reconfigure_handler = VmReconfiguredHandler(vm_service, vn_service, vmi_service)
    controller = VmwareController(vm_service, vn_service, vmi_service, [vm_reconfigure_handler])

    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)
    database.save(vn_model_2)

    # Some vlan ids should be already reserved
    vn_model_1.vlan_id_pool.reserve(0)
    vn_model_1.vlan_id_pool.reserve(1)
    vn_model_2.vlan_id_pool.reserve(0)
    vn_model_2.vlan_id_pool.reserve(1)
    vn_model_2.vlan_id_pool.reserve(2)
    vn_model_2.vlan_id_pool.reserve(3)

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)
    old_vmi_model = database.get_vmi_models_by_vm_uuid('12345678-1234-1234-1234-123456789012')[0]
    old_instance_ip = old_vmi_model.vnc_instance_ip

    # After a portgroup is changed, the port key is also changed
    vmware_vm_1.config.hardware.device[0].backing.port.portKey = '11'

    # Then VmReconfiguredEvent is being handled
    controller.handle_update(vm_reconfigure_update)

    # Check if VM Model has been saved properly in Database:
    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')
    assert vm_model.interfaces.get('11:11:11:11:11:11') == 'dvportgroup-2'

    # Check that VM was not updated in VNC except VM create event
    vnc_api_client.update_or_create_vm.assert_called_once()

    # Check if VMI Model has been saved properly:
    # - in VNC
    vnc_api_client.update_or_create_vmi.call_count == 2
    # print(vnc_api_client.update_or_create_vmi.call_args[0])
    vnc_vmi = vnc_api_client.update_or_create_vmi.call_args[0][0]
    assert vnc_vmi.get_virtual_machine_interface_mac_addresses().mac_address == ['11:11:11:11:11:11']
    assert vnc_vn_2.uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()]

    # - in Database
    vmi_models = database.get_vmi_models_by_vm_uuid('12345678-1234-1234-1234-123456789012')
    assert len(vmi_models) == 1
    vmi_model = vmi_models[0]
    assert vmi_model.display_name == 'vmi-DPG2-VM1'
    assert vmi_model.vn_model == vn_model_2

    # Check if VMI Model's Instance IP has been updated in VNC:
    vnc_api_client.delete_instance_ip.assert_called_once_with(old_instance_ip)
    assert vnc_api_client.create_and_read_instance_ip.call_count == 2
    new_instance_ip = vmi_model.vnc_instance_ip
    assert vnc_api_client.create_and_read_instance_ip.call_args[0][0] == new_instance_ip
    assert vnc_vn_2.uuid in [ref['uuid'] for ref in new_instance_ip.get_virtual_network_refs()]

    # Check if VMI's vRouter Port has been updated:
    vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)
    assert vrouter_api_client.add_port.call_count == 2
    assert vrouter_api_client.add_port.call_args[0][0] == vmi_model
    assert vmi_model.mac_address == '11:11:11:11:11:11'
    assert vmi_model.vnc_instance_ip.instance_ip_address == '192.168.100.5'
    assert vmi_model.vlan_id == 4

    # Check if VLAN ID has been set using VLAN Override
    assert vcenter_api_client.set_vlan_id.call_count == 2
    assert vcenter_api_client.set_vlan_id.call_args[0] == (vmi_model.vn_model.dvs_name, '11', 4)
