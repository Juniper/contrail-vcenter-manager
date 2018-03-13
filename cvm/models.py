import ipaddress
import logging
import uuid

from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import (IdPermsType, MacAddressesType, VirtualMachine,
                             VirtualMachineInterface, VirtualNetwork)

from constants import VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT

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
                try:
                    portgroupKey = device.backing.port.portgroupKey
                    if portgroupKey == portgroup.key:
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

    def construct_vmi_models(self, parent):
        return [VirtualMachineInterfaceModel(self, vn_model, parent) for vn_model in self.vn_models]


class VirtualNetworkModel(object):
    def __init__(self, vmware_vn, vnc_vn):
        self.vmware_vn = vmware_vn
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
        vnc_vmi.set_virtual_network(self.vn_model.vnc_vn)
        vnc_vmi.set_virtual_machine_interface_mac_addresses(MacAddressesType([self.mac_address]))
        vnc_vmi.set_port_security_enabled(True)
        # vnc_vmi.setSecurityGroup(vCenterDefSecGrp);
        return vnc_vmi

    @staticmethod
    def from_vnc(vnc_vmi, vm_model, vn_model, parent):
        vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, parent)
        vmi_model.vnc_vmi = vnc_vmi
        vmi_model.display_name = vnc_vmi.get_display_name()
        vmi_model.uuid = vnc_vmi.get_uuid()
        return vmi_model
