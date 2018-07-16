from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api

from cvm.clients import make_filter_spec
from cvm.models import VirtualMachineModel, VirtualNetworkModel


def create_vmware_vm_mock(network=None, uuid=None, name=None):
    vmware_vm = Mock(spec=vim.VirtualMachine)
    vmware_vm.summary.runtime.host = Mock(vm=[vmware_vm])
    vmware_vm.config.hardware.device = []
    vm_properties = {
        'config.instanceUuid': uuid or 'd376b6b4-943d-4599-862f-d852fd6ba425',
        'name': name or 'VM',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }
    vmware_vm.config.instanceUuid = uuid or 'd376b6b4-943d-4599-862f-d852fd6ba425'
    vmware_vm.network = network
    vmware_vm.guest.net = []
    if network:
        device = Mock()
        backing_mock = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo())
        device.backing = backing_mock
        device.backing.port.portgroupKey = network[0].key
        device.macAddress = 'c8:5b:76:53:0f:f5'
        vmware_vm.config.hardware.device = [device]
    return vmware_vm, vm_properties


def create_dpg_mock(**kwargs):
    dpg_mock = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
    for kwarg in kwargs:
        setattr(dpg_mock, kwarg, kwargs[kwarg])
    dpg_mock.config.distributedVirtualSwitch.FetchDVPorts.return_value = []
    return dpg_mock


def create_vcenter_client_mock():
    vcenter_client = Mock()
    vcenter_client.__enter__ = Mock()
    vcenter_client.__exit__ = Mock()
    return vcenter_client


def create_vnc_client_mock():
    vnc_client = Mock()
    project = vnc_api.Project()
    project.set_uuid('project-uuid')
    vnc_client.read_or_create_project.return_value = project
    vnc_client.read_security_group.return_value = vnc_api.SecurityGroup()
    return vnc_client


def create_property_filter(obj, filters):
    filter_spec = make_filter_spec(obj, filters)
    return vmodl.query.PropertyCollector.Filter(filter_spec)


def create_vm_model(network=None, uuid=None):
    vmware_vm, vm_properties = create_vmware_vm_mock(network=network, uuid=uuid)
    return VirtualMachineModel(vmware_vm, vm_properties)


def create_port_mock(vlan_id):
    port = Mock()
    port.config.setting.vlan.vlanId = vlan_id
    return port


def reserve_vlan_ids(vlan_id_pool, vlan_ids):
    for vlan_id in vlan_ids:
        vlan_id_pool.reserve(vlan_id)


def create_ipam():
    return vnc_api.NetworkIpam(
        name='IPAM',
        parent_obj=vnc_api.Project()
    )


def create_vnc_vn(name, uuid):
    vnc_vn = vnc_api.VirtualNetwork(name=name, parent=vnc_api.Project())
    vnc_vn.set_uuid(uuid)
    vnc_vn.set_network_ipam(create_ipam(), None)
    return vnc_vn


def create_vn_model(vnc_vn, portgroup_key):
    dpg = Mock()
    dpg.key = portgroup_key
    return VirtualNetworkModel(dpg, vnc_vn)


def assign_ip_to_instance_ip(instance_ip):
    instance_ip.set_instance_ip_address('192.168.100.5')
    return instance_ip


def dont_assign_ip_to_instance_ip(instance_ip):
    return instance_ip


def wrap_into_update_set(event=None, change=None, obj=None):
    update_set = vmodl.query.PropertyCollector.UpdateSet()
    filter_update = vmodl.query.PropertyCollector.FilterUpdate()
    if change is None:
        change = vmodl.query.PropertyCollector.Change()
        change.name = 'latestPage'
        change.val = event
    object_update = vmodl.query.PropertyCollector.ObjectUpdate()
    object_update.changeSet = [change]
    if obj is not None:
        object_update.obj = obj
    object_set = [object_update]
    filter_update.objectSet = object_set
    update_set.filterSet = [filter_update]
    return update_set


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


def assert_vm_model_state(vm_model, uuid=None, name=None, has_ports=None,
                          is_powered_on=None, tools_running=None):
    if uuid is not None:
        assert vm_model.uuid == uuid
    if name is not None:
        assert vm_model.name == name
    if is_powered_on is not None:
        assert vm_model.is_powered_on == is_powered_on
    if tools_running is not None:
        assert vm_model.tools_running == tools_running
    if has_ports is None:
        has_ports = {}
    for mac_address, portgroup_key in has_ports.items():
        assert mac_address in [port.mac_address for port in vm_model.ports]
        assert next(port.portgroup_key for port in vm_model.ports if port.mac_address == mac_address) == portgroup_key


def assert_vn_model_state(vn_model, uuid=None, name=None, key=None,
                          vnc_vn=None, vmware_vn=None):
    if uuid is not None:
        assert vn_model.uuid == uuid
    if name is not None:
        assert vn_model.name == name
    if key is not None:
        assert vn_model.key == key
    if vnc_vn is not None:
        assert vn_model.vnc_vn == vnc_vn
    if vmware_vn is not None:
        assert vn_model.vmware_vn == vmware_vn


def assert_vnc_vmi_state(vnc_vmi, mac_address=None, vnc_vm_uuid=None, vnc_vn_uuid=None):
    if mac_address is not None:
        assert vnc_vmi.get_virtual_machine_interface_mac_addresses().mac_address == [mac_address]
    if vnc_vm_uuid is not None:
        assert vnc_vm_uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_machine_refs()]
    if vnc_vn_uuid is not None:
        assert vnc_vn_uuid in [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()]


def assert_vnc_vm_state(vnc_vm, uuid=None, name=None, display_name=None, owner=None):
    if uuid is not None:
        assert vnc_vm.uuid == uuid
    if name is not None:
        assert vnc_vm.name == name
    if display_name is not None:
        assert vnc_vm.display_name == display_name
    if owner is not None:
        assert vnc_vm.get_perms2().get_owner() == owner
