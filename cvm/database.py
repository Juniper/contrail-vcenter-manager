import logging

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
        return self.vm_models.values()

    def get_vm_model_by_uuid(self, uid):
        vm_model = self.vm_models.get(uid, None)
        if not vm_model:
            # TODO: Database should not log anything (?)
            logger.error('Could not find VM with uuid %s.', uid)
        return vm_model

    def get_vm_model_by_name(self, name):
        try:
            return [vm_model for vm_model in self.vm_models.values() if vm_model.name == name][0]
        except IndexError:
            logger.error('Could not find VM with name %s.', name)
            return None

    def get_vn_model_by_key(self, key):
        vn_model = self.vn_models.get(key, None)
        if not vn_model:
            # TODO: Database should not log anything (?)
            logger.error('Could not find VN with key %s.', key)
        return vn_model

    def get_vn_model_by_uuid(self, uuid):
        try:
            return [vn_model for vn_model in self.vn_models.values() if vn_model.uuid == uuid][0]
        except IndexError:
            logger.error('Could not find VN with UUID %s.', uuid)
            return None

    def get_all_vn_models(self):
        return self.vn_models.values()

    def get_all_vmi_models(self):
        return self.vmi_models.values()

    def get_vmi_model_by_uuid(self, uuid):
        return self.vmi_models.get(uuid, None)

    def get_vmi_models_by_vm_uuid(self, uuid):
        return [vmi_model for vmi_model in self.vmi_models.values() if vmi_model.vm_model.uuid == uuid]

    def get_vmi_models_by_vn_uuid(self, uuid):
        return [vmi_model for vmi_model in self.vmi_models.values() if vmi_model.vn_model.uuid == uuid]

    def delete_vm_model(self, uid):
        try:
            self.vm_models.pop(uid)
        except KeyError:
            logger.info('Could not delete VM with uuid %s.', uid)

    def delete_vn_model(self, key):
        try:
            self.vn_models.pop(key)
        except KeyError:
            logger.info('Could not find VN with key %s. Nothing to delete.', key)

    def delete_vmi_model(self, uuid):
        try:
            self.vmi_models.pop(uuid)
        except KeyError:
            logger.info('Could not find VMI with uuid %s. Nothing to delete.', uuid)

    def print_out(self):
        print self.vm_models
        print self.vn_models
        print self.vmi_models
