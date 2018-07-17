# pylint: disable=redefined-outer-name
import pytest
from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api

from cvm.controllers import (GuestNetHandler, UpdateHandler,
                             VmReconfiguredHandler, VmRenamedHandler,
                             VmUpdatedHandler, VmwareController, PowerStateHandler,
                             VmwareToolsStatusHandler, VmRemovedHandler)
from cvm.database import Database
from cvm.models import VlanIdPool
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService,
                          VRouterPortService)
from tests.utils import (assign_ip_to_instance_ip, create_vn_model,
                         create_vnc_vn, wrap_into_update_set)


@pytest.fixture()
def vnc_vn_1():
    return create_vnc_vn(name='DPG1', uuid='vnc_vn_uuid_1')


@pytest.fixture()
def vnc_vn_2():
    return create_vnc_vn(name='DPG2', uuid='vnc_vn_uuid_2')


@pytest.fixture()
def vn_model_1(vnc_vn_1):
    return create_vn_model(vnc_vn=vnc_vn_1, portgroup_key='dvportgroup-1')


@pytest.fixture()
def vn_model_2(vnc_vn_2):
    return create_vn_model(vnc_vn=vnc_vn_2, portgroup_key='dvportgroup-2')


@pytest.fixture()
def vmware_vm_1():
    vmware_vm = Mock(spec=vim.VirtualMachine)
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
        'name': 'VM1',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }


@pytest.fixture()
def vm_properties_renamed():
    return {
        'config.instanceUuid': '12345678-1234-1234-1234-123456789012',
        'name': 'VM1-renamed',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }


@pytest.fixture()
def contrail_vm_properties():
    return {
        'config.instanceUuid': '12345678-1234-1234-1234-123456789012',
        'name': 'ContrailVM',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }


@pytest.fixture()
def vm_created_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmCreatedEvent())
    event.vm.vm = vmware_vm_1
    return wrap_into_update_set(event=event)


@pytest.fixture()
def vm_removed_update():
    event = Mock(spec=vim.event.VmRemovedEvent())
    event.vm.name = 'VM1'
    return wrap_into_update_set(event=event)


@pytest.fixture()
def vm_renamed_update():
    event = Mock(spec=vim.event.VmRenamedEvent())
    event.oldName = 'VM1'
    event.newName = 'VM1-renamed'
    return wrap_into_update_set(event=event)


@pytest.fixture()
def vm_reconfigured_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmReconfiguredEvent())
    event.vm.vm = vmware_vm_1
    port = Mock(spec=vim.dvs.PortConnection())
    port.portgroupKey = 'dvportgroup-2'
    device = Mock(spec=vim.vm.device.VirtualVmxnet3())
    device.backing.port = port
    device.macAddress = '11:11:11:11:11:11'
    device_spec = Mock(spec=vim.vm.device.VirtualDeviceSpec(), device=device)
    event.configSpec.deviceChange = [device_spec]
    return wrap_into_update_set(event=event)


@pytest.fixture()
def vnc_api_client():
    vnc_client = Mock()
    project = vnc_api.Project()
    project.set_uuid('project-uuid')
    vnc_client.read_or_create_project.return_value = project
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
def lock():
    semaphore = Mock()
    semaphore.__enter__ = Mock()
    semaphore.__exit__ = Mock()
    return semaphore


@pytest.fixture()
def vlan_id_pool():
    vlan_pool = VlanIdPool(0, 100)
    return vlan_pool


@pytest.fixture()
def nic_info_update():
    nic_info = Mock(spec=vim.vm.GuestInfo.NicInfo())
    nic_info.ipAddress = ['192.168.100.5']
    nic_info.macAddress = '11:11:11:11:11:11'
    change = Mock(spec=vmodl.query.PropertyCollector.Change())
    change.name = 'guest.net'
    change.val = [nic_info]
    return wrap_into_update_set(change=change)


@pytest.fixture()
def vm_power_off_state_update(vmware_vm_1):
    change = Mock(spec=vmodl.query.PropertyCollector.Change())
    change.name = 'runtime.powerState'
    change.val = 'poweredOff'
    return wrap_into_update_set(change=change, obj=vmware_vm_1)


@pytest.fixture()
def vm_power_on_state_update(vmware_vm_1):
    change = Mock(spec=vmodl.query.PropertyCollector.Change())
    change.name = 'runtime.powerState'
    change.val = 'poweredOn'
    return wrap_into_update_set(change=change, obj=vmware_vm_1)


@pytest.fixture()
def vm_disable_running_tools_update(vmware_vm_1):
    change = Mock(spec=vmodl.query.PropertyCollector.Change())
    change.name = 'guest.toolsRunningStatus'
    change.val = 'guestToolsNotRunning'
    return wrap_into_update_set(change=change, obj=vmware_vm_1)


@pytest.fixture()
def vm_enable_running_tools_update(vmware_vm_1):
    change = Mock(spec=vmodl.query.PropertyCollector.Change())
    change.name = 'guest.toolsRunningStatus'
    change.val = 'guestToolsRunning'
    return wrap_into_update_set(change=change, obj=vmware_vm_1)


@pytest.fixture()
def vm_service(esxi_api_client, vnc_api_client, database):
    return VirtualMachineService(esxi_api_client, vnc_api_client, database)


@pytest.fixture()
def vn_service(esxi_api_client, vnc_api_client, database):
    return VirtualNetworkService(esxi_api_client, vnc_api_client, database)


@pytest.fixture()
def vmi_service(vcenter_api_client, vnc_api_client, database, vlan_id_pool):
    return VirtualMachineInterfaceService(vcenter_api_client, vnc_api_client,
                                          database, vlan_id_pool=vlan_id_pool)


@pytest.fixture()
def vrouter_port_service(vrouter_api_client, database):
    return VRouterPortService(vrouter_api_client, database)


@pytest.fixture()
def database():
    return Database()


@pytest.fixture()
def vrouter_api_client():
    return Mock()


@pytest.fixture()
def controller(vm_service, vn_service, vmi_service, vrouter_port_service, lock):
    handlers = [
        VmUpdatedHandler(vm_service, vn_service, vmi_service, vrouter_port_service),
        VmRenamedHandler(vm_service, vmi_service, vrouter_port_service),
        VmReconfiguredHandler(vm_service, vn_service, vmi_service, vrouter_port_service),
        VmRemovedHandler(vm_service, vmi_service, vrouter_port_service),
        GuestNetHandler(vmi_service, vrouter_port_service),
        PowerStateHandler(vm_service, vrouter_port_service),
        VmwareToolsStatusHandler(vm_service)
    ]
    update_handler = UpdateHandler(handlers)
    return VmwareController(vm_service, vn_service, vmi_service, vrouter_port_service, update_handler, lock)
