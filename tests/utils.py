from builtins import next
from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module

from cvm.clients import make_filter_spec


def create_dv_port(vlan_id, vrouter_uuid):
    port = Mock()
    port.config.setting.vlan = Mock(spec=vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec)
    port.config.setting.vlan.vlanId = vlan_id
    vm_mock = Mock()
    vm_mock.name = 'ContrailVM'
    vm_mock.config.instanceUuid = vrouter_uuid
    port.proxyHost.vm = [vm_mock]
    return port


def create_property_filter(obj, filters):
    filter_spec = make_filter_spec(obj, filters)
    return vmodl.query.PropertyCollector.Filter(filter_spec)


def reserve_vlan_ids(vlan_id_pool, vlan_ids):
    for vlan_id in vlan_ids:
        vlan_id_pool.reserve(vlan_id)


def assign_ip_to_instance_ip(vmi_model):
    vmi_model.vnc_instance_ip.set_instance_ip_address('192.168.100.5')
    return vmi_model.vnc_instance_ip


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
    for mac_address, portgroup_key in list(has_ports.items()):
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
