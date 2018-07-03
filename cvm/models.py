import logging
import uuid
from collections import deque

from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import (IdPermsType, InstanceIp, KeyValuePair,
                             KeyValuePairs, MacAddressesType, VirtualMachine,
                             VirtualMachineInterface)

from cvm.constants import (CONTRAIL_VM_NAME, VNC_ROOT_DOMAIN,
                           VNC_VCENTER_PROJECT)

logger = logging.getLogger(__name__)

ID_PERMS = IdPermsType(creator='vcenter-manager',
                       enable=True)


def find_vrouter_uuid(host):
    try:
        for vmware_vm in host.vm:
            if vmware_vm.name.startswith(CONTRAIL_VM_NAME):
                return vmware_vm.config.instanceUuid
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
        self.ports = self._read_ports()
        self.vmi_models = self._construct_interfaces()
        self._vnc_vm = None

    def update(self, vmware_vm, vm_properties):
        self.vmware_vm = vmware_vm  # TODO: Consider removing this
        self.vm_properties = vm_properties
        self.vrouter_uuid = find_vrouter_uuid(vmware_vm.summary.runtime.host)
        self.ports = self._read_ports()

    def rename(self, name):
        self.vm_properties['name'] = name

    def update_ports(self):
        self.ports = self._read_ports()

    def update_vmis(self):
        self.vmi_models = self._construct_interfaces()

    def _read_ports(self):
        try:
            return [VCenterPort(device)
                    for device in self.vmware_vm.config.hardware.device
                    if isinstance(device.backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)]
        except AttributeError:
            logger.error('Could not read ports for %s.', self.name)
        return None

    def _construct_interfaces(self):
        return [VirtualMachineInterfaceModel(self, None, port)
                for port in self.ports]

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
                                          display_name=self.name,
                                          id_perms=ID_PERMS)
            self._vnc_vm.set_uuid(self.uuid)
            self._vnc_vm.annotations = self.vnc_vm.annotations or KeyValuePairs()
            self._vnc_vm.annotations.add_key_value_pair(
                KeyValuePair('vrouter-uuid', self.vrouter_uuid)
            )
        return self._vnc_vm

    def __repr__(self):
        return 'VirtualMachineModel(uuid=%s, name=%s, vrouter_uuid=%s, vm_properties=%s, interfaces=%s)' % \
               (self.uuid, self.name, self.vrouter_uuid, self.vm_properties,
                [vmi_model.uuid for vmi_model in self.vmi_models])


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, vnc_vn):
        self.vmware_vn = vmware_vn
        self.key = vmware_vn.key
        self.dvs = vmware_vn.config.distributedVirtualSwitch
        self.dvs_name = vmware_vn.config.distributedVirtualSwitch.name
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

    def __repr__(self):
        return 'VirtualNetworkModel(uuid=%s, key=%s, name=%s)' % \
               (self.uuid, self.key, self.name)


class VirtualMachineInterfaceModel(object):
    def __init__(self, vm_model, vn_model, vcenter_port):
        self.vm_model = vm_model
        self.vn_model = vn_model
        self.vcenter_port = vcenter_port
        self.ip_address = None
        self.vnc_vmi = None
        self.vnc_instance_ip = None
        self.parent = None
        self.security_group = None

    @property
    def uuid(self):
        return self.get_uuid(self.vcenter_port.mac_address)

    @property
    def display_name(self):
        if self.vn_model and self.vm_model:
            return 'vmi-{}-{}'.format(self.vn_model.name, self.vm_model.name)
        return None

    def refresh_port_key(self):
        self.vcenter_port.port_key = find_vmi_port_key(self.vm_model.vmware_vm, self.vcenter_port.mac_address)

    def to_vnc(self):
        if not self.vnc_vmi:
            self.vnc_vmi = VirtualMachineInterface(name=self.uuid,
                                                   display_name=self.display_name,
                                                   parent_obj=self.parent,
                                                   id_perms=ID_PERMS)
            self.vnc_vmi.set_uuid(self.uuid)
            self.vnc_vmi.add_virtual_machine(self.vm_model.vnc_vm)
            self.vnc_vmi.set_virtual_network(self.vn_model.vnc_vn)
            self.vnc_vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.vcenter_port.mac_address]))
            self.vnc_vmi.set_port_security_enabled(True)
            self.vnc_vmi.set_security_group(self.security_group)
            self.vnc_vmi.annotations = self.vnc_vmi.annotations or KeyValuePairs()
            self.vnc_vmi.annotations.add_key_value_pair(
                KeyValuePair('vrouter-uuid', self.vm_model.vrouter_uuid)
            )
        return self.vnc_vmi

    def construct_instance_ip(self):
        if not self.vn_model.subnet_info_is_set():
            return

        logger.info('Constructing Instance IP for %s', self.display_name)

        instance_ip_name = 'ip-' + self.vn_model.name + '-' + self.vm_model.name
        instance_ip_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, instance_ip_name.encode('utf-8')))

        instance_ip = InstanceIp(
            name=instance_ip_uuid,
            display_name=instance_ip_name,
            id_perms=ID_PERMS,
        )

        instance_ip.set_instance_ip_address(self.ip_address)
        instance_ip.set_uuid(instance_ip_uuid)
        instance_ip.set_virtual_network(self.vn_model.vnc_vn)
        instance_ip.set_virtual_machine_interface(self.to_vnc())
        instance_ip.annotations = instance_ip.annotations or KeyValuePairs()
        instance_ip.annotations.add_key_value_pair(
            KeyValuePair('vrouter-uuid', self.vm_model.vrouter_uuid)
        )
        self.vnc_instance_ip = instance_ip

    @staticmethod
    def get_uuid(mac_address):
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, mac_address.encode('utf-8')))

    def __repr__(self):
        if self.vnc_instance_ip is not None:
            ip_address = self.vnc_instance_ip.instance_ip_address
        else:
            ip_address = 'unset'
        return 'VirtualMachineInterfaceModel(uuid=%s, display_name=%s, vcenter_port=%s, ip_address=%s)' \
               % (self.uuid, self.display_name, self.vcenter_port, ip_address)


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


class VCenterPort(object):
    def __init__(self, device):
        self.mac_address = device.macAddress
        self.port_key = device.backing.port.portKey
        self.portgroup_key = device.backing.port.portgroupKey
        self.vlan_id = None

    def __repr__(self):
        return 'VCenterPort(mac_address=%s, port_key=%s, portgroup_key=%s, vlan_id=%s)' \
               % (self.mac_address, self.port_key, self.portgroup_key, self.vlan_id)
