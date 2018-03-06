from models import *
import logging
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Database:
    vm_models = []
    vn_models = []
    vmi_models = []

    def __init__(self):
        pass

    def save(self, obj):
        if isinstance(obj, VirtualMachineModel):
            self.vm_models.append(obj)
            logger.info('Saved Virtual Machine model for ' + obj.name)
        if isinstance(obj, VirtualNetworkModel):
            self.vn_models.append(obj)
            logger.info('Saved Virtual Network model for ' + obj.name)
        if isinstance(obj, VirtualMachineInterfaceModel):
            self.vmi_models.append(obj)
            logger.info('Saved Virtual Machine Interface model for ' + obj.name)

    def get_vm_model_by_name(self, name):
        for model in self.vm_models:
            if model.name == name:
                return model
        return None

    def get_vm_model_by_uuid(self, uid):
        for model in self.vm_models:
            if model.uuid == uid:
                return model
        return None

    def get_vn_model(self, name):
        for model in self.vn_models:
            if model.name == name:
                return model
        return None

    def get_vn_model_by_uuid(self, uid):
        for model in self.vn_models:
            if model.uuid == uid:
                return model
        return None

    def get_vn_model_by_key(self, key):
        for model in self.vn_models:
            if model.uuid == uuid.uuid3(uuid.NAMESPACE_DNS, key):
                return model
        return None

    def get_vmi_model_by_uuid(self, uid):
        for model in self.vmi_models:
            if model.uuid == uid:
                return model
        return None

    def get_vmi_model(self, vm_model, vn_model):
        for model in self.vmi_models:
            if model.vm_model == vm_model and model.vn_model == vn_model:
                return model
        return None

    def update(self, obj):
        if isinstance(obj, VirtualMachineModel):
            self.delete_vm_model(obj.name)
        if isinstance(obj, VirtualNetworkModel):
            self.delete_vn_model(obj.name)
        if isinstance(obj, VirtualMachineInterfaceModel):
            self.delete_vmi_model(obj.uuid)
        self.save(obj)

    def delete_vm_model(self, name):
        vm_model = self.get_vm_model_by_name(name)
        if vm_model:
            self.vm_models.remove(vm_model)

    def delete_vn_model(self, name):
        vn_model = self.get_vn_model(name)
        if vn_model:
            self.vn_models.remove(vn_model)

    def delete_vmi_model(self, uuid):
        vmi_model = self.get_vmi_model_by_uuid(uuid)
        if vmi_model:
            self.vmi_models.remove(vmi_model)

    def print_out(self):
        print self.vm_models
        print self.vn_models
        print self.vmi_models
