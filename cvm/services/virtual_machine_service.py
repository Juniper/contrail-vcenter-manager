import logging

from vnc_api.gen.resource_xsd import PermType2

from cvm.constants import CONTRAIL_VM_NAME, VM_UPDATE_FILTERS
from cvm.models import VirtualMachineModel
from cvm.services.service import Service

logger = logging.getLogger(__name__)


class VirtualMachineService(Service):
    def __init__(self, esxi_api_client, vcenter_api_client, vnc_api_client, database):
        super(VirtualMachineService, self).__init__(vnc_api_client, database,
                                                    esxi_api_client=esxi_api_client,
                                                    vcenter_api_client=vcenter_api_client)

    def update(self, vmware_vm):
        vm_properties = self._esxi_api_client.read_vm_properties(vmware_vm)
        if is_contrail_vm_name(vm_properties['name']):
            return
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if vm_model:
            self._update(vm_model, vmware_vm, vm_properties)
            return
        self._create(vmware_vm, vm_properties)

    def _update(self, vm_model, vmware_vm, vm_properties):
        logger.info('Updating %s', vm_model)
        vm_model.update(vmware_vm, vm_properties)
        logger.info('Updated %s', vm_model)
        for vmi_model in vm_model.vmi_models:
            self._database.vmis_to_update.append(vmi_model)
        self._database.save(vm_model)

    def _create(self, vmware_vm, vm_properties):
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        self._database.vmis_to_update += vm_model.vmi_models
        self._add_property_filter_for_vm(vm_model, vmware_vm, VM_UPDATE_FILTERS)
        self._update_in_vnc(vm_model.vnc_vm)
        logger.info('Created %s', vm_model)
        self._database.save(vm_model)

    def _add_property_filter_for_vm(self, vm_model, vmware_vm, filters):
        property_filter = self._esxi_api_client.add_filter(vmware_vm, filters)
        vm_model.property_filter = property_filter

    def _update_in_vnc(self, vnc_vm):
        self._add_owner_to(vnc_vm)
        self._vnc_api_client.update_or_create_vm(vnc_vm)

    def _add_owner_to(self, vnc_vm):
        perms2 = PermType2()
        perms2.set_owner(self._project.get_uuid())
        vnc_vm.set_perms2(perms2)

    def get_vms_from_vmware(self):
        vmware_vms = self._esxi_api_client.get_all_vms()
        for vmware_vm in vmware_vms:
            self.update(vmware_vm)

    def delete_unused_vms_in_vnc(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vnc_vm in vnc_vms:
            if self._database.get_vm_model_by_uuid(vnc_vm.uuid):
                continue
            with self._vcenter_api_client:
                if self._vcenter_api_client.can_remove_vm(uuid=vnc_vm.uuid):
                    logger.info('Deleting %s from VNC', vnc_vm.name)
                    self._vnc_api_client.delete_vm(vnc_vm.uuid)

    def remove_vm(self, name):
        vm_model = self._database.get_vm_model_by_name(name)
        logger.info('Deleting %s', vm_model)
        if not vm_model:
            return
        with self._vcenter_api_client:
            if self._vcenter_api_client.can_remove_vm(name=name):
                self._vnc_api_client.delete_vm(vm_model.uuid)
            else:
                logger.info('VM %s still exists on another host and can\'t be deleted from VNC', name)
        self._database.delete_vm_model(vm_model.uuid)
        vm_model.destroy_property_filter()

    def update_vmware_tools_status(self, vmware_vm, tools_running_status):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if not vm_model:
            return
        if vm_model.is_tools_running_status_changed(tools_running_status):
            vm_model.update_tools_running_status(tools_running_status)
            logger.info('VMware tools on VM %s are %s', vm_model.name,
                        'running' if vm_model.tools_running else 'not running')
            self._database.save(vm_model)

    def rename_vm(self, old_name, new_name):
        logger.info('Renaming %s to %s', old_name, new_name)
        vm_model = self._database.get_vm_model_by_name(old_name)
        vm_model.rename(new_name)
        if self._vcenter_api_client.can_rename_vm(vm_model, new_name):
            self._update_in_vnc(vm_model.vnc_vm)
        self._database.save(vm_model)

    def update_vm_models_interfaces(self, vmware_vm):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        old_vmi_models = {vmi_model.uuid: vmi_model for vmi_model in vm_model.vmi_models}
        vm_model.update_interfaces(vmware_vm)
        new_vmi_models = {vmi_model.uuid: vmi_model for vmi_model in vm_model.vmi_models}

        for uuid, new_vmi_model in new_vmi_models.items():
            old_vmi_models.pop(uuid, None)
            self._database.vmis_to_update.append(new_vmi_model)

        self._database.vmis_to_delete += old_vmi_models.values()

    def update_power_state(self, vmware_vm, power_state):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if vm_model.is_power_state_changed(power_state):
            vm_model.update_power_state(power_state)
            logger.info('VM %s was powered %s', vm_model.name, power_state[7:].lower())
            for vmi_model in vm_model.vmi_models:
                self._database.ports_to_update.append(vmi_model)
            self._database.save(vm_model)


def is_contrail_vm_name(name):
    return CONTRAIL_VM_NAME in name
