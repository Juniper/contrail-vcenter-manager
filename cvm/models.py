import ipaddress
import logging
import uuid

from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import (IdPermsType, MacAddressesType, VirtualMachine,
                             VirtualMachineInterface)

from cvm.constants import VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ID_PERMS = IdPermsType(creator='vcenter-manager',
                       enable=True)


def find_virtual_machine_ip_address(vmware_vm, port_group_name):
    net = vmware_vm.guest.net
    ipAddress = None
    virtual_machine_ip_address = None
    for nicInfo in net:
        if nicInfo.network == port_group_name:
            ipAddress = nicInfo.ipAddress
            break
    if ipAddress is not None:
        for address in ipAddress:
            ip = ipaddress.ip_address(address.decode('utf-8'))
            if isinstance(ip, ipaddress.IPv4Address):
                virtual_machine_ip_address = ip
                break
    return str(virtual_machine_ip_address)


def find_vrouter_ip_address(host):
    for vmware_vm in host.vm:
        if vmware_vm.name != 'ContrailVM':
            continue
        return find_virtual_machine_ip_address(vmware_vm, 'VM Network')  # TODO: Change this
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
        self.vnc_vn = vnc_vn
        self.ip_pool_id = vmware_vn.summary.ipPoolId
        self.subnet_address = None
        self.subnet_mask = None
        self.gateway_address = None
        self.ip_pool_enabled = None
        self.range = None
        self.external_ipam = None
        self._set_ip_pool_info(ip_pool)

    def _set_ip_pool_info(self, ip_pool):
        if ip_pool:
            ip_config_info = ip_pool.ipv4Config
            self.subnet_address = ip_config_info.subnetAddress
            self.subnet_mask = ip_config_info.netmask
            self.gateway_address = ip_config_info.gateway
            self.ip_pool_enabled = ip_config_info.ipPoolEnabled
            self.range = ip_config_info.range
            logger.info('Set ip_pool to %d for %s', self.ip_pool_id, self.key)

    #    def get_subnet(self):
    #     if not (self.subnet_address and self.subnet_mask):
    #         return None
    #     subnetUtils = SubnetUtils(self.subnet_address, self.subnet_mask)
    #     cidr = subnetUtils.getInfo().getCidrSignature()
    #     addr_pair = cidr.split("/")
    #
    #     allocation_pools = None
    #     if self.ip_pool_enabled and not self.range.isEmpty():
    #         pools = self.range.split("#")
    #         if len(pools) == 2:
    #             allocation_pools = []  # new ArrayList<AllocationPoolType>();
    #             start = (pools[0]).replace(" ", "")
    #             num = (pools[1]).replace(" ", "")
    #             start_ip = InetAddresses.coerceToInteger(InetAddresses.forString(start))
    #             end_ip = start_ip + int(num) - 1
    #             end = InetAddresses.toAddrString(InetAddresses.fromInteger(end_ip))
    #             logger.debug("Subnet IP Range :  Start:" + start + " End:" + end)
    #             pool1 = AllocationPoolType(start, end)
    #         allocation_pools.append(pool1)
    #
    #     # if gateway address is empty string, don't pass empty string to
    #     # api - server.INstead set it to null so that java binding will
    #     # drop gateway address from json content for virtual - network create
    #     if self.gateway_address:
    #         if self.gateway_address.trim().isEmpty():
    #             self.gateway_address = None
    #
    #     subnet = VnSubnetsType()
    #     subnet.add_ipam_subnets(IpamSubnetType(subnet=SubnetType(addr_pair[0], int(addr_pair[1])),
    #                                            default_gateway=self.gateway_address,
    #                                            dns_server_address=None,
    #                                            subnet_uuid=str(uuid.uuid4()),
    #                                            enable_dhcp=True,
    #                                            dns_nameservers=None,
    #                                            allocation_pools=allocation_pools,
    #                                            addr_from_start=True,
    #                                            dhcp_option_list=None,
    #                                            host_routes=None,
    #                                            subnet_name="{}-subnet".format(self.name),
    #                                            alloc_unit=1))
    #     return subnet

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


class VirtualMachineInterfaceModel(object):
    def __init__(self, vm_model, vn_model, parent, security_group):
        self.parent = parent
        self.vm_model = vm_model
        self.vn_model = vn_model
        self.display_name = 'vmi-{}-{}'.format(vn_model.name, vm_model.name)
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vm_model.uuid + vn_model.uuid))
        self.mac_address = find_virtual_machine_mac_address(self.vm_model.vmware_vm, self.vn_model.key)
        self.security_group = security_group

    def to_vnc(self):
        vnc_vmi = VirtualMachineInterface(name=self.uuid,
                                          display_name=self.display_name,
                                          parent_obj=self.parent,
                                          id_perms=ID_PERMS)
        vnc_vmi.set_uuid(self.uuid)
        vnc_vmi.add_virtual_machine(self.vm_model.to_vnc())
        vnc_vmi.set_virtual_network(self.vn_model.vnc_vn)
        vnc_vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.mac_address]))
        vnc_vmi.set_port_security_enabled(True)
        vnc_vmi.set_security_group(self.security_group)
        return vnc_vmi
