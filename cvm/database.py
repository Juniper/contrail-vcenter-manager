from models import *
import logging

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
            logger.info('Saved VM:' + obj.name)
        if isinstance(obj, VirtualNetworkModel):
            self.vn_models.append(obj)
        if isinstance(obj, VirtualMachineInterfaceModel):
            self.vmi_models.append(obj)

    def get_vm_model(self, name):
        for model in self.vm_models:
            if model.name == name:
                return model
        return None

    def get_vn_model(self, name):
        for model in self.vm_models:
            if model.name == name:
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
            self.delete_vmi_model(obj.vm_model, obj.vn_model)
        self.save(obj)

    def delete_vm_model(self, name):
        vm_model = self.get_vm_model(name)
        if vm_model:
            self.vm_models.remove(vm_model)

    def delete_vn_model(self, name):
        vn_model = self.get_vn_model(name)
        if vn_model:
            self.vn_models.remove(vn_model)

    def delete_vmi_model(self, vm_model, vn_model):
        vmi_model = self.get_vmi_model(vm_model, vn_model)
        if vmi_model:
            self.vmi_models.remove(vm_model)
