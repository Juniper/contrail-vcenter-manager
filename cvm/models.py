import ipaddress
import logging
import uuid

from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import (IdPermsType, InstanceIp, MacAddressesType,
                             VirtualMachine, VirtualMachineInterface)

from cvm.constants import VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT

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
            if vmware_vm.name == 'ContrailVM':
                return find_virtual_machine_ip_address(vmware_vm, 'VM Network')  # TODO: Change this
    except AttributeError:
        pass
    return None


def find_virtual_machine_mac_address(vmware_vm, portgroup_key):
    try:
        devices = vmware_vm.config.hardware.device
        for device in devices:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                try:
                    portgroupKey = device.backing.port.portgroupKey
                    if portgroupKey == portgroup_key:
                        return device.macAddress
                except AttributeError:
                    pass
    except AttributeError:
        pass
    return None


class VirtualMachineModel(object):
    def __init__(self, vmware_vm):
        self.vmware_vm = vmware_vm  # TODO: Consider removing this
        self.uuid = vmware_vm.config.instanceUuid
        self.name = vmware_vm.name
        self.power_state = vmware_vm.runtime.powerState
        self.tools_running_status = vmware_vm.guest.toolsRunningStatus
        self.vrouter_ip_address = find_vrouter_ip_address(vmware_vm.summary.runtime.host)
        self.vn_models = []

    @staticmethod
    def from_event(event):
        vmware_vm = event.vm.vm
        return VirtualMachineModel(vmware_vm)

    def set_vmware_vm(self, vmware_vm):
        self.vmware_vm = vmware_vm  # TODO: Consider removing this
        self.uuid = vmware_vm.config.instanceUuid
        self.name = vmware_vm.name
        self.power_state = vmware_vm.runtime.powerState
        self.tools_running_status = vmware_vm.guest.toolsRunningStatus
        self.vrouter_ip_address = find_vrouter_ip_address(vmware_vm.summary.runtime.host)

    def to_vnc(self):
        """
        Gets fresh instance of vnc_api.VirtualMachine for this model.

        Since vnc_api.VirtualMachine is only a DTO, it can be created each time we need to use it.
        """
        vnc_vm = VirtualMachine(name=self.uuid,
                                display_name=self.vrouter_ip_address,
                                id_perms=ID_PERMS)
        vnc_vm.set_uuid(self.uuid)
        return vnc_vm

    def get_distributed_portgroups(self):
        return [dpg for dpg in self.vmware_vm.network if isinstance(dpg, vim.dvs.DistributedVirtualPortgroup)]

    def construct_vmi_models(self, parent, security_group):
        return [VirtualMachineInterfaceModel(self, vn_model, parent, security_group) for vn_model in self.vn_models]


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, vnc_vn, ip_pool):
        self.vmware_vn = vmware_vn
        self.key = vmware_vn.key
        self.dvs = vmware_vn.config.distributedVirtualSwitch
        self.default_port_config = vmware_vn.config.defaultPortConfig
        self.vendor_specific_config = vmware_vn.config.vendorSpecificConfig
        self.vnc_vn = vnc_vn
        self.primary_vlan_id = None
        self.isolated_vlan_id = None
        self.ip_pool_info = self._construct_ip_pool_info(
            ip_pool_id=vmware_vn.summary.ipPoolId,
            name=vmware_vn.summary.ipPoolName,
            ip_pool=ip_pool
        )
        self._populate_vlans()

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

    @staticmethod
    def _construct_ip_pool_info(ip_pool_id, name, ip_pool):
        if not ip_pool:
            return None
        return IpPoolInfo(ip_pool_id, name, ip_pool)

    def _populate_vlans(self):

        pvlan_map = self.dvs.config.pvlanConfig
        if not pvlan_map:
            logger.error('Cannot populate vlan, private vlan not configured on dvSwitch: %s', self.dvs.name)
            return

        try:
            self._extract_data_from_vlan_spec(pvlan_map)
        except AttributeError:
            logger.error('Cannot populate vlan, invalid port setting: %s', self.default_port_config)

    def _extract_data_from_vlan_spec(self, pvlan_map):
        vlan_spec = self.default_port_config.vlan
        if isinstance(vlan_spec, vim.dvs.VmwareDistributedVirtualSwitch.PvlanSpec):
            self._find_primary_vlan_for_isolated(pvlan_map, vlan_spec)
        elif isinstance(vlan_spec, vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec):
            self._set_regular_vlan(vlan_spec)
        else:
            logger.error('Cannot populate vlan, invalid vlan spec: %s', type(vlan_spec))

    def _set_regular_vlan(self, vlan_spec):
        self.primary_vlan_id = self.isolated_vlan_id = vlan_spec.vlanId
        logger.info('VlanType = VLAN VlanId = %d', self.primary_vlan_id)

    def _find_primary_vlan_for_isolated(self, pvlan_map, vlan_spec):
        self.isolated_vlan_id = vlan_spec.pvlanId
        try:
            matching_entry = [e for e in [isolated for isolated in pvlan_map if isolated.pvlanType == 'isolated']
                              if e.secondaryVlanId == self.isolated_vlan_id][0]
            self.primary_vlan_id = matching_entry.primaryVlanId
            logger.info('VlanType = PrivateVLAN PrimaryVLAN = %d IsolatedVLAN = %d',
                        self.primary_vlan_id,
                        self.isolated_vlan_id)
        except IndexError:
            logger.error('Cannot populate vlan, could not find primary vlan for isolated vlan: %d',
                         self.isolated_vlan_id)

    def ip_pool_info_not_set(self):
        try:
            return not self.ip_pool_info.subnet_address or not self.ip_pool_info.subnet_mask
        except AttributeError:
            return False


