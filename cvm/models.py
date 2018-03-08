import logging
import uuid
import ipaddress
from vnc_api.vnc_api import VirtualMachine, IdPermsType, VirtualMachineInterface, MacAddressesType, VirtualNetwork
from pyVmomi import vim  # pylint: disable=no-name-in-module

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
    def __init__(self, vmware_vm):
        self.vmware_vm = vmware_vm
        self.uuid = vmware_vm.config.instanceUuid
        self.name = vmware_vm.name
        self.power_state = vmware_vm.runtime.powerState
        self.tools_running_status = vmware_vm.guest.toolsRunningStatus
        self.vrouter_ip_address = find_vrouter_ip_address(vmware_vm.summary.runtime.host)
        self.networks = []

    @classmethod
    def from_event(cls, event):
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


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, parent):
        self.vmware_vn = vmware_vn
        self.parent = parent
        self.name = self.vmware_vn.name
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vmware_vn.config.key))  # TODO: Extract method

    def to_vnc(self):
        vnc_vn = VirtualNetwork(self.name, self.parent)
        vnc_vn.set_uuid(self.uuid)
        return vnc_vn


class VirtualMachineInterfaceModel(object):
    def __init__(self, vm_model, vn_model, parent):
        self.parent = parent
        self.vm_model = vm_model
        self.vn_model = vn_model
        self.display_name = 'vmi-{}-{}'.format(vn_model.name, vm_model.name)
        self.uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, vm_model.uuid + vn_model.uuid))
        self.mac_address = find_virtual_machine_mac_address(self.vm_model.vmware_vm, self.vn_model.vmware_vn)

    def to_vnc(self):
        vnc_vmi = VirtualMachineInterface(name=self.uuid,
                                          display_name=self.display_name,
                                          parent_obj=self.parent,
                                          id_perms=ID_PERMS)
        vnc_vmi.set_uuid(self.uuid)
        vnc_vmi.add_virtual_machine(self.vm_model.to_vnc())
        vnc_vmi.set_virtual_network(self.vn_model.to_vnc())
        vnc_vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.mac_address]))
        # vnc_vmi.setPortSecurityEnabled(vmiInfo.getPortSecurityEnabled());
        # vnc_vmi.setSecurityGroup(vCenterDefSecGrp);
        return vnc_vmi

    @classmethod
    def from_vnc(cls, vnc_vmi, vm_model, vn_model, parent):
        vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, parent)
        vmi_model.vnc_vmi = vnc_vmi
        vmi_model.display_name = vnc_vmi.get_display_name()
        vmi_model.uuid = vnc_vmi.get_uuid()
        return vmi_model
