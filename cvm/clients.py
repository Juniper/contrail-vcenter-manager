import atexit
import logging

from pyVim.connect import SmartConnectNoSSL, Disconnect
from vnc_api import vnc_api
from vnc_api.exceptions import RefsExistError, NoIdError
from constants import VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT
from pyVmomi import vim, vmodl

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VmwareAPIClient(object):
    """A connector for interacting with vCenter API."""
    _version = ''

    def __init__(self, esxi_cfg):
        self.si = SmartConnectNoSSL(host=esxi_cfg['host'],
                                    user=esxi_cfg['username'],
                                    pwd=esxi_cfg['password'],
                                    port=esxi_cfg['port'],
                                    preferredApiVersions=esxi_cfg['preferred_api_versions'])
        atexit.register(Disconnect, self.si)
        self._property_collector = self.si.content.propertyCollector
        self._wait_options = vmodl.query.PropertyCollector.WaitOptions()

    def get_all_vms(self):
        return self.si.content.rootFolder.childEntity[0].vmFolder.childEntity

    def get_all_dpgs(self):
        all_networks = self.si.content.rootFolder.childEntity[0].network
        return list(filter(lambda net: isinstance(net, vim.dvs.DistributedVirtualPortgroup), all_networks))

    def create_event_history_collector(self, events_to_observe):
        event_manager = self.si.content.eventManager
        event_filter_spec = vim.event.EventFilterSpec()
        event_types = [getattr(vim.event, et) for et in events_to_observe]
        event_filter_spec.type = event_types
        entity_spec = vim.event.EventFilterSpec.ByEntity()
        # TODO: find a way to search for this entity
        entity_spec.entity = self.si.content.rootFolder.childEntity[0]
        entity_spec.recursion = vim.event.EventFilterSpec.RecursionOption.children
        event_filter_spec.entity = entity_spec
        return event_manager.CreateCollectorForEvents(filter=event_filter_spec)

    def add_filter(self, object_to_observe):
        filter_spec = vmodl.query.PropertyCollector.FilterSpec()
        filter_spec.objectSet = self.make_object_set(object_to_observe)
        filter_spec.propSet = self.make_prop_set(object_to_observe)
        self._property_collector.CreateFilter(filter_spec, True)

    def make_wait_options(self, max_wait_seconds=None, max_object_updates=None):
        if max_object_updates is not None:
            self._wait_options.maxObjectUpdates = max_object_updates
        if max_wait_seconds is not None:
            self._wait_options.maxWaitSeconds = max_wait_seconds

    def make_object_set(self, object_to_observe):
        object_set = [vmodl.query.PropertyCollector.ObjectSpec(obj=object_to_observe[0])]
        return object_set

    def make_prop_set(self, object_to_observe):
        prop_set = []
        property_spec = vmodl.query.PropertyCollector.PropertySpec(
            type=type(object_to_observe[0]),
            all=False)
        property_spec.pathSet.extend(object_to_observe[1])
        prop_set.append(property_spec)
        return prop_set

    def wait_for_updates(self):
        update_set = self._property_collector.WaitForUpdatesEx(self._version, self._wait_options)
        if update_set:
            self._version = update_set.version
        return update_set


