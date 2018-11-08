from collections import defaultdict

import gevent

import logging

from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)
from cvm.utils import synchronized

from threading import current_thread

logger = logging.getLogger(__name__)


class Database(object):

    def __init__(self):
        self._lock = gevent.lock.RLock()
        self.vm_models = {}
        self.vn_models = {}
        self.vmi_models = {}
        self._vmis_to_update = defaultdict(list)
        self._vmis_to_delete = defaultdict(list)
        self._vlans_to_update = defaultdict(list)
        self._vlans_to_restore = defaultdict(list)
        self._ports_to_update = defaultdict(list)
        self._ports_to_delete = defaultdict(list)

    @property
    @synchronized
    def vmis_to_update(self):
        greenlet_id = current_thread().ident
        return self._vmis_to_update[greenlet_id]

    @property
    @synchronized
    def vmis_to_delete(self):
        greenlet_id = current_thread().ident
        return self._vmis_to_delete[greenlet_id]

    @property
    @synchronized
    def vlans_to_update(self):
        greenlet_id = current_thread().ident
        return self._vlans_to_update[greenlet_id]

    @property
    @synchronized
    def vlans_to_restore(self):
        greenlet_id = current_thread().ident
        return self._vlans_to_restore[greenlet_id]

    @property
    @synchronized
    def ports_to_update(self):
        greenlet_id = current_thread().ident
        return self._ports_to_update[greenlet_id]

    @property
    @synchronized
    def ports_to_delete(self):
        greenlet_id = current_thread().ident
        return self._ports_to_delete[greenlet_id]

    @synchronized
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

    @synchronized
    def get_all_vm_models(self):
        return self.vm_models.values()

    @synchronized
    def get_vm_model_by_uuid(self, uuid):
        vm_model = self.vm_models.get(uuid, None)
        if not vm_model:
            logger.info('Could not find VM model with uuid %s.', uuid)
        return vm_model

    @synchronized
    def get_vm_model_by_name(self, name):
        try:
            return [vm_model for vm_model in self.vm_models.values() if vm_model.name == name][0]
        except IndexError:
            logger.info('Could not find VM model with name %s.', name)
            return None

    @synchronized
    def get_vn_model_by_key(self, key):
        vn_model = self.vn_models.get(key, None)
        if not vn_model:
            logger.info('Could not find VN model with key %s.', key)
        return vn_model

    @synchronized
    def get_vn_model_by_uuid(self, uuid):
        try:
            return [vn_model for vn_model in self.vn_models.values() if vn_model.uuid == uuid][0]
        except IndexError:
            logger.info('Could not find VN model with UUID %s.', uuid)
            return None

    @synchronized
    def get_all_vn_models(self):
        return self.vn_models.values()

    @synchronized
    def get_all_vmi_models(self):
        return self.vmi_models.values()

    @synchronized
    def get_vmi_model_by_uuid(self, uuid):
        return self.vmi_models.get(uuid, None)

    @synchronized
    def get_vmi_models_by_vm_uuid(self, uuid):
        return [vmi_model for vmi_model in self.vmi_models.values() if vmi_model.vm_model.uuid == uuid]

    @synchronized
    def get_vmi_models_by_vn_uuid(self, uuid):
        return [vmi_model for vmi_model in self.vmi_models.values() if vmi_model.vn_model.uuid == uuid]

    @synchronized
    def delete_vm_model(self, uid):
        try:
            self.vm_models.pop(uid)
        except KeyError:
            logger.info('Could not delete VM model with uuid %s.', uid)

    @synchronized
    def delete_vn_model(self, key):
        try:
            self.vn_models.pop(key)
        except KeyError:
            logger.info('Could not find VN model with key %s. Nothing to delete.', key)

    @synchronized
    def delete_vmi_model(self, uuid):
        try:
            self.vmi_models.pop(uuid)
        except KeyError:
            logger.info('Could not find VMI model with uuid %s. Nothing to delete.', uuid)

    @synchronized
    def is_vlan_available(self, new_vmi_model, vlan_id):
        vmi_models = [vmi_model for vmi_model in self.get_all_vmi_models()
                      if vmi_model.vcenter_port.vlan_id == vlan_id
                      and vmi_model.uuid != new_vmi_model.uuid]
        return not bool(vmi_models)

    def clear_database(self):
        self.vm_models = {}
        self.vn_models = {}
        self.vmi_models = {}
        self._vmis_to_update = defaultdict(list)
        self._vmis_to_delete = defaultdict(list)
        self._vlans_to_update = defaultdict(list)
        self._vlans_to_restore = defaultdict(list)
        self._ports_to_update = defaultdict(list)
        self._ports_to_delete = defaultdict(list)
