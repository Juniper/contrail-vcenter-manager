import logging
import time
from abc import ABCMeta, abstractmethod

from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module

logger = logging.getLogger(__name__)


class VmwareController(object):
    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service,
                 vlan_id_service, update_handler, lock):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service
        self._vlan_id_service = vlan_id_service
        self._update_handler = update_handler
        self._lock = lock

    def sync(self):
        logger.info('Synchronizing CVM...')
        with self._lock:
            self._vm_service.get_vms_from_vmware()
            self._vn_service.sync_vns()
            self._vmi_service.sync_vmis()
            self._vm_service.delete_unused_vms_in_vnc()
            self._vlan_id_service.sync_vlan_ids()
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
                try:
                    self._handle_change(obj, value)
                except vmodl.fault.ManagedObjectNotFound:
                    self._log_managed_object_not_found(value)

    @abstractmethod
    def _log_managed_object_not_found(self, value):
        pass

    @abstractmethod
    def _handle_change(self, obj, value):
        pass

    @classmethod
    def _has_vm_vcenter_uuid(cls, vmware_vm):
        try:
            has_uuid = vmware_vm.config.instanceUuid is not None
        except Exception:
            has_uuid = False
        if not has_uuid:
            logger.error('VM: %s has not vCenter uuid.', vmware_vm.name)
        return has_uuid

    @classmethod
    def _is_vm_template(cls, vmware_vm):
        is_template = vmware_vm.config.template
        if is_template:
            logger.info('VM: %s is a template.', vmware_vm.name)
        return is_template

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
            logger.info('Detected event: %s for VM: %s', type(value), value.vm.name)
            try:
                self._handle_event(value)
            except vmodl.fault.ManagedObjectNotFound:
                self._log_managed_object_not_found(value)
        if isinstance(value, list):
            for change in sorted(value, key=lambda e: e.key):
                self._handle_change(obj, change)

    @abstractmethod
    def _handle_event(self, event):
        pass

    def _log_managed_object_not_found(self, event):
        logger.error('VM: %s was deleted/moved from ESXi during %s handling',
                     event.vm.name, type(event))

    def _validate_event(self, event):
        vmware_vm = event.vm.vm
        return self._has_vm_vcenter_uuid(vmware_vm) and not self._is_vm_template(vmware_vm)


class VmUpdatedHandler(AbstractEventHandler):
    EVENTS = (
        vim.event.VmCreatedEvent,
        vim.event.VmClonedEvent,
        vim.event.VmDeployedEvent,
        vim.event.VmMacChangedEvent,
        vim.event.VmMacAssignedEvent,
    )

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service, vlan_id_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service
        self._vlan_id_service = vlan_id_service

    def _handle_event(self, event):
        if not self._validate_event(event):
            return
        vmware_vm = event.vm.vm
        self._vm_service.update(vmware_vm)
        self._vn_service.update_vns()
        self._vmi_service.update_vmis()
        self._vlan_id_service.update_vlan_ids()
        self._vrouter_port_service.sync_ports()


class VmRegisteredHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmRegisteredEvent,)

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service, vlan_id_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service
        self._vlan_id_service = vlan_id_service

    def _handle_event(self, event):
        if not self._validate_event(event):
            return
        vmware_vm = event.vm.vm
        self._vm_service.update(vmware_vm)
        self._vn_service.update_vns()
        self._vmi_service.register_vmis()
        self._vlan_id_service.update_vlan_ids()
        self._vrouter_port_service.sync_ports()


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

    def __init__(self, vm_service, vn_service, vmi_service, vrouter_port_service, vlan_id_service):
        self._vm_service = vm_service
        self._vn_service = vn_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service
        self._vlan_id_service = vlan_id_service

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
                self._vlan_id_service.update_vlan_ids()
                self._vrouter_port_service.sync_ports()
            else:
                logger.info('Detected VmReconfiguredEvent with unsupported %s device type', type(device))

    def _validate_event(self, event):
        vmware_vm = event.vm.vm
        return all((
            not self._is_vm_template(vmware_vm),
            self._has_vm_vcenter_uuid(vmware_vm),
            self._is_vm_in_database(name=vmware_vm.name)
        ))


class VmRemovedHandler(AbstractEventHandler):
    EVENTS = (vim.event.VmRemovedEvent,)

    def __init__(self, vm_service, vmi_service, vrouter_port_service, vlan_id_service):
        self._vm_service = vm_service
        self._vmi_service = vmi_service
        self._vrouter_port_service = vrouter_port_service
        self._vlan_id_service = vlan_id_service

    def _handle_event(self, event):
        if not self._validate_event(event):
            return
        # wait for VM removed from vCenter (in vMotion case it is not needed,
        # but cannot distinguish these situations basing on event)
        time.sleep(5)
        vm_name = event.vm.name
        self._vmi_service.remove_vmis_for_vm_model(vm_name)
        self._vlan_id_service.update_vlan_ids()
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

    def _log_managed_object_not_found(self, value):
        logger.error('One VM was deleted/moved from ESXi during its GuestNetHandling handling')


class VmwareToolsStatusHandler(AbstractChangeHandler):
    PROPERTY_NAME = 'guest.toolsRunningStatus'

    def __init__(self, vm_service):
        self._vm_service = vm_service

    def _handle_change(self, obj, value):
        if not self._validate_vm(obj):
            return
        self._vm_service.update_vmware_tools_status(obj, value)

    def _validate_vm(self, vmware_vm):
        return self._has_vm_vcenter_uuid(vmware_vm)

    def _log_managed_object_not_found(self, value):
        logger.error('One VM was deleted/moved from ESXi during its VmwareTools update handling')


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

    def _log_managed_object_not_found(self, value):
        logger.error('One VM was deleted/moved from ESXi during its PowerState update handling')
