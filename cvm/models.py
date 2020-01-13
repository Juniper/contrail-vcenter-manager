from builtins import str
from builtins import range
from builtins import object
from collections import deque
import logging
import uuid

from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import (InstanceIp, MacAddressesType, VirtualMachine,
                             VirtualMachineInterface)

from cvm.constants import CONTRAIL_VM_NAME, ID_PERMS

logger = logging.getLogger(__name__)


def find_vrouter_uuid(host):
    try:
        for vmware_vm in host.vm:
            if vmware_vm.name.startswith(CONTRAIL_VM_NAME):
                return vmware_vm.config.instanceUuid
    except AttributeError:
        pass
    return None


class VirtualMachineModel(object):
    def __init__(self, vmware_vm, vm_properties):
        self.vmware_vm = vmware_vm
        self.vm_properties = vm_properties
        self.devices = vmware_vm.config.hardware.device
        host = vm_properties['summary.runtime.host']
        self.host_uuid = host.hardware.systemInfo.uuid
        self.property_filter = None
        self.ports = self._read_ports()
        self.vmi_models = self._construct_interfaces()

    def update(self, vmware_vm, vm_properties):
        self.vmware_vm = vmware_vm
        self.vm_properties = vm_properties
        self.devices = vmware_vm.config.hardware.device
        host = vm_properties['summary.runtime.host']
        self.host_uuid = host.hardware.systemInfo.uuid
        self.ports = self._read_ports()

    def rename(self, name):
        self.vm_properties['name'] = name

    def update_interfaces(self, vmware_vm):
        self.devices = vmware_vm.config.hardware.device
        self.ports = self._read_ports()
        self.vmi_models = self._construct_interfaces()

    def is_tools_running_status_changed(self, tools_running_status):
        return tools_running_status != self.vm_properties['guest.toolsRunningStatus']

    def update_tools_running_status(self, tools_running_status):
        self.vm_properties['guest.toolsRunningStatus'] = tools_running_status

    def is_power_state_changed(self, power_state):
        return power_state != self.vm_properties['runtime.powerState']

    def update_power_state(self, power_state):
        self.vm_properties['runtime.powerState'] = power_state

    def _read_ports(self):
        try:
            return [VCenterPort(device)
                    for device in self.devices
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
        vnc_vm = VirtualMachine(name=self.uuid,
                                display_name=self.name,
                                id_perms=ID_PERMS)
        vnc_vm.set_uuid(self.uuid)
        return vnc_vm

    def __repr__(self):
        return 'VirtualMachineModel(uuid=%s, name=%s, vm_properties=%s, interfaces=%s)' % \
               (self.uuid, self.name, self.vm_properties,
                [vmi_model.uuid for vmi_model in self.vmi_models])


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, vnc_vn):
        self.vmware_vn = vmware_vn
        self.key = vmware_vn.key
        self.vnc_vn = vnc_vn

    @property
    def name(self):
        return self.vnc_vn.name

    @property
    def uuid(self):
        return str(self.vnc_vn.uuid)

    @property
    def has_external_ipam(self):
        return self.vnc_vn.get_external_ipam()

    @property
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
        self._ip_address = None
        self.vnc_instance_ip = None
        self.parent = None
        self.security_group = None
        self._vnc_vmi = None

    @property
    def uuid(self):
        return self.get_uuid(self.vcenter_port.mac_address)

    @property
    def ip_address(self):
        return self._ip_address

    @property
    def display_name(self):
        if self.vn_model and self.vm_model:
            return 'vmi-{}-{}'.format(self.vn_model.name, self.vm_model.name)
        return None

    @property
    def vnc_vmi(self):
        return self._construct_new_vnc_vmi()

    @vnc_vmi.setter
    def vnc_vmi(self, vmi):
        self._vnc_vmi = vmi

    def _construct_new_vnc_vmi(self):
        vmi = VirtualMachineInterface(name=self.uuid,
                                      display_name=self.display_name,
                                      parent_obj=self.parent,
                                      id_perms=ID_PERMS)
        vmi.set_uuid(self.uuid)
        vmi.add_virtual_machine(self.vm_model.vnc_vm)
        if self.vn_model:
            vmi.set_virtual_network(self.vn_model.vnc_vn)
        vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.vcenter_port.mac_address]))
        vmi.set_port_security_enabled(True)
        vmi.set_security_group(self.security_group)
        return vmi

    def update_ip_address(self, ip_address):
        if ip_address != self._ip_address:
            self._ip_address = ip_address
            return True
        return False

    def is_ip_address_changed(self, ip_address):
        return ip_address != self._ip_address

    def construct_instance_ip(self):
        if not self._should_construct_instance_ip():
            return

        logger.info('Constructing Instance IP for Interface %s', self.display_name)

        instance_ip_name = 'ip-' + self.vn_model.name + '-' + self.vm_model.name
        instance_ip_uuid = self.construct_instance_ip_uuid(instance_ip_name)

        instance_ip = InstanceIp(
            name=instance_ip_uuid,
            display_name=instance_ip_name,
            id_perms=ID_PERMS,
        )
        instance_ip.set_uuid(instance_ip_uuid)
        instance_ip.set_virtual_network(self.vn_model.vnc_vn)
        instance_ip.set_virtual_machine_interface(self.vnc_vmi)

        if self.vn_model.vnc_vn.get_external_ipam():
            logger.info('VN %s uses external IPAM - setting IP address to: %s',
                        self.vn_model.name, self._ip_address)
            instance_ip.set_instance_ip_address(self._ip_address)

        self.vnc_instance_ip = instance_ip

    def remove_from_vm_model(self):
        self.vm_model.vmi_models.remove(self)

    def _should_construct_instance_ip(self):
        return (self.vn_model.subnet_info_is_set
                and (self.ip_address or not self.vn_model.has_external_ipam))

    @staticmethod
    def construct_instance_ip_uuid(name):
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, name))

    @staticmethod
    def get_uuid(mac_address):
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, mac_address))

    def __repr__(self):
        if self.vnc_instance_ip is not None:
            ip_address = self.vnc_instance_ip.instance_ip_address
        else:
            ip_address = 'unset'
        return 'VirtualMachineInterfaceModel(uuid=%s, display_name=%s, vcenter_port=%s, ip_address=%s)' \
               % (self.uuid, self.display_name, self.vcenter_port, ip_address)


class VlanIdPool(object):
    def __init__(self, start, end):
        self._available_ids = deque(list(range(start, end + 1)))

    def reserve(self, vlan_id):
        try:
            self._available_ids.remove(vlan_id)
            logger.info('Reserved VLAN %s', vlan_id)
        except ValueError:
            pass

    def get_available(self):
        try:
            vlan_id = self._available_ids.popleft()
            logger.info('Reserved VLAN %s', vlan_id)
            return vlan_id
        except IndexError:
            raise Exception('No viable VLAN ID')

    def free(self, vlan_id):
        if vlan_id not in self._available_ids:
            self._available_ids.append(vlan_id)
        logger.info('Freed VLAN %s', vlan_id)

    def is_available(self, vlan_id):
        return vlan_id in self._available_ids


class VCenterPort(object):
    def __init__(self, device):
        self.device = device
        self.mac_address = device.macAddress
        self.port_key = device.backing.port.portKey
        self.portgroup_key = device.backing.port.portgroupKey
        self.vlan_id = None
        self.vlan_success = False

    def __repr__(self):
        return 'VCenterPort(mac_address=%s, port_key=%s, portgroup_key=%s, vlan_id=%s, vlan_success=%s)' \
               % (self.mac_address, self.port_key, self.portgroup_key, self.vlan_id, self.vlan_success)
