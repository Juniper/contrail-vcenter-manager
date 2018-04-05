import logging

from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VmwareController(object):
    def __init__(self, vm_service, vn_service, vmi_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service

    def initialize_database(self):
        logger.info('Initializing database...')
        self._vn_service.sync_vns()
        self._vm_service.sync_vms()
        self._vmi_service.sync_vmis()

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
            elif name.startswith('guest.net'):
                self._handle_net_change(value)

    def _handle_event(self, event):
        logger.info('Handling event: %s', event.fullFormattedMessage)
        if isinstance(event, (
                vim.event.VmCreatedEvent,
                vim.event.VmPoweredOnEvent,
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

    def _handle_vm_updated_event(self, event):
        vmware_vm = event.vm.vm
        try:
            vm_model = self._vm_service.update(vmware_vm)
            self._vmi_service.update_vmis_for_vm_model(vm_model)
        except vmodl.fault.ManagedObjectNotFound:
            logger.info('Skipping event for a non-existent VM.')

    def _handle_vm_removed_event(self, event):
        vm_model = self._vm_service.remove_vm(event.vm.name)
        # TODO: self._vmi_service.remove_vmis_for_vm_model(vm_model)

    def _handle_net_change(self, nic_infos):
        logger.info('Handling NicInfo update.')
        for nic_info in nic_infos:
            self._vmi_service.update_nic(nic_info)