class VirtualMachineInterfaceModel(object):
    def __init__(self, vm_model, vn_model, parent, security_group):
        self.parent = parent
        self.vm_model = vm_model
        self.vn_model = vn_model
        self.display_name = 'vmi-{}-{}'.format(vn_model.name, vm_model.name)
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vm_model.uuid + vn_model.uuid))
        self.mac_address = find_virtual_machine_mac_address(self.vm_model.vmware_vm, self.vn_model.key)
        self.security_group = security_group
        self.vnc_vmi = None
        self.vnc_instance_ip = self._construct_instance_ip()

    def to_vnc(self):
        if not self.vnc_vmi:
            self.vnc_vmi = VirtualMachineInterface(name=self.uuid,
                                                   display_name=self.display_name,
                                                   parent_obj=self.parent,
                                                   id_perms=ID_PERMS)
            self.vnc_vmi.set_uuid(self.uuid)
            self.vnc_vmi.add_virtual_machine(self.vm_model.to_vnc())
            self.vnc_vmi.set_virtual_network(self.vn_model.vnc_vn)
            self.vnc_vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.mac_address]))
            self.vnc_vmi.set_port_security_enabled(True)
            self.vnc_vmi.set_security_group(self.security_group)
        return self.vnc_vmi

    def _construct_instance_ip(self):
        if self.vn_model.ip_pool_info_not_set():
            return None

        instance_ip_name = "ip-" + self.vn_model.name + "-" + self.vm_model.name
        instance_ip_uuid = str(uuid.uuid4())

        instance_ip = InstanceIp(
            name=instance_ip_uuid,
            display_name=instance_ip_name,
            id_perms=ID_PERMS,
        )
        if self.ip_address:
            instance_ip.set_address(self.ip_address)
            # if not self.vn_model.external_ipam:
            #     logger.error("Internal error address already set for DHCP")
        instance_ip.set_uuid(instance_ip_uuid)
        instance_ip.set_virtual_network(self.vn_model.vnc_vn)
        instance_ip.set_virtual_machine_interface(self.to_vnc())
        return instance_ip

    @property
    def ip_address(self):
        return find_virtual_machine_ip_address(self.vm_model.vmware_vm, self.vn_model.vmware_vn)


class IpPoolInfo(object):
    def __init__(self, ip_pool_id, name, ip_pool):
        self.ip_pool_id = ip_pool_id
        self.ip_pool_name = name
        ip_config_info = ip_pool.ipv4Config
        self.subnet_address = ip_config_info.subnetAddress
        self.subnet_mask = ip_config_info.netmask
        self.gateway_address = ip_config_info.gateway
        self.ip_pool_enabled = ip_config_info.ipPoolEnabled
        self.range = ip_config_info.range
