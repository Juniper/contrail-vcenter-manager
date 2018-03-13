import atexit
import logging
from uuid import uuid4

from pyVim.connect import Disconnect, SmartConnectNoSSL
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.exceptions import NoIdError, RefsExistError

from cvm.constants import (VNC_VCENTER_DEFAULT_SG, VNC_VCENTER_DEFAULT_SG_FQN,
                           VNC_VCENTER_PROJECT)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def make_prop_set(obj, filters):
    prop_set = []
    property_spec = vmodl.query.PropertyCollector.PropertySpec(
        type=type(obj),
        all=False)
    property_spec.pathSet.extend(filters)
    prop_set.append(property_spec)
    return prop_set


def make_object_set(obj):
    object_set = [vmodl.query.PropertyCollector.ObjectSpec(obj=obj)]
    return object_set


class ESXiAPIClient(object):
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
        return (net for net in all_networks if isinstance(net, vim.dvs.DistributedVirtualPortgroup))

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

    def add_filter(self, obj, filters):
        filter_spec = vmodl.query.PropertyCollector.FilterSpec()
        filter_spec.objectSet = make_object_set(obj)
        filter_spec.propSet = make_prop_set(obj, filters)
        self._property_collector.CreateFilter(filter_spec, True)

    def make_wait_options(self, max_wait_seconds=None, max_object_updates=None):
        if max_object_updates is not None:
            self._wait_options.maxObjectUpdates = max_object_updates
        if max_wait_seconds is not None:
            self._wait_options.maxWaitSeconds = max_wait_seconds

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
        self.id_perms.set_creator('vcenter-manager')
        self.id_perms.set_enable(True)

    def create_vm(self, vnc_vm):
        try:
            self.vnc_lib.virtual_machine_create(vnc_vm)
            logger.info('Virtual Machine created: %s', vnc_vm.name)
        except RefsExistError:
            logger.error('Virtual Machine already exists: %s', vnc_vm.name)

    def delete_vm(self, uuid):
        try:
            self.vnc_lib.virtual_machine_delete(id=uuid)
            logger.info('Virtual Machine removed: %s', uuid)
        except NoIdError:
            logger.error('Virtual Machine not found: %s', uuid)

    def read_vm(self, uuid):
        try:
            return self.vnc_lib.virtual_machine_read(id=uuid)
        except NoIdError:
            logger.error('Virtual Machine not found: %s', uuid)
            return None

    def update_vm(self, vnc_vm):
        """ TODO: Change name - it's more of a update_or_create than update. """
        try:
            self.vnc_lib.virtual_machine_update(vnc_vm)
            logger.info('Virtual Machine updated: %s', vnc_vm.name)
        except NoIdError:
            logger.info('Virtual Machine not found - creating: %s', vnc_vm.name)
            self.create_vm(vnc_vm)

    def get_all_vms(self):
        vms = self.vnc_lib.virtual_machines_list().get('virtual-machines')
        return (self.vnc_lib.virtual_machine_read(vm['fq_name']) for vm in vms)

    def create_vmi(self, vmi):
        try:
            self.vnc_lib.virtual_machine_interface_create(vmi)
            logger.info('Virtual Machine Interface created: %s', vmi.display_name)
        except RefsExistError:
            logger.error('Virtual Machine Interface already exists: %s', vmi.display_name)

    def update_vmi(self, vmi):
        """ TODO: Change name - it's more of a update_or_create than update. """
        try:
            self.vnc_lib.virtual_machine_interface_update(vmi)
            logger.info('Virtual Machine Interface updated: %s', vmi.name)
        except NoIdError:
            logger.info('Virtual Machine Interface not found - creating: %s', vmi.name)
            self.create_vmi(vmi)

    def read_vmi(self, name, uuid):
        try:
            return self.vnc_lib.virtual_machine_interface_read([name, uuid])
        except NoIdError:
            logger.error('Virtual Machine not found: %s', name)
            return None

    def delete_vmi(self, uuid):
        try:
            self.vnc_lib.virtual_machine_interface_delete(id=uuid)
            logger.info('Virtual Machine Interface removed: %s', uuid)
        except NoIdError:
            logger.error('Virtual Machine Interface not found: %s', uuid)

    def get_all_vmis(self):
        vmis = self.vnc_lib.virtual_machine_interfaces_list(
            parent_id=self.vcenter_project.uuid
        ).get('virtual-machine-interfaces')
        return [self.vnc_lib.virtual_machine_interface_read(vmi['fq_name']) for vmi in vmis]

    def get_vmis_for_vm(self, vm_model):
        vmis = self.vnc_lib.virtual_machine_interfaces_list(
            back_ref_id=vm_model.uuid
        ).get('virtual-machine-interfaces')
        return [self.vnc_lib.virtual_machine_interface_read(vmi['fq_name']) for vmi in vmis]

    def create_vn(self, vnc_vn):
        try:
            self.vnc_lib.virtual_network_create(vnc_vn)
            logger.info('Virtual Network created: %s', vnc_vn.name)
        except RefsExistError:
            logger.error('Virtual Network already exists: %s', vnc_vn.name)

    def read_vn(self, fq_name):
        try:
            return self.vnc_lib.virtual_network_read(fq_name)
        except NoIdError:
            logger.error('Virtual Machine not found: %s', fq_name)
            return None

    def delete_vn(self, uuid):
        try:
            self.vnc_lib.virtual_network_delete(id=uuid)
            logger.info('Virtual Network removed: %s', uuid)
        except NoIdError:
            logger.error('Virtual Network not found: %s', uuid)

    def get_all_vns(self):
        vns = self.vnc_lib.virtual_networks_list(
            parent_id=self.vcenter_project.uuid).get('virtual-networks')
        return (self.vnc_lib.virtual_network_read(vn['fq_name']) for vn in vns)

    @staticmethod
    def construct_project():
        return vnc_api.Project(name=VNC_VCENTER_PROJECT)

    def create_project(self, project):
        try:
            project.set_id_perms(self.id_perms)
            self.vnc_lib.project_create(project)
            logger.info('Project created: %s', project.name)
        except RefsExistError:
            logger.error('Project already exists: %s', project.name)

    def read_project(self, fq_name):
        try:
            return self.vnc_lib.project_read(fq_name)
        except NoIdError:
            logger.error('Project not found: %s', fq_name)
            return None

    @staticmethod
    def construct_security_group(project):
        security_group = vnc_api.SecurityGroup(name=VNC_VCENTER_DEFAULT_SG,
                                               parent_obj=project)

        security_group_entry = vnc_api.PolicyEntriesType()

        ingress_rule = vnc_api.PolicyRuleType(
            rule_uuid=str(uuid4()),
            direction='>',
            protocol='any',
            src_addresses=[vnc_api.AddressType(
                security_group=VNC_VCENTER_DEFAULT_SG_FQN)],
            src_ports=[vnc_api.PortType(0, 65535)],
            dst_addresses=[vnc_api.AddressType(security_group='local')],
            dst_ports=[vnc_api.PortType(0, 65535)],
            ethertype='IPv4',
        )

        egress_rule = vnc_api.PolicyRuleType(
            rule_uuid=str(uuid4()),
            direction='>',
            protocol='any',
            src_addresses=[vnc_api.AddressType(security_group='local')],
            src_ports=[vnc_api.PortType(0, 65535)],
            dst_addresses=[vnc_api.AddressType(vnc_api.SubnetType('0.0.0.0', 0))],
            dst_ports=[vnc_api.PortType(0, 65535)],
            ethertype='IPv4',
        )

        security_group_entry.add_policy_rule(ingress_rule)
        security_group_entry.add_policy_rule(egress_rule)

        security_group.set_security_group_entries(security_group_entry)
        return security_group

    def create_security_group(self, security_group):
        try:
            self.vnc_lib.security_group_create(security_group)
            logger.info('Security group created: %s', security_group.name)
        except RefsExistError:
            logger.error('Security group already exists: %s', security_group.name)

    def read_security_group(self, fq_name):
        try:
            return self.vnc_lib.security_group_read(fq_name)
        except NoIdError:
            logger.error('Security group not found: %s', fq_name)
            return None
