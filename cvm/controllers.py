import logging
from abc import ABCMeta, abstractmethod

from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module

logger = logging.getLogger(__name__)


class VmwareController(object):
    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service, update_handler, lock):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service
        self._update_handler = update_handler
        self._lock = lock

    def initialize_database(self):
        logger.info('Initializing database...')
        with self._lock:
            self._vmi_service.sync_vlan_ids()
            self._vm_service.get_vms_from_vmware()
            self._vn_service.update_vns()
            self._vmi_service.sync_vmis()
            self._vm_service.delete_unused_vms_in_vnc()
            self._vrouter_port_service.sync_ports()

    def handle_update(self, update_set):
        with self._lock:
            self._update_handler.handle_update(update_set)


class UpdateHandler(object):
    def __init__(self, handlers):
        self._handlers = handlers

    def handle_update(self, update_set):
        for property_filter_update in update_set.filterSet:
            for object_update in property_filter_update.objectSet:
                for property_change in object_update.changeSet:
                    for handler in self._handlers:
                        handler.handle_change(object_update.obj, property_change)


class AbstractChangeHandler(object):
    __metaclass__ = ABCMeta

    def handle_change(self, obj, property_change):
        name = getattr(property_change, 'name', None)
        value = getattr(property_change, 'val', None)
        if value:
            if name.startswith(self.PROPERTY_NAME):
                self._handle_change(obj, value)

    @abstractmethod
    def _handle_change(self, obj, value):
        pass


class AbstractEventHandler(AbstractChangeHandler):
    __metaclass__ = ABCMeta
    PROPERTY_NAME = 'latestPage'

    def _handle_change(self, obj, value):
        if isinstance(value, self.EVENTS):
            self._handle_event(value)

    @abstractmethod
    def _handle_event(self, event):
        pass


class VmUpdatedHandler(AbstractEventHandler):
    EVENTS = (
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
    )

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        vmware_vm = event.vm.vm
        try:
            self._vm_service.update(vmware_vm)
            self._vn_service.update_vns()
            self._vmi_service.update_vmis()
            self._vrouter_port_service.sync_ports()
        except vmodl.fault.ManagedObjectNotFound:
            logger.info('Skipping event for a non-existent VM.')


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
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
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


class GuestNetHandler(AbstractChangeHandler):
    PROPERTY_NAME = 'guest.net'

    def __init__(self, vmi_service, vrouter_port_service):
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_change(self, obj, value):
        logger.info('Handling NicInfo update.')
        for nic_info in value:
            self._vmi_service.update_nic(nic_info)
        self._vrouter_port_service.sync_ports()


class VmwareToolsStatusHandler(AbstractChangeHandler):
    PROPERTY_NAME = 'guest.toolsRunningStatus'

    def __init__(self, vm_service):
        self._vm_service = vm_service

    def _handle_change(self, obj, value):
        try:
            self._vm_service.update_vmware_tools_status(obj, value)
        except vmodl.fault.ManagedObjectNotFound:
            pass


class PowerStateHandler(AbstractChangeHandler):
    PROPERTY_NAME = 'runtime.powerState'

    def __init__(self, vm_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_change(self, obj, value):
        self._vm_service.update_power_state(obj, value)
        self._vrouter_port_service.sync_ports()
