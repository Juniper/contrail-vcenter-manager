# pylint: disable=redefined-outer-name
import pytest
from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api

from cvm.constants import ID_PERMS
from cvm.controllers import (GuestNetHandler, PowerStateHandler, UpdateHandler,
                             VmReconfiguredHandler, VmRegisteredHandler,
                             VmRemovedHandler, VmRenamedHandler,
                             VmUpdatedHandler, VmwareController,
                             VmwareToolsStatusHandler)
from cvm.database import Database
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel, VlanIdPool)
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService,
                          VRouterPortService, VlanIdService)
from tests.utils import assign_ip_to_instance_ip, wrap_into_update_set


@pytest.fixture()
def vnc_vn_1(project, ipam):
    vnc_vn = vnc_api.VirtualNetwork(name='DPG1', parent=project)
    vnc_vn.set_uuid('vnc-vn-uuid-1')
    vnc_vn.set_network_ipam(ipam, None)
    return vnc_vn


@pytest.fixture()
def vnc_vn_2(project, ipam):
    vnc_vn = vnc_api.VirtualNetwork(name='DPG2', parent=project)
    vnc_vn.set_uuid('vnc-vn-uuid-2')
    vnc_vn.set_network_ipam(ipam, None)
    return vnc_vn


@pytest.fixture()
def vnc_vm():
    vm = vnc_api.VirtualMachine('vnc-vm-uuid')
    vm.set_uuid('vnc-vm-uuid')
    vm.set_annotations(vnc_api.KeyValuePairs(
        [vnc_api.KeyValuePair('vrouter-uuid', 'vrouter-uuid-1')]))
    return vm


@pytest.fixture()
def vnc_vmi(project, vnc_vm, vnc_vn_1):
    vmi = vnc_api.VirtualMachineInterface('vnc-vmi-uuid', parent_obj=project)
    vmi.set_uuid('vnc-vmi-uuid')
    vmi.add_virtual_machine(vnc_vm)
    vmi.set_virtual_network(vnc_vn_1)
    vmi.set_annotations(vnc_api.KeyValuePairs(
        [vnc_api.KeyValuePair('vrouter-uuid', 'vrouter-uuid-1'),
         vnc_api.KeyValuePair('key-1', 'value-1')]
    ))
    return vmi


@pytest.fixture()
def instance_ip(vnc_vmi, vnc_vn_1, vnc_vm):
    ip_name = 'ip-' + vnc_vn_1.name + '-' + vnc_vm.name
    ip_uuid = VirtualMachineInterfaceModel.construct_instance_ip_uuid(ip_name)

    ip = vnc_api.InstanceIp(
        name=ip_uuid,
        display_name=ip_name,
        id_perms=ID_PERMS,
    )

    ip.set_instance_ip_address('10.10.10.1')
    ip.set_uuid(ip_uuid)
    ip.set_virtual_network(vnc_vn_1)
    ip.set_virtual_machine_interface(vnc_vmi)
    ip.annotations = ip.annotations or vnc_api.KeyValuePairs()
    ip.annotations.add_key_value_pair(
        vnc_api.KeyValuePair('vrouter-uuid', 'vrouter-uuid-1')
    )
    ip.annotations.add_key_value_pair(
        vnc_api.KeyValuePair('key-1', 'value-1')
    )
    return ip


@pytest.fixture()
def vn_model_1(vnc_vn_1):
    dpg = Mock()
    dpg.key = 'dvportgroup-1'
    return VirtualNetworkModel(dpg, vnc_vn_1)


@pytest.fixture()
def vn_model_2(vnc_vn_2):
    dpg = Mock()
    dpg.key = 'dvportgroup-2'
    return VirtualNetworkModel(dpg, vnc_vn_2)


@pytest.fixture()
def portgroup():
    pg = Mock(key='dvportgroup-1')
    pg.configure_mock(name='DPG1')
    pg.config.policy = Mock(spec=vim.dvs.DistributedVirtualPortgroup.PortgroupPolicy())
    pg.config.policy.vlanOverrideAllowed = False
    pg.config.defaultPortConfig = Mock(spec=vim.dvs.VmwareDistributedVirtualSwitch.VmwarePortConfigPolicy())
    pg.config.configVersion = '1'
    pg.config.name = 'portgroup'
    pg.config.numPorts = 100
    pg.config.type = 'portgroup-type'
    pg.config.autoExpand = True
    pg.config.vmVnicNetworkResourcePoolKey = 'poolkey'
    pg.config.description = 'description'
    return pg


