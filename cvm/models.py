import ipaddress
import logging
import uuid
from collections import deque

from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import (IdPermsType, InstanceIp, KeyValuePair,
                             KeyValuePairs, MacAddressesType, VirtualMachine,
                             VirtualMachineInterface)

from cvm.constants import (CONTRAIL_VM_NAME, VNC_ROOT_DOMAIN,
                           VNC_VCENTER_PROJECT)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ID_PERMS = IdPermsType(creator='vcenter-manager',
                       enable=True)


def find_virtual_machine_ip_address(vmware_vm, port_group_name):
    try:
        return next(
            addr for nicInfo in vmware_vm.guest.net
            if is_nic_info_valid(nicInfo)
            for addr in nicInfo.ipAddress
            if (nicInfo.network == port_group_name and
                is_ipv4(addr.decode('utf-8')))
        )
    except (StopIteration, AttributeError):
        return None


def is_ipv4(string):
    return isinstance(ipaddress.ip_address(string), ipaddress.IPv4Address)


def is_nic_info_valid(info):
    return hasattr(info, 'ipAddress') and hasattr(info, 'network')


def find_vrouter_uuid(host):
    try:
        for vmware_vm in host.vm:
            if vmware_vm.name.startswith(CONTRAIL_VM_NAME):
                return vmware_vm.config.instanceUuid
    except AttributeError:
        pass
    return None


def find_vm_mac_address(vmware_vm, portgroup_key):
    try:
        devices = vmware_vm.config.hardware.device
        for device in devices:
            try:
                if device.backing.port.portgroupKey == portgroup_key:
                    return device.macAddress
            except AttributeError:
                pass
    except AttributeError:
        pass
    return None


def find_vmi_port_key(vmware_vm, mac_address):
    try:
        devices = vmware_vm.config.hardware.device
        for device in devices:
            try:
                if device.macAddress == mac_address:
                    return device.backing.port.portKey
            except AttributeError:
                pass
    except AttributeError:
        pass
    return None

class VirtualMachineModel(object):
    def __init__(self, vmware_vm, vm_properties):
        self.vmware_vm = vmware_vm  # TODO: Consider removing this
        self.vm_properties = vm_properties
        self.vrouter_uuid = find_vrouter_uuid(vmware_vm.summary.runtime.host)
        self.property_filter = None
        self.interfaces = self._read_interfaces()
        self._vnc_vm = None

    def update(self, vmware_vm, vm_properties):
        self.vmware_vm = vmware_vm  # TODO: Consider removing this
        self.vm_properties = vm_properties
        self.vrouter_uuid = find_vrouter_uuid(vmware_vm.summary.runtime.host)
        self.interfaces = self._read_interfaces()

    def rename(self, name):
        self.vm_properties['name'] = name

    def update_interface_portgroup_key(self, mac_address, portgroup_key):
        self.interfaces[mac_address] = portgroup_key

    def _read_interfaces(self):
        try:
            return {device.macAddress: device.backing.port.portgroupKey
                    for device in self.vmware_vm.config.hardware.device
                    if isinstance(device.backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)}
        except AttributeError:
            logger.error('Could not read Virtual Machine Interfaces for %s.', self.name)
        return None

    def destroy_property_filter(self):
        self.property_filter.DestroyPropertyFilter()

    @property
    def uuid(self):
        return self.vm_properties.get('config.instanceUuid')

    @property
    def name(self):
        return self.vm_properties.get('name')

    @property
    def is_contrail_vm(self):
        return 'ContrailVM' in self.name

    @property
    def is_powered_on(self):
        return self.vm_properties.get('runtime.powerState') == 'poweredOn'

    @property
    def tools_running(self):
        return self.vm_properties.get('guest.toolsRunningStatus') == 'guestToolsRunning'

    @property
    def vnc_vm(self):
        if not self._vnc_vm:
            self._vnc_vm = VirtualMachine(name=self.uuid,
                                          display_name=self.name,
                                          id_perms=ID_PERMS)
            self._vnc_vm.set_uuid(self.uuid)
            self._vnc_vm.annotations = self.vnc_vm.annotations or KeyValuePairs()
            self._vnc_vm.annotations.add_key_value_pair(
                KeyValuePair('vrouter-uuid', self.vrouter_uuid)
            )
        return self._vnc_vm


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, vnc_vn, vlan_id_pool):
        self.vmware_vn = vmware_vn
        self.key = vmware_vn.key
        self.dvs = vmware_vn.config.distributedVirtualSwitch
        self.dvs_name = vmware_vn.config.distributedVirtualSwitch.name
        self.default_port_config = vmware_vn.config.defaultPortConfig
        self.vnc_vn = vnc_vn
        self.vlan_id = None
        self.vlan_id_pool = vlan_id_pool
        self._sync_vlan_ids()

    @property
    def name(self):
        return self.vnc_vn.name

    @property
    def uuid(self):
        return str(self.vnc_vn.uuid)

    @staticmethod
    def get_fq_name(name):
        return [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, name]

    @staticmethod
    def get_uuid(key):
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, key))

    def subnet_info_is_set(self):
        return self.vnc_vn.get_network_ipam_refs()

    def _sync_vlan_ids(self):
        criteria = vim.dvs.PortCriteria()
        criteria.portgroupKey = self.key
        criteria.inside = True

        vlans = [port.config.setting.vlan for port in self.dvs.FetchDVPorts(criteria)]

        for vlan in vlans:
            try:
                self.vlan_id_pool.reserve(vlan.vlanId)
            except TypeError:
                pass


