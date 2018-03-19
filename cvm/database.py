import logging

from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Database(object):

    def __init__(self):
        self.vm_models = {}
        self.vn_models = {}
        self.vmi_models = {}

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

    def get_vm_model_by_uuid(self, uid):
        vm_model = self.vm_models.get(uid, None)
        if not vm_model:
            # TODO: Database should not log anything (?)
            logger.error('Could not find VM with uuid %s.', uid)
        return vm_model

    def get_vn_model_by_key(self, key):
        vn_model = self.vn_models.get(key, None)
        if not vn_model:
            # TODO: Database should not log anything (?)
            logger.error('Could not find VN with key %s.', key)
        return vn_model

    def get_vmi_model_by_uuid(self, uid):
        return self.vmi_models.get(uid, None)

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

    def delete_vmi_model(self, uid):
        try:
            self.vmi_models.pop(uid)
        except KeyError:
            logger.info('Could not find VMI with uuid %s. Nothing to delete.', uid)

    def print_out(self):
        print self.vm_models
        print self.vn_models
        print self.vmi_models
