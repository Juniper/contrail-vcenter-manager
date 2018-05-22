import pytest
from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import InstanceIp, Project, VirtualNetwork

from cvm.controllers import VmwareController
from cvm.database import Database
from cvm.models import VirtualNetworkModel, VlanIdPool
from cvm.services import VirtualMachineInterfaceService, VirtualMachineService


@pytest.fixture(scope='module')
def vnc_vn_1():
    vnc_vn = VirtualNetwork(name='DPG1', parent=Project())
    return vnc_vn


@pytest.fixture(scope='module')
def vn_model_1(vnc_vn_1):
    dpg = Mock()
    dpg.key = 'dportgroup-1'
    dpg.name = 'DPG1'
    dvs = Mock()
    dpg.config.distributedVirtualSwitch = dvs
    dvs.FetchDVPorts.return_value = []
    return VirtualNetworkModel(dpg, vnc_vn_1, VlanIdPool(0, 100))


@pytest.fixture(scope='module')
def vmware_vm_1():
    vmware_vm = Mock()
    vmware_vm.summary.runtime.host.vm = []
    backing = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
    backing.port = Mock(portgroupKey='dportgroup-1', portKey='10')
    vmware_vm.config.hardware.device = [Mock(backing=backing, macAddress='11:11:11:11:11:11')]
    return vmware_vm


@pytest.fixture(scope='module')
def vm_properties_1():
    return {
        'config.instanceUuid': '12345678-1234-1234-1234-123456789012',
        'name': 'VM1'
    }


@pytest.fixture(scope='module')
def instance_ip():
    instance_ip = InstanceIp()
    instance_ip.set_instance_ip_address('192.168.100.5')
    return instance_ip


@pytest.fixture(scope='module')
def vm_created_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmCreatedEvent())
    event.vm.vm = vmware_vm_1
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


@pytest.fixture(scope='module')
def vnc_api_client(instance_ip):
    vnc_client = Mock()
    vnc_client.read_or_create_project.return_value = Project()
    vnc_client.create_and_read_instance_ip.return_value = instance_ip
    return vnc_client


@pytest.fixture(scope='module')
def vcenter_api_client():
    vcenter_client = Mock()
    vcenter_client.__enter__ = Mock()
    vcenter_client.__exit__ = Mock()
    vcenter_client.get_ip_pool_for_dpg.return_value = None
    return vcenter_client


def test_vm_created(vcenter_api_client, vnc_api_client, vn_model_1, vm_created_update, vm_properties_1):
    esxi_api_client = Mock()
    esxi_api_client.read_vm_properties.return_value = vm_properties_1
    vrouter_api_client = Mock()
    database = Database()
    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vmi_service = VirtualMachineInterfaceService(vcenter_api_client, vnc_api_client, vrouter_api_client, database)
    controller = VmwareController(vm_service, None, vmi_service)

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
    # TODO: Pass the proper lanIdPool in the constructor and uncomment this
    # assert vmi_model.vlan_id == 3

    # Check if VLAN ID has been set using VLAN Override
    # vcenter_api_client.set_vlan_id.assert_called_once_with(vmi_model.vn_model.dvs, '10', 3)
