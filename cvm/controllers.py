import logging
from abc import ABCMeta, abstractmethod

from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VmwareController(object):
    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service, handlers):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service
        self._handlers = handlers

    def initialize_database(self):
        logger.info('Initializing database...')
        self._vm_service.get_vms_from_vmware()
        self._vn_service.update_vns()
        self._vmi_service.sync_vmis()
        self._vm_service.delete_unused_vms_in_vnc()
        self._vrouter_port_service.sync_ports()

    def handle_update(self, update_set):
        logger.info('Handling ESXi update.')
        for handler in self._handlers:
            handler.handle_update(update_set)

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
                # elif isinstance(value, list):
                #     for event in sorted(value, key=lambda e: e.key):
                #         self._handle_event(event)
            elif name.startswith('guest.toolsRunningStatus'):
                self._handle_tools_status(obj, value)
            elif name.startswith('guest.net'):
                self._handle_net_change(value)

    def _handle_event(self, event):
        logger.info('Handling event: %s', event.fullFormattedMessage)
        if isinstance(event, (
                vim.event.VmCreatedEvent,
                vim.event.VmClonedEvent,
                vim.event.VmDeployedEvent,
                vim.event.VmMacChangedEvent,
                vim.event.VmMacAssignedEvent,
                vim.event.DrsVmMigratedEvent,
                vim.event.DrsVmPoweredOnEvent,
                vim.event.VmMigratedEvent,
                vim.event.VmRegisteredEvent,
                vim.event.VmPoweredOnEvent,
                vim.event.VmPoweredOffEvent,
                vim.event.VmSuspendedEvent,
        )):
            self._handle_vm_updated_event(event)

    def _handle_vm_updated_event(self, event):
        vmware_vm = event.vm.vm
        try:
            self._vm_service.update(vmware_vm)
            self._vn_service.update_vns()
            self._vmi_service.update_vmis()
            self._vrouter_port_service.sync_ports()
        except vmodl.fault.ManagedObjectNotFound:
            logger.info('Skipping event for a non-existent VM.')

    def _handle_tools_status(self, vmware_vm, value):
        try:
            logger.info('Handling toolsRunningStatus update.')
            self._vm_service.set_tools_running_status(vmware_vm, value)
        except vmodl.fault.ManagedObjectNotFound:
            logger.info('Skipping toolsRunningStatus change for a non-existent VM.')

    def _handle_net_change(self, nic_infos):
        logger.info('Handling NicInfo update.')
        for nic_info in nic_infos:
            self._vmi_service.update_nic(nic_info)
        self._vrouter_port_service.sync_ports()


class AbstractEventHandler(object):
    __metaclass__ = ABCMeta

    def handle_update(self, update_set):
        for property_filter_update in update_set.filterSet:
            for object_update in property_filter_update.objectSet:
                for property_change in object_update.changeSet:
                    self._handle_change(property_change)

    def _handle_change(self, property_change):
        name = getattr(property_change, 'name', None)
        value = getattr(property_change, 'val', None)
        if value:
            if name.startswith('latestPage'):
                if isinstance(value, self.EVENTS):
                    self._handle_event(value)

    @abstractmethod
    def _handle_event(self, event):
        pass


class VmRenamedHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmRenamedEvent,)

    def __init__(self, vm_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        old_name = event.oldName
        new_name = event.newName
        self._vm_service.rename_vm(old_name, new_name)
        self._vmi_service.rename_vmis(new_name)
        self._vrouter_port_service.sync_ports()


class VmReconfiguredHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmReconfiguredEvent,)

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        logger.info('Detected VmReconfiguredEvent')
        vmware_vm = event.vm.vm
        for device_spec in event.configSpec.deviceChange:
            device = device_spec.device
            if isinstance(device, vim.vm.device.VirtualVmxnet3):
                logger.info('Detected VmReconfiguredEvent with %s device', type(device))
                self._vm_service.update_vm_models_interfaces(vmware_vm)
                self._vn_service.update_vns()
                self._vmi_service.update_vmis()
                self._vrouter_port_service.sync_ports()
            else:
                logger.info('Detected VmReconfiguredEvent with unsupported %s device', type(device))


class VmRemovedHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmRemovedEvent,)

    def __init__(self, vm_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        vm_name = event.vm.name
        self._vmi_service.remove_vmis_for_vm_model(vm_name)
        self._vm_service.remove_vm(vm_name)
        self._vrouter_port_service.sync_ports()
