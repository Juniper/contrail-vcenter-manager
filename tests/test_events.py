# pylint: disable=redefined-outer-name

import pytest
from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.vnc_api import Project, VirtualNetwork

from cvm.controllers import (VmReconfiguredHandler, VmRenamedHandler,
                             VmwareController)
from cvm.database import Database
from cvm.models import VirtualNetworkModel, VlanIdPool
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService,
                          VRouterPortService)
from tests.utils import reserve_vlan_ids


def create_ipam():
    return vnc_api.NetworkIpam(
        name='IPAM',
        parent_obj=vnc_api.Project()
    )


def create_vnc_vn(name, uuid):
    vnc_vn = VirtualNetwork(name=name, parent=Project())
    vnc_vn.set_uuid(uuid)
    vnc_vn.set_network_ipam(create_ipam(), None)
    return vnc_vn


def create_vn_model(vnc_vn, portgroup_key, portgroup_name):
    dpg = Mock()
    dpg.key = portgroup_key
    dpg.name = portgroup_name
    dvs = Mock()
    dpg.config.distributedVirtualSwitch = dvs
    dvs.FetchDVPorts.return_value = []
    return VirtualNetworkModel(dpg, vnc_vn)


@pytest.fixture()
def vnc_vn_1():
    return create_vnc_vn(name='DPG1', uuid='vnc_vn_uuid_1')


@pytest.fixture()
def vnc_vn_2():
    return create_vnc_vn(name='DPG2', uuid='vnc_vn_uuid_2')


@pytest.fixture()
def vn_model_1(vnc_vn_1):
    return create_vn_model(vnc_vn=vnc_vn_1,
                           portgroup_key='dvportgroup-1', portgroup_name='DPG1')


@pytest.fixture()
def vn_model_2(vnc_vn_2):
    return create_vn_model(vnc_vn=vnc_vn_2,
                           portgroup_key='dvportgroup-2', portgroup_name='DPG2')


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


@pytest.fixture()
def contrail_vm_properties():
    return {
        'config.instanceUuid': '12345678-1234-1234-1234-123456789012',
        'name': 'ContrailVM'
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
def vm_renamed_update():
    event = Mock(spec=vim.event.VmRenamedEvent())
    event.oldName = 'VM1'
    event.newName = 'VM1-renamed'
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
    device_spec = Mock(spec=vim.vm.device.VirtualDeviceSpec(), device=device)
    event.configSpec.deviceChange = [device_spec]
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
    esxi_client = Mock()
    esxi_client.read_vm_properties.return_value = vm_properties_1
    return esxi_client


@pytest.fixture()
def vlan_id_pool():
    vlan_pool = VlanIdPool(0, 100)
    return vlan_pool


def assert_vmi_model_state(vmi_model, mac_address=None, ip_address=None,
                           vlan_id=None, display_name=None, vn_model=None, vm_model=None):
    if mac_address is not None:
        assert vmi_model.vcenter_port.mac_address == mac_address
    if ip_address is not None:
        assert vmi_model.vnc_instance_ip.instance_ip_address == ip_address
    if vlan_id is not None:
        assert vmi_model.vcenter_port.vlan_id == vlan_id
    if display_name is not None:
        assert vmi_model.display_name == display_name
    if vn_model is not None:
        assert vmi_model.vn_model == vn_model
    if vm_model is not None:
        assert vmi_model.vm_model == vm_model


def assert_vm_model_state(vm_model, uuid=None, name=None, has_ports=None):
    if uuid is not None:
        assert vm_model.uuid == uuid
    if name is not None:
        assert vm_model.name == name
    if has_ports is None:
        has_ports = {}
    for mac_address, portgroup_key in has_ports.items():
        assert mac_address in [port.mac_address for port in vm_model.ports]
        assert next(port.portgroup_key for port in vm_model.ports if port.mac_address == mac_address) == portgroup_key


def assert_vnc_vmi_state(vnc_vmi, mac_address=None, vnc_vm_uuid=None, vnc_vn_uuid=None):
    if mac_address is not None:
        assert vnc_vmi.get_virtual_machine_interface_mac_addresses().mac_address == [mac_address]
    if vnc_vm_uuid is not None:
        assert vnc_vm_uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_machine_refs()]
    if vnc_vn_uuid is not None:
        assert vnc_vn_uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()]


