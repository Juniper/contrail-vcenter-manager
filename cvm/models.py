import ipaddress
import uuid
from vnc_api.vnc_api import VirtualMachine, IdPermsType, VirtualMachineInterface, MacAddressesType, VirtualNetwork
from pyVmomi import vim


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
    # TODO: Unit test this and remove unnecessary getattrs
    portgroup_key = getattr(portgroup, 'key', None)
    config = getattr(vmware_vm, 'config', None)
    hardware = getattr(config, 'hardware', None)
    for device in getattr(hardware, 'device', []):
        if isinstance(device, vim.vm.device.VirtualEthernetCard):
            port = getattr(device.backing, 'port', None)
            if getattr(port, 'portgroupKey', None) == portgroup_key:
                return device.macAddress
    return None


class VirtualMachineModel:
    def __init__(self, vmware_vm=None):
        self.vmware_vm = vmware_vm
        if vmware_vm:
            self.uuid = vmware_vm.config.instanceUuid
            self.name = vmware_vm.name
            self.display_name = self.name
            self.power_state = vmware_vm.runtime.powerState
            self.tools_running_status = vmware_vm.guest.toolsRunningStatus
            self.vrouter_ip_address = find_vrouter_ip_address(vmware_vm.summary.runtime.host)
        self.networks = []
        self.id_perms = IdPermsType()
        self.id_perms.set_creator('vcenter-cvm')
        self.id_perms.set_enable(True)
        self.vnc_vm = None

    @classmethod
    def from_event(cls, event):
        vmware_vm = event.vm.vm
        return VirtualMachineModel(vmware_vm)

    def to_vnc_vm(self):
        if not self.vnc_vm:
            vnc_vm = VirtualMachine(self.uuid)
            vnc_vm.set_uuid(self.uuid)
            vnc_vm.set_display_name(self.vrouter_ip_address)
            vnc_vm.set_id_perms(self.id_perms)
            self.vnc_vm = vnc_vm
        return self.vnc_vm


class VirtualNetworkModel:
    def __init__(self, vmware_vn, parent):
        self.vmware_vn = vmware_vn
        self.parent = parent
        self.name = self.vmware_vn.name
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vmware_vn.config.key))
        self.vnc_vn = None

    def to_vnc_vn(self):
        if not self.vnc_vn:
            self.vnc_vn = VirtualNetwork(self.name, self.parent)
        return self.vnc_vn


class VirtualMachineInterfaceModel:
    def __init__(self, vm_model=None, vn_model=None, parent=None):
        if parent:
            self.parent = parent
        if vn_model and vm_model:
            self.vm_model = vm_model
            self.vn_model = vn_model
            self.name = 'vmi-{}-{}'.format(vn_model.name, vm_model.name)
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vm_model.uuid + vn_model.uuid))
        self.id_perms = IdPermsType()
        self.id_perms.set_creator('vcenter-cvm')
        self.id_perms.set_enable(True)
        self.vnc_vmi = None

    def to_vnc_vmi(self):
        if not self.vnc_vmi:
            vnc_vmi = VirtualMachineInterface(self.uuid, self.parent)
            vnc_vmi.display_name = self.name
            vnc_vmi.uuid = self.uuid
            # vnc_vmi.setSecurityGroup(vCenterDefSecGrp);
            # vnc_vmi.setPortSecurityEnabled(vmiInfo.getPortSecurityEnabled());
            vnc_vmi.set_virtual_network(self.vn_model.to_vnc_vn())
            vnc_vmi.add_virtual_machine(self.vm_model.to_vnc_vm())
            mac_address = find_virtual_machine_mac_address(self.vm_model.vmware_vm, self.vn_model.vmware_vn)
            macAddressesType = MacAddressesType([mac_address])
            vnc_vmi.virtual_machine_interface_mac_addresses = macAddressesType
            vnc_vmi.set_id_perms(self.id_perms)
            self.vnc_vmi = vnc_vmi
        return self.vnc_vmi

    @classmethod
    def from_vnc_vmi(cls, vnc_vmi, vm_model, vn_model, parent):
        vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, parent)
        vmi_model.vnc_vmi = vnc_vmi
        vmi_model.name = vnc_vmi.display_name
        vmi_model.uuid = vnc_vmi.uuid
        return vmi_model
