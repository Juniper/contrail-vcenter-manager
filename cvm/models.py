import logging
import uuid
import ipaddress
from vnc_api.vnc_api import VirtualMachine, IdPermsType, VirtualMachineInterface, MacAddressesType, VirtualNetwork
from pyVmomi import vim  # pylint: disable=no-name-in-module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


def find_virtual_machine_mac_address(vmware_vm, portgroup):
    try:
        devices = vmware_vm.config.hardware.device
        for device in devices:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                portgroupKey = device.backing.port.portgroupKey
                if portgroupKey == portgroup.key:
                    return device.macAddress
    except AttributeError:
        pass
    return None


class VirtualMachineModel(object):
    def __init__(self, vmware_vm=None):
        self.vmware_vm = vmware_vm
        if vmware_vm:
            self.uuid = vmware_vm.config.instanceUuid
            self.name = vmware_vm.name
            self.power_state = vmware_vm.runtime.powerState
            self.tools_running_status = vmware_vm.guest.toolsRunningStatus
            self.vrouter_ip_address = find_vrouter_ip_address(vmware_vm.summary.runtime.host)
        self.networks = []
        self.id_perms = IdPermsType()
        self.id_perms.set_creator('vcenter-manager')
        self.id_perms.set_enable(True)

    @classmethod
    def from_event(cls, event):
        vmware_vm = event.vm.vm
        return VirtualMachineModel(vmware_vm)

    def to_vnc_vm(self):
        """
        Gets fresh instance of vnc_api.VirtualMachine for this model.

        Since vnc_api.VirtualMachine is only a DTO, it can be created each time we need to use it.
        """
        vnc_vm = VirtualMachine(name=self.uuid)
        vnc_vm.set_uuid(self.uuid)
        vnc_vm.set_display_name(self.vrouter_ip_address)
        vnc_vm.set_id_perms(self.id_perms)
        return vnc_vm


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, parent):
        self.vmware_vn = vmware_vn
        self.parent = parent
        self.name = self.vmware_vn.name
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vmware_vn.config.key))
        self.vnc_vn = None

    def to_vnc_vn(self):
        if not self.vnc_vn:
            vnc_vn = VirtualNetwork(self.name, self.parent)
            vnc_vn.set_uuid(self.uuid)
            self.vnc_vn = vnc_vn
        return self.vnc_vn

    # Can't implement this, because ipPools are inavailable from ESXi level (must be connected to vCenter machine)
    # def getSubnet(self):
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


class VirtualMachineInterfaceModel(object):
    def __init__(self, vm_model=None, vn_model=None, parent=None):
        if parent:
            self.parent = parent
        if vn_model and vm_model:
            self.vm_model = vm_model
            self.vn_model = vn_model
            self.name = 'vmi-{}-{}'.format(vn_model.name, vm_model.name)
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vm_model.uuid + vn_model.uuid))
        self.mac_address = find_virtual_machine_mac_address(self.vm_model.vmware_vm, self.vn_model.vmware_vn)
        self.id_perms = IdPermsType()
        self.id_perms.set_creator('vcenter-manager')
        self.id_perms.set_enable(True)
        self.vnc_vmi = None

    def to_vnc_vmi(self):
        if not self.vnc_vmi:
            vnc_vmi = VirtualMachineInterface(self.uuid, self.parent)
            vnc_vmi.set_display_name(self.name)
            vnc_vmi.set_uuid(self.uuid)
            vnc_vmi.add_virtual_machine(self.vm_model.to_vnc_vm())
            vnc_vmi.set_virtual_network(self.vn_model.to_vnc_vn())
            vnc_vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.mac_address]))
            vnc_vmi.set_id_perms(self.id_perms)
            # vnc_vmi.setPortSecurityEnabled(vmiInfo.getPortSecurityEnabled());
            # vnc_vmi.setSecurityGroup(vCenterDefSecGrp);
            self.vnc_vmi = vnc_vmi
        return self.vnc_vmi

    @classmethod
    def from_vnc_vmi(cls, vnc_vmi, vm_model, vn_model, parent):
        vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, parent)
        vmi_model.vnc_vmi = vnc_vmi
        vmi_model.name = vnc_vmi.get_display_name()
        vmi_model.uuid = vnc_vmi.get_uuid()
        return vmi_model