class VNCAPIClient(object):
    """A connector for interacting with VNC API."""

    def __init__(self, vnc_cfg):
        self.vnc_lib = vnc_api.VncApi(username=vnc_cfg['username'],
                                      password=vnc_cfg['password'],
                                      tenant_name=vnc_cfg['tenant_name'],
                                      api_server_host=vnc_cfg['api_server_host'],
                                      api_server_port=vnc_cfg['api_server_port'],
                                      auth_host=vnc_cfg['auth_host'],
                                      auth_port=vnc_cfg['auth_port'])
        self.id_perms = vnc_api.IdPermsType()
        self.id_perms.set_creator('vcenter-cvm')
        self.id_perms.set_enable(True)
        project = vnc_api.Project(VNC_VCENTER_PROJECT)
        self.create_project(project)
        self.vcenter_project = self.read_project([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT])

    def create_vm(self, vm_model):
        try:
            self.vnc_lib.virtual_machine_create(vm_model.to_vnc_vm())
            logger.info('Virtual Machine created: {}'.format(vm_model.display_name))
        except RefsExistError:
            logger.info('Virtual Machine already exists: {}'.format(vm_model.display_name))

    def delete_vm(self, uuid):
        try:
            self.vnc_lib.virtual_machine_delete(id=uuid)
            logger.info('Virtual Machine removed: {}'.format(uuid))
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(uuid))

    def read_vm(self, uuid):
        try:
            return self.vnc_lib.virtual_machine_read(id=uuid)
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(uuid))
            return None

    def update_vm(self, vm_model):
        try:
            self.vnc_lib.virtual_machine_update(vm_model.to_vnc_vm())
            logger.info('Virtual Machine updated: {}'.format(vm_model.display_name))
        except NoIdError:
            self.create_vm(vm_model)
            logger.error('Virtual Machine not found: {}'.format(vm_model.uuid))

    def get_all_vms(self):
        vms = self.vnc_lib.virtual_machines_list(
            parent_id=self.vcenter_project.uuid).get('virtual-machines')
        return [self.vnc_lib.virtual_machine_read(vm['fq_name']) for vm in vms]

    def create_vmi(self, vmi):
        try:
            self.vnc_lib.virtual_machine_interface_create(vmi)
            logger.info('Virtual Machine Interface created: {}'.format(vmi.display_name))
        except RefsExistError:
            logger.info('Virtual Machine Interface already exists: {}'.format(vmi.display_name))

    def read_vmi(self, name, uuid):
        try:
            return self.vnc_lib.virtual_machine_interface_read([name, uuid])
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(name))
            return None

    def delete_vmi(self, uuid):
        try:
            self.vnc_lib.virtual_machine_interface_delete(id=uuid)
            logger.info('Virtual Machine Interface removed: {}'.format(uuid))
        except NoIdError:
            logger.error('Virtual Machine Interface not found: {}'.format(uuid))

    def get_all_vmis(self):
        vmis = self.vnc_lib.virtual_machine_interfaces_list(
            parent_id=self.vcenter_project.uuid).get('virtual-machine-interfaces')
        return [self.vnc_lib.virtual_machine_interface_read(vmi['fq_name']) for vmi in vmis]

    def create_vn(self, vn):
        try:
            self.vnc_lib.virtual_network_create(vn)
            logger.info('Virtual Network created: {}'.format(vn.name))
        except RefsExistError:
            logger.info('Virtual Network already exists: {}'.format(vn.name))
        except Exception, e:
            logger.error(e)

    def read_vn(self, fq_name):
        try:
            return self.vnc_lib.virtual_network_read(fq_name)
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(fq_name))
            return None

    def delete_vn(self, uuid):
        try:
            self.vnc_lib.virtual_network_delete(id=uuid)
            logger.info('Virtual Network removed: {}'.format(uuid))
        except NoIdError:
            logger.error('Virtual Network not found: {}'.format(uuid))

    def get_all_vns(self):
        vns = self.vnc_lib.virtual_networks_list(
            parent_id=self.vcenter_project.uuid).get('virtual-networks')
        return [self.vnc_lib.virtual_network_read(vn['fq_name']) for vn in vns]

    def create_project(self, project):
        try:
            project.set_id_perms(self.id_perms)
            self.vnc_lib.project_create(project)
            logger.info('Project created: {}'.format(project.name))
        except RefsExistError:
            logger.info('Project already exists: {}')

    def read_project(self, fq_name):
        try:
            return self.vnc_lib.project_read(fq_name)
        except NoIdError:
            logger.error('Project not found: {}')
            return None
