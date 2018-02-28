import abc
import logging
import ipaddress
import uuid

from pyVmomi import vim, vmodl
from vnc_api.vnc_api import VirtualMachine, VirtualMachineInterface, MacAddressesType, VirtualNetwork

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_virtual_machine_ip_address(vmware_vm, port_group_name):
    net = vmware_vm.guest.net
    vrouter_ip_addresses = None
    vrouter_ip_address = None
    for nicInfo in net:
        if nicInfo.network == port_group_name:
            vrouter_ip_addresses = nicInfo.ipConfig.ipAddress
            break
    if vrouter_ip_addresses is not None:
        for address in vrouter_ip_addresses:
            ip = ipaddress.ip_address(address.ipAddress.decode('utf-8'))
            if isinstance(ip, ipaddress.IPv4Address):
                vrouter_ip_address = ip
                break
    return vrouter_ip_address


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


def read_virtual_machine_interfaces(vmware_vm):
    pass


class EventHandler(object):
    """Base class for all EventHandlers."""
    __metaclass__ = abc.ABCMeta

    def __init__(self, vnc_api_client, vcenter_api_client, vcenter_monitor):
        self.vnc_api_client = vnc_api_client
        self.vcenter_api_client = vcenter_api_client
        self.vcenter_monitor = vcenter_monitor

    @abc.abstractmethod
    def handle_update(self, changes):
        """Read the changes and take proper actions based on them.

        Must be implemented by a derived class.
        """


class VCenterEventHandler(EventHandler):
    def handle_update(self, update_set):
        logger.info('Handling ESXi update.')

        for property_filter_update in update_set.filterSet:
            for object_update in property_filter_update.objectSet:
                for property_change in object_update.changeSet:
                    self._handle_change(object_update.obj, property_change)

    def _handle_change(self, obj, property_change):
        name = getattr(property_change, 'name', None)
        value = getattr(property_change, 'val', None)
        if value:
            if name.startswith('latestPage'):
                if isinstance(value, vim.event.Event):
                    self._handle_event(value)
                elif isinstance(value, list):
                    for event in sorted(value, key=lambda e: e.key):
                        self._handle_event(event)
            elif name.startswith('guest.toolsRunningStatus'):
                print obj.name, name, value

    def _handle_event(self, event):
        logger.info('Handling event: {}'.format(event.fullFormattedMessage))
        if isinstance(event, vim.event.VmCreatedEvent):
            self._handle_vm_created_event(event)
        elif isinstance(event, (vim.event.VmPoweredOnEvent,
                                vim.event.VmClonedEvent,
                                vim.event.VmDeployedEvent,
                                vim.event.VmReconfiguredEvent,
                                vim.event.VmRenamedEvent,
                                vim.event.VmMacChangedEvent,
                                vim.event.VmMacAssignedEvent,
                                vim.event.DrsVmMigratedEvent,
                                vim.event.DrsVmPoweredOnEvent,
                                vim.event.VmMigratedEvent,
                                vim.event.VmPoweredOnEvent,
                                vim.event.VmPoweredOffEvent,
                                vim.event.VmSuspendedEvent,
                                )):
            self._handle_vm_updated_event(event)
        elif isinstance(event, vim.event.VmRemovedEvent):
            self._handle_vm_removed_event(event)

    def _handle_vm_created_event(self, event):
        try:
            vmware_datacenter = event.datacenter.datacenter
            vmware_dvs = event.dvs
            vmware_host = event.host
            vmware_vm = event.vm.vm
            self.vcenter_monitor.add_filter((vmware_vm, ['guest.toolsRunningStatus', 'guest.net']))
            display_name = vmware_vm.name
            vrouter_ip_address = find_vrouter_ip_address(event.host.host)
            uuid = vmware_vm.config.instanceUuid
            power_state = vmware_vm.runtime.powerState
            tools_running_status = vmware_vm.guest.toolsRunningStatus
            logger.info(tools_running_status)
            # _set_contrail_vm_active_state
            # _read_virtual_machine_interfaces
            # networks = vmware_vm.networks

            vm = VirtualMachine(uuid)
            vm.set_uuid(uuid)
            vm.set_display_name(vrouter_ip_address)
            # self.api_client.create_vm(vm)

            self._create_virtual_machine_interface(vmware_vm, vmware_vm.network[0])
        except vmodl.fault.ManagedObjectNotFound:
            logger.error('Virtual Machine not found: {}'.format(event.vm.name))

    def _handle_vm_updated_event(self, event):
        try:
            vmware_datacenter = event.datacenter.datacenter
            vmware_dvs = event.dvs
            vmware_host = event.host
            vmware_vm = event.vm.vm
            display_name = vmware_vm.name
            vrouter_ip_address = find_vrouter_ip_address(event.host.host)
            self.vcenter_monitor.add_filter((vmware_vm, ['guest.toolsRunningStatus', 'guest.net']))

            logger.info(vrouter_ip_address)
            uuid = vmware_vm.config.instanceUuid
            power_state = vmware_vm.runtime.powerState
            tools_running_status = vmware_vm.guest.toolsRunningStatus
            logger.info(find_virtual_machine_mac_address(vmware_vm, vmware_vm.network[0]))
            # _set_contrail_vm_active_state
            # _read_virtual_machine_interfaces
            vm = VirtualMachine(uuid)
            vm.set_uuid(uuid)
            vm.set_display_name(vrouter_ip_address)
            self._create_virtual_machine_interface(vmware_vm, vmware_vm.network[0])

        except vmodl.fault.ManagedObjectNotFound:
            logger.error('Virtual Machine not found: {}'.format(event.vm.name))
        logger.info('Virtual Machine configuration changed: {}'.format(event.vm.name))

    def _handle_vm_removed_event(self, event):
        self.vnc_api_client.delete_vm(event.vm.name)

    def _create_virtual_machine_interface(self, vmware_vm, vmware_network):

        vm_interface_name = 'vmi-{}-{}'.format(vmware_network.name, vmware_vm.name)
        id = str(uuid.uuid4())

        vm = self.vnc_api_client.read_vm(vmware_vm.name)
        if not vm:
            return

        # network = self.vnc_api_client.read_vn(vmware_network.name)
        network = self.vnc_api_client.read_vn([u'default-domain', u'demo', u'test123'])
        vm_interface = VirtualMachineInterface(id, vm)
        vm_interface.display_name = vm_interface_name
        vm_interface.uuid = id
        # vm_interface.setParent(vCenterProject)
        # vm_interface.setSecurityGroup(vCenterDefSecGrp);
        # vm_interface.setPortSecurityEnabled(vmiInfo.getPortSecurityEnabled());
        vm_interface.set_virtual_network(network)
        vm_interface.add_virtual_machine(vm)
        mac_address = find_virtual_machine_mac_address(vmware_vm, vmware_network)
        mac_addresses = MacAddressesType([mac_address])
        vm_interface.virtual_machine_interface_mac_addresses = mac_addresses
        # vm_interface.setIdPerms(vCenterIdPerms)
        self.vnc_api_client.create_vmi(vm_interface)
        vmi = self.vnc_api_client.read_vmi(vmware_vm.name, id)
        logger.info("Created " + str(vmi.fq_name))


class VNCEventHandler(EventHandler):
    def handle_update(self, vns):
        logger.info('Handling vns.')
        pass
