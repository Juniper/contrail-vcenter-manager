import logging

from pyVmomi import vim

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VmwareController(object):
    def __init__(self, vmware_service, vnc_service):
        self._vmware_service = vmware_service
        self._vnc_service = vnc_service

    def initialize_database(self):
        vmware_vns = self._vmware_service.get_all_vns()
        for vmware_vn in vmware_vns:
            self._vnc_service.create_vn(vmware_vn)

        vmware_vms = self._vmware_service.get_all_vms()
        for vmware_vm in vmware_vms:
            vm_model = self._vnc_service.create_vm(vmware_vm)
            self._vnc_service.create_vmis_for_vm_model(vm_model)

        self._vnc_service.sync_vms()
        self._vnc_service.sync_vns()
        self._vnc_service.sync_vmis()

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
        logger.info('Handling event: %s', event.fullFormattedMessage)
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
        vmware_vm = event.vm.vm
        self._vnc_service.create_vm(vmware_vm)
        # self._vnc_service.create_virtual_machine_interface(vmware_vm)
        self._vmware_service.add_property_filter_for_vm(event.vm.vm, ['guest.toolsRunningStatus', 'guest.net'])

    def _handle_vm_updated_event(self, event):
        vmware_vm = event.vm.vm
        self._vnc_service.update_vm(vmware_vm)

    def _handle_vm_removed_event(self, event):
        self._vnc_service.delete_vm(event.vm.name)
