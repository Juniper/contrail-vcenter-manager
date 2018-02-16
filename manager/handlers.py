import abc
import logging

from pyVmomi import vim, vmodl
from vnc_api.vnc_api import VirtualMachine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventHandler(object):
    """Base class for all EventHandlers."""
    __metaclass__ = abc.ABCMeta

    def __init__(self, api_client):
        self.api_client = api_client

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
                    self._handle_change(property_change)

    def _handle_change(self, property_change):
        name = getattr(property_change, 'name', None)
        value = getattr(property_change, 'val', None)
        if name.startswith('latestPage') and value:
            if isinstance(value, vim.event.Event):
                self._handle_event(value)
            elif isinstance(value, list):
                for event in sorted(value, key=lambda e: e.key):
                    self._handle_event(event)

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
        vm = VirtualMachine(event.vm.name)
        try:
            vm.set_uuid(event.vm.vm.config.uuid)
            self.api_client.create_vm(vm)
        except vmodl.fault.ManagedObjectNotFound:
            logger.error('Virtual Machine not found: {}'.format(vm.name))

    def _handle_vm_updated_event(self, event):
        logger.info('Virtual Machine configuration changed: {}'.format(event.vm.name))

    def _handle_vm_removed_event(self, event):
        self.api_client.delete_vm(event.vm.name)


class VNCEventHandler(EventHandler):
    def handle_update(self, vns):
        logger.info('Handling vns.')
        pass
