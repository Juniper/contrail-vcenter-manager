import atexit
import logging
from uuid import uuid4

import requests
from pyVim.connect import Disconnect, SmartConnectNoSSL
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.exceptions import NoIdError, RefsExistError

from cvm.constants import (VM_PROPERTY_FILTERS, VNC_VCENTER_DEFAULT_SG,
                           VNC_VCENTER_DEFAULT_SG_FQN, VNC_VCENTER_IPAM,
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


def make_filter_spec(obj, filters):
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = make_object_set(obj)
    filter_spec.propSet = make_prop_set(obj, filters)
    return filter_spec


class ESXiAPIClient(object):
    _version = ''

    def __init__(self, esxi_cfg):
        self._si = SmartConnectNoSSL(host=esxi_cfg.get('host'),
                                     user=esxi_cfg.get('username'),
                                     pwd=esxi_cfg.get('password'),
                                     port=esxi_cfg.get('port'),
                                     preferredApiVersions=esxi_cfg.get('preferred_api_versions'))
        atexit.register(Disconnect, self._si)
        self._property_collector = self._si.content.propertyCollector
        self._wait_options = vmodl.query.PropertyCollector.WaitOptions()

    def get_all_vms(self):
        return self._si.content.rootFolder.childEntity[0].vmFolder.childEntity

    def get_all_dpgs(self):
        all_networks = self._si.content.rootFolder.childEntity[0].network
        return [net for net in all_networks if isinstance(net, vim.dvs.DistributedVirtualPortgroup)]

    def create_event_history_collector(self, events_to_observe):
        event_manager = self._si.content.eventManager
        event_filter_spec = vim.event.EventFilterSpec()
        event_types = [getattr(vim.event, et) for et in events_to_observe]
        event_filter_spec.type = event_types
        entity_spec = vim.event.EventFilterSpec.ByEntity()
        # TODO: find a way to search for this entity
        entity_spec.entity = self._si.content.rootFolder.childEntity[0]
        entity_spec.recursion = vim.event.EventFilterSpec.RecursionOption.children
        event_filter_spec.entity = entity_spec
        return event_manager.CreateCollectorForEvents(filter=event_filter_spec)

    def add_filter(self, obj, filters):
        filter_spec = make_filter_spec(obj, filters)
        return self._property_collector.CreateFilter(filter_spec, True)

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

    def read_vm_properties(self, vmware_vm):
        filter_spec = make_filter_spec(vmware_vm, VM_PROPERTY_FILTERS)
        options = vmodl.query.PropertyCollector.RetrieveOptions()
        object_set = self._property_collector.RetrievePropertiesEx([filter_spec], options=options).objects
        prop_set = object_set[0].propSet
        return {prop.name: prop.val for prop in prop_set}


class VCenterAPIClient(object):
    def __init__(self, vcenter_cfg):
        self.vcenter_cfg = vcenter_cfg
        self.si = None

    def __enter__(self):
        self.si = SmartConnectNoSSL(host=self.vcenter_cfg['host'],
                                    user=self.vcenter_cfg['username'],
                                    pwd=self.vcenter_cfg['password'],
                                    port=self.vcenter_cfg['port'],
                                    preferredApiVersions=self.vcenter_cfg['preferred_api_versions'])

    def __exit__(self, *args):
        Disconnect(self.si)

    def get_dpg_by_name(self, name):
        for dpg in self.si.content.rootFolder.childEntity[0].network:
            if dpg.name == name and isinstance(dpg, vim.dvs.DistributedVirtualPortgroup):
                return dpg
        return None

    def get_dpgs_for_vm(self, vm_model):
        for vmware_vm in self.si.content.rootFolder.childEntity[0].hostFolder.childEntity[0].host[0].vm:
            if vmware_vm.config.instanceUuid == vm_model.uuid:
                return [dpg for dpg in vmware_vm.network if isinstance(dpg, vim.dvs.DistributedVirtualPortgroup)]
        return []

    def get_ip_pool_for_dpg(self, dpg):
        dc = self.si.content.rootFolder.childEntity[0]
        return self._get_ip_pool_by_id(dpg.summary.ipPoolId, dc)

    def _get_ip_pool_by_id(self, pool_id, dc):
        for ip_pool in self.si.content.ipPoolManager.QueryIpPools(dc):
            if ip_pool.id == pool_id:
                return ip_pool
        return None


class VNCAPIClient(object):
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
        return [self.vnc_lib.virtual_machine_read(vm['fq_name']) for vm in vms]

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

    def get_vmis_by_project(self, project):
        vmis = self.vnc_lib.virtual_machine_interfaces_list(parent_id=project.uuid).get('virtual-machine-interfaces')
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

    def get_vns_by_project(self, project):
        vns = self.vnc_lib.virtual_networks_list(parent_id=project.uuid).get('virtual-networks')
        return [self.vnc_lib.virtual_network_read(vn['fq_name']) for vn in vns]

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

    @staticmethod
    def construct_ipam(project):
        return vnc_api.NetworkIpam(
            name=VNC_VCENTER_IPAM,
            parent_obj=project
        )

    def create_ipam(self, ipam):
        try:
            self.vnc_lib.network_ipam_create(ipam)
            logger.info('Network IPAM created: %s', ipam.name)
        except RefsExistError:
            logger.error('Network IPAM already exists: %s', ipam.name)

    def read_ipam(self, fq_name):
        try:
            return self.vnc_lib.network_ipam_read(fq_name)
        except NoIdError:
            logger.error('Network IPAM not found: %s', fq_name)

    def create_instance_ip(self, instance_ip):
        try:
            self.vnc_lib.instance_ip_create(instance_ip)
            logger.debug("Created instanceIP: " + instance_ip.name + ": " + instance_ip.address)
        except RefsExistError:
            logger.error('Instance IP already exists: %s', instance_ip.name)


class VRouterAPIClient(object):
    """
    A client for Contrail VRouter Agent REST API.

    Based on:
    - https://github.com/Juniper/contrail-controller/blob/master/src/vnsw/agent/port_ipc/vrouter-port-control
    - https://github.com/Juniper/contrail-vrouter-java-api/blob/master/src/net/juniper/contrail/contrail_vrouter_api/ContrailVRouterApi.java
    """

    def __init__(self, address, port):
        self.url = 'http://{0}:{1}'.format(address, port)

    def add_port(self, vmi_model):
        """ Add port to VRouter Agent. """
        payload = {
            'uuid': vmi_model.uuid,
            'name': vmi_model.uuid,
            'id': vmi_model.uuid,
            'instance-id': vmi_model.vm_model.uuid,
            'system-name': vmi_model.uuid,
            'ip-address': vmi_model.ip_address,
            'mac-address': vmi_model.mac_address,
            'vn-id': vmi_model.vn_model.uuid,
            'display-name': vmi_model.vm_model.name,
            'vm-project-id': vmi_model.parent.uuid,
            'tx-vlan-id': vmi_model.vn_model.primary_vlan_id,
            'rx-vlan-id': vmi_model.vn_model.isolated_vlan_id,
        }

        url = self.url + '/port'

        response = requests.post(url, json=payload)

        if response.status_code == requests.codes.ok:
            logger.error('Port created for interface: %s', vmi_model.uuid)
        else:
            logger.error('Port not added for interface %s, agent returned: %s', vmi_model.uuid, response.reason)

    def delete_port(self, vmi_uuid):
        """ Delete port from VRouter Agent. """
        url = self.url + '/port/{0}'.format(vmi_uuid)

        response = requests.delete(url)

        if response.status_code == requests.codes.ok:
            logger.error('Port removed for interface: %s', vmi_uuid)
        else:
            logger.error('Port not removed for interface %s, agent returned: %s', vmi_uuid, response.reason)
