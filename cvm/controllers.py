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

    def sync(self):
        logger.info('Synchronizing CVM...')
        with self._lock:
            self._vmi_service.sync_vlan_ids()
            self._vm_service.get_vms_from_vmware()
            self._vn_service.sync_vns()
            self._vmi_service.sync_vmis()
            self._vm_service.delete_unused_vms_in_vnc()
            self._vrouter_port_service.sync_ports()
        logger.info('Synchronization complete')

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

    def _has_vm_vcenter_uuid(self, vmware_vm):
        vm_properties = self._vm_service.get_vm_vmware_properties(vmware_vm)
        if 'config.instanceUuid' not in vm_properties:
            logger.error('Virtual Machine %s has not vCenter uuid. Unable to update.', vm_properties['name'])
            return False
        return True

    def _is_vm_in_database(self, name=None, uuid=None):
        if name is not None:
            vm_model = self._vm_service.get_vm_model_by_name(name)
            if vm_model is None:
                logger.error('Virtual Machine %s does not exist in CVM database. Unable to update', name)
                return False
            return True
        if uuid is not None:
            vm_model = self._vm_service.get_vm_model_by_uuid(uuid)
            if vm_model is None:
                logger.error('Virtual Machine %s does not exist in CVM database. Unable to update', uuid)
                return False
            return True
        return False


class AbstractEventHandler(AbstractChangeHandler):
    __metaclass__ = ABCMeta
    PROPERTY_NAME = 'latestPage'

    def _handle_change(self, obj, value):
        if isinstance(value, self.EVENTS):
            logger.info('Detected event: %s', type(value))
            self._handle_event(value)
        if isinstance(value, list):
            for change in sorted(value, key=lambda e: e.key):
                self._handle_change(obj, change)

    @abstractmethod
    def _handle_event(self, event):
        pass

    def _validate_event(self, event):
        vmware_vm = event.vm.vm
        return self._has_vm_vcenter_uuid(vmware_vm)


class VmUpdatedHandler(AbstractEventHandler):
    EVENTS = (
        vim.event.VmCreatedEvent,
        vim.event.VmClonedEvent,
        vim.event.VmDeployedEvent,
        vim.event.VmMacChangedEvent,
        vim.event.VmMacAssignedEvent,
    )

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        try:
            if not self._validate_event(event):
                return
            vmware_vm = event.vm.vm
            self._vm_service.update(vmware_vm)
            self._vn_service.update_vns()
            self._vmi_service.update_vmis()
            self._vrouter_port_service.sync_ports()
        except vmodl.fault.ManagedObjectNotFound:
            logger.info('Skipping event for a non-existent VM.')


class VmRegisteredHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmRegisteredEvent,)

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        try:
            if not self._validate_event(event):
                return
            vmware_vm = event.vm.vm
            self._vm_service.update(vmware_vm)
            self._vn_service.update_vns()
            self._vmi_service.register_vmis()
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
        if not self._validate_event(event):
            return
        old_name = event.oldName
        new_name = event.newName
        self._vm_service.rename_vm(old_name, new_name)
        self._vmi_service.rename_vmis(new_name)
        self._vrouter_port_service.sync_ports()

    def _validate_event(self, event):
        old_name = event.oldName
        return self._is_vm_in_database(name=old_name)


class VmReconfiguredHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmReconfiguredEvent,)

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        if not self._validate_event(event):
            return
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
                logger.info('Detected VmReconfiguredEvent with unsupported %s device type', type(device))

    def _validate_event(self, event):
        vmware_vm = event.vm.vm
        return self._has_vm_vcenter_uuid(vmware_vm) and self._is_vm_in_database(name=vmware_vm.name)


class VmRemovedHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmRemovedEvent,)

    def __init__(self, vm_service, vmi_service, vrouter_port_service):
        self._vm_service = vm_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_event(self, event):
        if not self._validate_event(event):
            return
        vm_name = event.vm.name
        self._vmi_service.remove_vmis_for_vm_model(vm_name)
        self._vm_service.remove_vm(vm_name)
        self._vrouter_port_service.sync_ports()

    def _validate_event(self, event):
        vm_name = event.vm.name
        return self._is_vm_in_database(name=vm_name)


class GuestNetHandler(AbstractChangeHandler):
    PROPERTY_NAME = 'guest.net'

    def __init__(self, vmi_service, vrouter_port_service):
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service

    def _handle_change(self, obj, value):
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
        if not self._validate_vm(obj):
            return
        self._vm_service.update_power_state(obj, value)
        self._vrouter_port_service.sync_port_states()

    def _validate_vm(self, vmware_vm):
        return self._is_vm_in_database(name=vmware_vm.name)