@pytest.fixture()
def vmware_vm_1(host_1):
    vmware_vm = Mock(spec=vim.VirtualMachine)
    vmware_vm.configure_mock(name='VM1')
    vmware_vm.summary.runtime.host = host_1
    vmware_vm.config.instanceUuid = 'vmware-vm-uuid-1'
    backing = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
    backing.port = Mock(portgroupKey='dvportgroup-1', portKey='10')
    vmware_vm.config.hardware.device = [Mock(backing=backing, macAddress='mac-address')]
    return vmware_vm


@pytest.fixture()
def vmware_vm_1_updated(host_1):
    vmware_vm = Mock(spec=vim.VirtualMachine)
    vmware_vm.configure_mock(name='VM1')
    vmware_vm.summary.runtime.host = host_1
    vmware_vm.config.instanceUuid = 'vmware-vm-uuid-1'
    backing = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
    backing.port = Mock(portgroupKey='dvportgroup-2', portKey='10')
    vmware_vm.config.hardware.device = [Mock(backing=backing, macAddress='mac-address')]
    return vmware_vm


@pytest.fixture()
def vmware_vm_2(host_1):
    vmware_vm = Mock(spec=vim.VirtualMachine)
    vmware_vm.configure_mock(name='VM2')
    vmware_vm.summary.runtime.host = host_1
    vmware_vm.config.instanceUuid = 'vmware-vm-uuid-2'
    backing = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
    backing.port = Mock(portgroupKey='dvportgroup-2', portKey='20')
    vmware_vm.config.hardware.device = [Mock(backing=backing, macAddress='mac-address-2')]
    return vmware_vm


@pytest.fixture()
def host_1():
    host = Mock(vm=[])
    host.configure_mock(name='host-1')
    return host


@pytest.fixture()
def host_2():
    host = Mock(vm=[])
    host.configure_mock(name='host-2')
    return host


@pytest.fixture()
def vm_properties_1():
    return {
        'config.instanceUuid': 'vmware-vm-uuid-1',
        'name': 'VM1',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }


@pytest.fixture()
def vm_properties_2():
    return {
        'config.instanceUuid': 'vmware-vm-uuid-2',
        'name': 'VM2',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }


@pytest.fixture()
def vm_properties_renamed():
    return {
        'config.instanceUuid': 'vmware-vm-uuid-1',
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
def vm_model(vmware_vm_1, vm_properties_1):
    model = VirtualMachineModel(vmware_vm_1, vm_properties_1)
    model.property_filter = Mock()
    return model


@pytest.fixture()
def vm_model_2(vmware_vm_2, vm_properties_2):
    model = VirtualMachineModel(vmware_vm_2, vm_properties_2)
    model.property_filter = Mock()
    return model


@pytest.fixture()
def vmi_model(vm_model, vn_model_1, project, security_group):
    vmi = VirtualMachineInterfaceModel(
        vm_model, vn_model_1,
        Mock(mac_address='mac-address', portgroup_key='dvportgroup-1', vlan_id=1)
    )
    vmi.parent = project
    vmi.security_group = security_group
    return vmi


@pytest.fixture()
def vmi_model_2(vm_model_2, vn_model_2, project, security_group):
    vmi = VirtualMachineInterfaceModel(
        vm_model_2, vn_model_2,
        Mock(mac_address='mac-address-2', portgroup_key='dvportgroup-1', vlan_id=2)
    )
    vmi.parent = project
    vmi.security_group = security_group
    return vmi


@pytest.fixture()
def vm_created_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmCreatedEvent())
    event.vm.vm = vmware_vm_1
    return wrap_into_update_set(event=event)


@pytest.fixture()
def vm_registered_update(vmware_vm_1):
    event = Mock(spec=vim.event.VmRegisteredEvent())
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
    device.macAddress = 'mac-address'
    device_spec = Mock(spec=vim.vm.device.VirtualDeviceSpec(), device=device)
    event.configSpec.deviceChange = [device_spec]
    return wrap_into_update_set(event=event)


