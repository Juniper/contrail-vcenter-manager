from builtins import object
import logging

from cvm.constants import VMFS
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)

logger = logging.getLogger(__name__)


class Database(object):

    def __init__(self):
        self.vm_models = {}
        self.vn_models = {}
        self.vmi_models = {}
        self.vmis_to_update = []
        self.vmis_to_delete = []
        self.vlans_to_update = []
        self.vlans_to_restore = []
        self.ports_to_update = []
        self.ports_to_delete = []

    def save(self, obj):
        if isinstance(obj, VirtualMachineModel):
            self.vm_models[obj.uuid] = obj
            logger.info('Saved Virtual Machine model for %s', obj.name)
        if isinstance(obj, VirtualNetworkModel):
            self.vn_models[obj.key] = obj
            logger.info('Saved Virtual Network model for %s', obj.name)
        if isinstance(obj, VirtualMachineInterfaceModel):
            self.vmi_models[obj.uuid] = obj
            logger.info('Saved Virtual Machine Interface model for %s', obj.display_name)

    def get_all_vm_models(self):
        return list(self.vm_models.values())

    def get_vm_model_by_uuid(self, uuid):
        vm_model = self.vm_models.get(uuid, None)
        if not vm_model:
            logger.info('Could not find VM model with uuid %s.', uuid)
        return vm_model

    def get_vm_model_by_name(self, name):
        try:
            return [vm_model for vm_model in list(self.vm_models.values()) if vm_model.name == name][0]
        except IndexError:
            logger.info('Could not find VM model with name %s.', name)
            return self._get_vm_model_by_old_name(name)

    def _get_vm_model_by_old_name(self, old_name):
        # Sometimes during stress tests VmRemoved event comes with old name, despite rename
        # Renaming yVM-test-gtiltsxwws to /vmfs/volumes/23c13506-c7f8ba2b/yVM-test-gtiltsxwws/yVM-test-gtiltsxwws.vmx
        # Detected event: <class 'pyVmomi.VmomiSupport.vim.event.VmRemovedEvent'> for VM: yVM-test-gtiltsxwws
        logger.info('Looking for VM model with old name: %s', old_name)
        for vm_model in list(self.vm_models.values()):
            if VMFS in vm_model.name and '{0}/{0}'.format(old_name) in vm_model.name:
                return vm_model
        logger.info('Could not find VM model with old name %s.', old_name)
        return None

    def get_vn_model_by_key(self, key):
        vn_model = self.vn_models.get(key, None)
        if not vn_model:
            logger.info('Could not find VN model with key %s.', key)
        return vn_model

    def get_vn_model_by_uuid(self, uuid):
        try:
            return [vn_model for vn_model in list(self.vn_models.values()) if vn_model.uuid == uuid][0]
        except IndexError:
            logger.info('Could not find VN model with UUID %s.', uuid)
            return None

    def get_all_vn_models(self):
        return list(self.vn_models.values())

    def get_all_vmi_models(self):
        return list(self.vmi_models.values())

    def get_vmi_model_by_uuid(self, uuid):
        return self.vmi_models.get(uuid, None)

    def get_vmi_models_by_vm_uuid(self, uuid):
        return [vmi_model for vmi_model in list(self.vmi_models.values()) if vmi_model.vm_model.uuid == uuid]

    def get_vmi_models_by_vn_uuid(self, uuid):
        return [vmi_model for vmi_model in list(self.vmi_models.values()) if vmi_model.vn_model.uuid == uuid]

    def delete_vm_model(self, uid):
        try:
            self.vm_models.pop(uid)
        except KeyError:
            logger.info('Could not delete VM model with uuid %s.', uid)

    def delete_vn_model(self, key):
        try:
            self.vn_models.pop(key)
        except KeyError:
            logger.info('Could not find VN model with key %s. Nothing to delete.', key)

    def delete_vmi_model(self, uuid):
        try:
            self.vmi_models.pop(uuid)
        except KeyError:
            logger.info('Could not find VMI model with uuid %s. Nothing to delete.', uuid)

    def is_vlan_available(self, new_vmi_model, vlan_id):
        vmi_models = [vmi_model for vmi_model in self.get_all_vmi_models()
                      if vmi_model.vcenter_port.vlan_id == vlan_id
                      and vmi_model.uuid != new_vmi_model.uuid]
        return not bool(vmi_models)

    def clear_database(self):
        self.vm_models = {}
        self.vn_models = {}
        self.vmi_models = {}
        self.vmis_to_update = []
        self.vmis_to_delete = []
        self.vlans_to_update = []
        self.vlans_to_restore = []
        self.ports_to_update = []
        self.ports_to_delete = []