def assert_vnc_vm_state(vnc_vm, uuid=None, name=None):
    if uuid is not None:
        assert vnc_vm.uuid == uuid
    if name is not None:
        assert vnc_vm.name == name


def test_vm_created(vcenter_api_client, vn_model_1, vm_created_update,
                    esxi_api_client, vnc_api_client, vnc_vn_1, vlan_id_pool):
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vn_service = VirtualNetworkService(esxi_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(vcenter_api_client, vnc_api_client,
                                                 database, vlan_id_pool=vlan_id_pool)
    vrouter_port_service = VRouterPortService(vrouter_api_client, database)
    controller = VmwareController(vm_service, vn_service, vmi_service, vrouter_port_service, [])

    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    vcenter_api_client.get_vlan_id.return_value = None
    reserve_vlan_ids(vlan_id_pool, [0, 1])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # Check if VM Model has been saved properly:
    # - in VNC:
    vnc_api_client.update_or_create_vm.assert_called_once()
    vnc_vm = vnc_api_client.update_or_create_vm.call_args[0][0]
    assert_vnc_vm_state(vnc_vm, uuid='12345678-1234-1234-1234-123456789012',
                        name='12345678-1234-1234-1234-123456789012')

    # - in Database:
    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')
    assert_vm_model_state(vm_model, uuid='12345678-1234-1234-1234-123456789012', name='VM1')

    # Check if VMI Model has been saved properly:
    # - in VNC
    vnc_api_client.update_or_create_vmi.assert_called_once()
    vnc_vmi = vnc_api_client.update_or_create_vmi.call_args[0][0]
    assert_vnc_vmi_state(vnc_vmi, mac_address='11:11:11:11:11:11',
                         vnc_vm_uuid=vnc_vm.uuid, vnc_vn_uuid=vnc_vn_1.uuid)

    # - in Database
    vmi_model = database.get_all_vmi_models()[0]

    # Check if VMI Model's Instance IP has been created in VNC:
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    # Check if VMI's vRouter Port has been added:
    vrouter_api_client.add_port.assert_called_once_with(vmi_model)

    # Check if VLAN ID has been set using VLAN Override
    vcenter_port = vcenter_api_client.set_vlan_id.call_args[0][0]
    assert vcenter_port.port_key == '10'
    assert vcenter_port.vlan_id == 2

    # Check inner VMI model state
    assert_vmi_model_state(
        vmi_model,
        mac_address='11:11:11:11:11:11',
        ip_address='192.168.100.5',
        vlan_id=2,
        display_name='vmi-DPG1-VM1',
        vn_model=vn_model_1,
        vm_model=vm_model
    )


def test_vm_renamed(vcenter_api_client, vn_model_1, vm_created_update,
                    esxi_api_client, vm_renamed_update, vlan_id_pool,
                    vm_properties_renamed, vnc_api_client):
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vn_service = VirtualNetworkService(esxi_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(
        vcenter_api_client,
        vnc_api_client,
        database,
        vlan_id_pool=vlan_id_pool
    )
    vrouter_port_service = VRouterPortService(vrouter_api_client, database)
    vm_renamed_handler = VmRenamedHandler(vm_service, vmi_service, vrouter_port_service)
    controller = VmwareController(vm_service, vn_service, vmi_service, vrouter_port_service, [vm_renamed_handler])

    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    vcenter_api_client.get_vlan_id.return_value = None
    reserve_vlan_ids(vlan_id_pool, [0, 1])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # A user renames the VM in vSphere and VmRenamedEvent arrives
    esxi_api_client.read_vm_properties.return_value = vm_properties_renamed
    controller.handle_update(vm_renamed_update)

    # Check if VM Model has been saved properly:
    # - in VNC:
    assert vnc_api_client.update_or_create_vmi.call_count == 2
    vnc_vm = vnc_api_client.update_or_create_vm.call_args[0][0]
    assert_vnc_vm_state(vnc_vm, uuid='12345678-1234-1234-1234-123456789012',
                        name='12345678-1234-1234-1234-123456789012')

    # - in Database:
    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')
    assert_vm_model_state(vm_model, uuid='12345678-1234-1234-1234-123456789012', name='VM1-renamed')

    # Check if VMI Model has been saved properly:
    # - in VNC
    assert vnc_api_client.update_or_create_vmi.call_count == 2
    vnc_vmi = vnc_api_client.update_or_create_vmi.call_args[0][0]
    assert_vnc_vmi_state(vnc_vmi, mac_address='11:11:11:11:11:11', vnc_vm_uuid=vnc_vm.uuid)

    # - in Database
    vmi_model = database.get_all_vmi_models()[0]

    # Check if VMI Model's Instance IP has been created in VNC:
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    # Check if VMI's vRouter Port has been added:
    vrouter_api_client.add_port.called_with(vmi_model)
    assert vrouter_api_client.add_port.call_count == 2

    # Check if VLAN ID has been set using VLAN Override
    vcenter_port = vcenter_api_client.set_vlan_id.call_args[0][0]
    assert vcenter_port.port_key == '10'
    assert vcenter_port.vlan_id == 2

    # Check inner VMI model state
    assert_vmi_model_state(
        vmi_model,
        mac_address='11:11:11:11:11:11',
        ip_address='192.168.100.5',
        vlan_id=2,
        display_name='vmi-DPG1-VM1-renamed',
        vn_model=vn_model_1,
        vm_model=vm_model
    )


def test_vm_reconfigured(vcenter_api_client, vn_model_1, vn_model_2, vm_created_update,
                         esxi_api_client, vm_reconfigure_update, vnc_api_client, vnc_vn_2,
                         vmware_vm_1, vlan_id_pool):
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vn_service = VirtualNetworkService(vcenter_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(
        vcenter_api_client,
        vnc_api_client,
        database,
        vlan_id_pool=vlan_id_pool
    )
    vrouter_port_service = VRouterPortService(vrouter_api_client, database)
    vm_reconfigure_handler = VmReconfiguredHandler(vm_service, vn_service, vmi_service, vrouter_port_service)
    controller = VmwareController(vm_service, vn_service, vmi_service, vrouter_port_service, [vm_reconfigure_handler])

    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)
    database.save(vn_model_2)

    # Some vlan ids should be already reserved
    vcenter_api_client.get_vlan_id.return_value = None
    reserve_vlan_ids(vlan_id_pool, [0, 1, 2, 3])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # After a portgroup is changed, the port key is also changed
    vmware_vm_1.config.hardware.device[0].backing.port.portgroupKey = 'dvportgroup-2'
    vmware_vm_1.config.hardware.device[0].backing.port.portKey = '11'

    # Then VmReconfiguredEvent is being handled
    controller.handle_update(vm_reconfigure_update)

    # Check if VM Model has been saved properly in Database:
    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')
    assert_vm_model_state(vm_model, has_ports={'11:11:11:11:11:11': 'dvportgroup-2'})

    # Check that VM was not updated in VNC except VM create event
    vnc_api_client.update_or_create_vm.assert_called_once()

    # Check if VMI Model has been saved properly:

    # - in Database
    vmi_models = database.get_vmi_models_by_vm_uuid('12345678-1234-1234-1234-123456789012')
    assert len(vmi_models) == 1
    vmi_model = vmi_models[0]

    # - in VNC
    vnc_api_client.delete_vmi.assert_called_once_with(vmi_model.uuid)
    assert vnc_api_client.update_or_create_vmi.call_count == 2
    vnc_vmi = vnc_api_client.update_or_create_vmi.call_args[0][0]
    assert_vnc_vmi_state(vnc_vmi, mac_address='11:11:11:11:11:11', vnc_vn_uuid=vnc_vn_2.uuid)

    # Check if VMI Model's Instance IP has been updated in VNC:
    assert vnc_api_client.create_and_read_instance_ip.call_count == 2
    new_instance_ip = vmi_model.vnc_instance_ip
    assert vnc_api_client.create_and_read_instance_ip.call_args[0][0] == new_instance_ip
    assert vnc_vn_2.uuid in [ref['uuid'] for ref in new_instance_ip.get_virtual_network_refs()]

    # Check if VMI's vRouter Port has been updated:
    assert vrouter_api_client.delete_port.call_count == 3
    assert vrouter_api_client.delete_port.call_args[0][0] == vmi_model.uuid
    assert vrouter_api_client.add_port.call_count == 2
    assert vrouter_api_client.add_port.call_args[0][0] == vmi_model

    # Check if VLAN ID has been set using VLAN Override
    assert vcenter_api_client.set_vlan_id.call_count == 2
    vcenter_port = vcenter_api_client.set_vlan_id.call_args[0][0]
    assert vcenter_port.port_key == '11'
    assert vcenter_port.vlan_id == 5

    # Check inner VMI model state
    assert_vmi_model_state(
        vmi_model,
        mac_address='11:11:11:11:11:11',
        ip_address='192.168.100.5',
        vlan_id=5,
        display_name='vmi-DPG2-VM1',
        vn_model=vn_model_2
    )


def test_vm_created_vlan_id(vcenter_api_client, vn_model_1, vm_created_update,
                            esxi_api_client, vnc_api_client, vlan_id_pool):
    """
    What happens when the created interface is already using an overriden VLAN ID?
    We should keep it, not removing old/adding new VLAN ID, since it breaks the connectivity
    for a moment.
    """
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vn_service = VirtualNetworkService(esxi_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(
        vcenter_api_client,
        vnc_api_client,
        database,
        vlan_id_pool=vlan_id_pool
    )
    vrouter_port_service = VRouterPortService(vrouter_api_client, database)
    controller = VmwareController(vm_service, vn_service, vmi_service, vrouter_port_service, [])

    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    reserve_vlan_ids(vlan_id_pool, [0, 1, 5])

    # When we ask vCenter for the VLAN ID it turns out that the VLAN ID has already been overridden
    vcenter_api_client.get_vlan_id.return_value = 5

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # Check if VLAN ID has not been changed
    vcenter_api_client.set_vlan_id.assert_not_called()

    # Check inner VMI model state
    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')
    vmi_model = database.get_all_vmi_models()[0]
    assert_vmi_model_state(
        vmi_model,
        mac_address='11:11:11:11:11:11',
        ip_address='192.168.100.5',
        vlan_id=5,
        display_name='vmi-DPG1-VM1',
        vn_model=vn_model_1,
        vm_model=vm_model
    )


def test_contrail_vm(vcenter_api_client, vm_created_update, esxi_api_client,
                     vnc_api_client, contrail_vm_properties):
    """ We don't need ContrailVM model for CVM to operate properly. """
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vn_service = VirtualNetworkService(esxi_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(vcenter_api_client, vnc_api_client, database)
    vrouter_port_service = VRouterPortService(vrouter_api_client, database)
    esxi_api_client.read_vm_properties.return_value = contrail_vm_properties
    controller = VmwareController(vm_service, vn_service, vmi_service, vrouter_port_service, [])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # VM model has not been saved in the database
    assert not database.get_all_vm_models()

    # There were no calls to vnc_api
    vnc_api_client.update_or_create_vm.assert_not_called()
    vnc_api_client.update_or_create_vmi.assert_not_called()

    # There were no calls to vrouter_api
    vrouter_api_client.add_port.assert_not_called()
