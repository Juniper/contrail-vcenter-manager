import abc
import logging
import ipaddress

from pyVmomi import vim, vmodl
from vnc_api.vnc_api import VirtualMachine

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
            # logger.info(vmware_vm.guest.__dict__)
            # _set_contrail_vm_active_state
            # _read_virtual_machine_interfaces

            vm = VirtualMachine(uuid)
            vm.set_uuid(uuid)
            vm.set_display_name(vrouter_ip_address)
        except vmodl.fault.ManagedObjectNotFound:
            logger.error('Virtual Machine not found: {}'.format(event.vm.name))
        logger.info('Virtual Machine configuration changed: {}'.format(event.vm.name))

    def _handle_vm_removed_event(self, event):
        self.vnc_api_client.delete_vm(event.vm.name)


class VNCEventHandler(EventHandler):
    def handle_update(self, vns):
        logger.info('Handling vns.')
        pass
