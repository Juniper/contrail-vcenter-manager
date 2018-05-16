import ipaddress
import logging
import uuid

from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import (IdPermsType, InstanceIp, MacAddressesType,
                             VirtualMachine, VirtualMachineInterface)

from cvm.constants import (CONTRAIL_NETWORK, CONTRAIL_VM_NAME, VNC_ROOT_DOMAIN,
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


def find_vrouter_ip_address(host):
    try:
        for vmware_vm in host.vm:
            if vmware_vm.name.startswith(CONTRAIL_VM_NAME):
                return find_virtual_machine_ip_address(vmware_vm, CONTRAIL_NETWORK)
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


class VirtualMachineModel(object):
    def __init__(self, vmware_vm, vm_properties):
        self.vmware_vm = vmware_vm  # TODO: Consider removing this
        self.vm_properties = vm_properties
        self.vrouter_ip_address = find_vrouter_ip_address(vmware_vm.summary.runtime.host)
        self.property_filter = None
        self.interfaces = self._read_interfaces()
        self._vnc_vm = None

    def update(self, vmware_vm, vm_properties):
        self.vmware_vm = vmware_vm  # TODO: Consider removing this
        self.vm_properties = vm_properties
        self.vrouter_ip_address = find_vrouter_ip_address(vmware_vm.summary.runtime.host)
        self.interfaces = self._read_interfaces()

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
    def is_powered_on(self):
        return self.vm_properties.get('runtime.powerState') == 'poweredOn'

    @property
    def tools_running(self):
        return self.vm_properties.get('guest.toolsRunningStatus') == 'guestToolsRunning'

    @property
    def vnc_vm(self):
        if not self._vnc_vm:
            self._vnc_vm = VirtualMachine(name=self.uuid,
                                          display_name=self.vrouter_ip_address,
                                          id_perms=ID_PERMS)
            self._vnc_vm.set_uuid(self.uuid)
        return self._vnc_vm


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, vnc_vn):
        self.vmware_vn = vmware_vn
        self.key = vmware_vn.key
        self.dvs = vmware_vn.config.distributedVirtualSwitch
        self.default_port_config = vmware_vn.config.defaultPortConfig
        self.vnc_vn = vnc_vn

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


class VirtualMachineInterfaceModel(object):
    def __init__(self, vm_model, vn_model, parent, security_group):
        self.parent = parent
        self.vm_model = vm_model
        self.vn_model = vn_model
        self.mac_address = find_vm_mac_address(self.vm_model.vmware_vm, self.vn_model.key)
        self.ip_address = self._find_ip_address()
        self.security_group = security_group
        self.vnc_vmi = None
        self.vnc_instance_ip = self._construct_instance_ip()
        self.vrouter_port_added = False

    @property
    def uuid(self):
        return self.get_uuid(self.mac_address)

    @property
    def display_name(self):
        return 'vmi-{}-{}'.format(self.vn_model.name, self.vm_model.name)

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
        return self.vnc_vmi

    def _find_ip_address(self):
        if self.vn_model.vnc_vn.get_external_ipam() and self.vm_model.tools_running:
            return find_virtual_machine_ip_address(self.vm_model.vmware_vm, self.vn_model.name)
        return None

    def _construct_instance_ip(self):
        if not self._should_construct_instance_ip():
            return None

        logger.info('Constructing Instance IP for %s', self.display_name)

        instance_ip_name = 'ip-' + self.vn_model.name + '-' + self.vm_model.name
        instance_ip_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, instance_ip_name.encode('utf-8')))

        instance_ip = InstanceIp(
            name=instance_ip_uuid,
            display_name=instance_ip_name,
            id_perms=ID_PERMS,
        )

        if self.ip_address:
            instance_ip.set_instance_ip_address(self.ip_address)
            # TODO: Check if setting this to None works (remove if statement)
        instance_ip.set_uuid(instance_ip_uuid)
        instance_ip.set_virtual_network(self.vn_model.vnc_vn)
        instance_ip.set_virtual_machine_interface(self.to_vnc())
        return instance_ip

    def _should_construct_instance_ip(self):
        return (self.mac_address
                and self.vn_model.subnet_info_is_set()
                and (self.ip_address
                     or not self.vn_model.vnc_vn.get_external_ipam()))

    @staticmethod
    def get_uuid(mac_address):
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, mac_address.encode('utf-8')))