class VirtualMachineInterfaceModel(object):
    def __init__(self, vm_model, vn_model, parent, security_group):
        self.parent = parent
        self.vm_model = vm_model
        self.vn_model = vn_model
        self.mac_address = find_vm_mac_address(self.vm_model.vmware_vm, self.vn_model.key)
        self.port_key = find_vmi_port_key(self.vm_model.vmware_vm, self.mac_address)
        self.ip_address = None
        self.port_key = None
        self.vlan_id = None
        self.security_group = security_group
        self.vnc_vmi = None
        self.vnc_instance_ip = None
        self.vrouter_port_added = False

    @property
    def uuid(self):
        return self.get_uuid(self.mac_address)

    @property
    def display_name(self):
        return 'vmi-{}-{}'.format(self.vn_model.name, self.vm_model.name)

    def refresh_port_key(self):
        self.port_key = find_vmi_port_key(self.vm_model.vmware_vm, self.mac_address)

    def to_vnc(self):
        if not self.vnc_vmi:
            self.vnc_vmi = VirtualMachineInterface(name=self.uuid,
                                                   display_name=self.display_name,
                                                   parent_obj=self.parent,
                                                   id_perms=ID_PERMS)
            self.vnc_vmi.set_uuid(self.uuid)
            self.vnc_vmi.add_virtual_machine(self.vm_model.vnc_vm)
            self.vnc_vmi.set_virtual_network(self.vn_model.vnc_vn)
            self.vnc_vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.mac_address]))
            self.vnc_vmi.set_port_security_enabled(True)
            self.vnc_vmi.set_security_group(self.security_group)
            self.vnc_vmi.annotations = self.vnc_vmi.annotations or KeyValuePairs()
            self.vnc_vmi.annotations.add_key_value_pair(
                KeyValuePair('vrouter-uuid', self.vm_model.vrouter_uuid)
            )
        return self.vnc_vmi

    def construct_instance_ip(self):
        if not self._should_construct_instance_ip():
            return

        logger.info('Constructing Instance IP for %s', self.display_name)

        instance_ip_name = 'ip-' + self.vn_model.name + '-' + self.vm_model.name
        instance_ip_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, instance_ip_name.encode('utf-8')))

        instance_ip = InstanceIp(
            name=instance_ip_uuid,
            display_name=instance_ip_name,
            id_perms=ID_PERMS,
        )

        # if self.ip_address:
        #    instance_ip.set_instance_ip_address(self.ip_address)
        # TODO: Check if setting this to None works (remove if statement)
        instance_ip.set_uuid(instance_ip_uuid)
        instance_ip.set_virtual_network(self.vn_model.vnc_vn)
        instance_ip.set_virtual_machine_interface(self.to_vnc())
        instance_ip.annotations = instance_ip.annotations or KeyValuePairs()
        instance_ip.annotations.add_key_value_pair(
            KeyValuePair('vrouter-uuid', self.vm_model.vrouter_uuid)
        )
        self.vnc_instance_ip = instance_ip

    def acquire_vlan_id(self):
        self.vlan_id = self.vlan_id or self.vn_model.vlan_id_pool.get_available()

    def clear_vlan_id(self):
        self.vn_model.vlan_id_pool.free(self.vlan_id)
        self.vlan_id = None

    def _find_ip_address(self):
        if self.vn_model.vnc_vn.get_external_ipam() and self.vm_model.tools_running:
            return find_virtual_machine_ip_address(self.vm_model.vmware_vm, self.vn_model.name)
        return None

    def _should_construct_instance_ip(self):
        return (self.mac_address
                and self.vn_model.subnet_info_is_set()
                and (self.ip_address
                     or not self.vn_model.vnc_vn.get_external_ipam()))

    @staticmethod
    def get_uuid(mac_address):
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, mac_address.encode('utf-8')))


class VlanIdPool(object):
    def __init__(self, start, end):
        self._available_ids = deque(range(start, end + 1))

    def reserve(self, vlan_id):
        try:
            self._available_ids.remove(vlan_id)
        except ValueError:
            pass

    def get_available(self):
        try:
            return self._available_ids.popleft()
        except IndexError:
            return None

    def free(self, vlan_id):
        self._available_ids.append(vlan_id)