@pytest.fixture()
def project():
    proj = vnc_api.Project(
        name='project-name',
        parent_obj=vnc_api.Domain(name='domain-name')
    )
    proj.set_uuid('project-uuid')
    return proj


@pytest.fixture()
def security_group(project):
    return vnc_api.SecurityGroup(
        name='security-group-name',
        parent_obj=project,
    )


@pytest.fixture()
def ipam(project):
    return vnc_api.NetworkIpam(
        name='ipam-name',
        parent_obj=project,
    )


@pytest.fixture()
def vnc_api_client(project, security_group):
    vnc_client = Mock()
    vnc_client.read_or_create_project.return_value = project
    vnc_client.read_or_create_security_group.return_value = security_group
    vnc_client.create_and_read_instance_ip.side_effect = assign_ip_to_instance_ip
    vnc_client.read_vmi.return_value = None
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
    esxi_client.read_vrouter_uuid.return_value = 'vrouter-uuid-1'
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
    vlan_pool = VlanIdPool(0, 4095)
    return vlan_pool


@pytest.fixture()
def nic_info():
    return Mock(
        spec=vim.vm.GuestInfo.NicInfo(),
        ipAddress=['192.168.100.5'],
        macAddress='mac-address',
    )


@pytest.fixture()
def nic_info_update(nic_info):
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
def vmware_tools_not_running_update(vmware_vm_1):
    change = Mock(spec=vmodl.query.PropertyCollector.Change())
    change.name = 'guest.toolsRunningStatus'
    change.val = 'guestToolsNotRunning'
    return wrap_into_update_set(change=change, obj=vmware_vm_1)


@pytest.fixture()
def vmware_tools_running_update(vmware_vm_1):
    change = Mock(spec=vmodl.query.PropertyCollector.Change())
    change.name = 'guest.toolsRunningStatus'
    change.val = 'guestToolsRunning'
    return wrap_into_update_set(change=change, obj=vmware_vm_1)


@pytest.fixture()
def vm_service(esxi_api_client, vcenter_api_client, vnc_api_client, database):
    return VirtualMachineService(esxi_api_client, vcenter_api_client, vnc_api_client, database)


@pytest.fixture()
def vn_service(vcenter_api_client, vnc_api_client, database):
    return VirtualNetworkService(vcenter_api_client, vnc_api_client, database)


@pytest.fixture()
def vmi_service(esxi_api_client, vcenter_api_client, vnc_api_client, database, vlan_id_pool):
    return VirtualMachineInterfaceService(vcenter_api_client, vnc_api_client,
                                          database, esxi_api_client, vlan_id_pool=vlan_id_pool)


@pytest.fixture()
def vrouter_port_service(vrouter_api_client, database):
    return VRouterPortService(vrouter_api_client, database)


@pytest.fixture()
def vlan_id_service(vcenter_api_client, esxi_api_client, vlan_id_pool, database):
    return VlanIdService(vcenter_api_client, esxi_api_client, vlan_id_pool, database)


@pytest.fixture()
def database():
    return Database()


@pytest.fixture()
def vrouter_api_client():
    return Mock()


@pytest.fixture()
def controller(vm_service, vn_service, vmi_service, vrouter_port_service, vlan_id_service, lock):
    handlers = [
        VmUpdatedHandler(vm_service, vn_service, vmi_service, vrouter_port_service, vlan_id_service),
        VmRenamedHandler(vm_service, vmi_service, vrouter_port_service),
        VmReconfiguredHandler(vm_service, vn_service, vmi_service, vrouter_port_service, vlan_id_service),
        VmRemovedHandler(vm_service, vmi_service, vrouter_port_service, vlan_id_service),
        VmRegisteredHandler(vm_service, vn_service, vmi_service, vrouter_port_service, vlan_id_service),
        GuestNetHandler(vmi_service, vrouter_port_service),
        PowerStateHandler(vm_service, vrouter_port_service),
        VmwareToolsStatusHandler(vm_service)
    ]
    for handler in handlers:
        handler._validate_event = Mock(return_value=True)
    update_handler = UpdateHandler(handlers)
    return VmwareController(vm_service, vn_service, vmi_service,
                            vrouter_port_service, vlan_id_service, update_handler, lock)
