import atexit
import datetime
import json
import logging
import random
import os
from uuid import uuid4

import requests
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from pyVim.connect import Disconnect, SmartConnectNoSSL
from pyVim.task import WaitForTask
from vnc_api import vnc_api
from vnc_api.exceptions import NoIdError, RefsExistError

from cvm.constants import (VM_PROPERTY_FILTERS, VNC_ROOT_DOMAIN,
                           VNC_VCENTER_DEFAULT_SG, VNC_VCENTER_DEFAULT_SG_FQN,
                           VNC_VCENTER_IPAM, VNC_VCENTER_IPAM_FQN,
                           VNC_VCENTER_PROJECT)
from cvm.models import find_vrouter_uuid

logger = logging.getLogger(__name__)


class VSphereAPIClient(object):
    def __init__(self):
        self._si = None
        self._datacenter = None

    def _get_object(self, vimtype, name):
        content = self._si.content
        container = content.viewManager.CreateContainerView(content.rootFolder, vimtype, True)
        try:
            return [obj for obj in container.view if obj.name == name][0]
        except IndexError:
            return None

    def _get_vm_by_uuid(self, uuid):
        content = self._si.content
        container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        try:
            return [vm for vm in container.view if vm.config.instanceUuid == uuid][0]
        except Exception:
            return None


class ESXiAPIClient(VSphereAPIClient):
    _version = ''

    def __init__(self, esxi_cfg):
        super(ESXiAPIClient, self).__init__()
        self._si = SmartConnectNoSSL(
            host=esxi_cfg.get('host'),
            user=esxi_cfg.get('username'),
            pwd=esxi_cfg.get('password'),
            port=esxi_cfg.get('port'),
            preferredApiVersions=esxi_cfg.get('preferred_api_versions')
        )
        self._datacenter = self._si.content.rootFolder.childEntity[0]
        atexit.register(Disconnect, self._si)
        self._property_collector = self._si.content.propertyCollector
        self._wait_options = vmodl.query.PropertyCollector.WaitOptions()

    def get_all_vms(self):
        return self._datacenter.vmFolder.childEntity

    def create_event_history_collector(self, events_to_observe):
        event_manager = self._si.content.eventManager
        event_filter_spec = vim.event.EventFilterSpec()
        event_types = [getattr(vim.event, et) for et in events_to_observe]
        event_filter_spec.type = event_types
        entity_spec = vim.event.EventFilterSpec.ByEntity()
        entity_spec.entity = self._datacenter
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
        properties = {prop.name: prop.val for prop in prop_set}
        logger.info('Read from ESXi API %s properties: %s', vmware_vm.name, properties)
        return properties

    def read_vrouter_uuid(self):
        host = self._datacenter.hostFolder.childEntity[0].host[0]
        return find_vrouter_uuid(host)


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


class VCenterAPIClient(VSphereAPIClient):
    def __init__(self, vcenter_cfg):
        super(VCenterAPIClient, self).__init__()
        self._vcenter_cfg = vcenter_cfg
        self._dvs = None

    def __enter__(self):
        self._si = SmartConnectNoSSL(
            host=self._vcenter_cfg.get('host'),
            user=self._vcenter_cfg.get('username'),
            pwd=self._vcenter_cfg.get('password'),
            port=self._vcenter_cfg.get('port'),
            preferredApiVersions=self._vcenter_cfg.get('preferred_api_versions')
        )
        self._datacenter = self._get_datacenter(self._vcenter_cfg.get('datacenter'))
        self._dvs = self._get_dvswitch(self._vcenter_cfg.get('dvswitch'))

    def __exit__(self, *args):
        Disconnect(self._si)

    def get_dpg_by_key(self, key):
        for dpg in self._datacenter.network:
            if isinstance(dpg, vim.dvs.DistributedVirtualPortgroup) and dpg.key == key:
                return dpg
        return None

    def get_dpg_by_name(self, name):
        for dpg in self._datacenter.network:
            if isinstance(dpg, vim.dvs.DistributedVirtualPortgroup) and dpg.name == name:
                return dpg
        return None

    def set_vlan_id(self, vcenter_port):
        dv_port = self._fetch_port_from_dvs(vcenter_port.port_key)
        if not dv_port:
            return
        logger.info('Setting vCenter VLAN ID of port %s to %d', vcenter_port.port_key, vcenter_port.vlan_id)
        dv_port_spec = make_dv_port_spec(dv_port, vcenter_port.vlan_id)
        task = self._dvs.ReconfigureDVPort_Task(port=[dv_port_spec])
        success_message = 'Successfully set VLAN ID: %d for port: %s' % (vcenter_port.vlan_id, vcenter_port.port_key)
        fault_message = 'Failed to set VLAN ID: %d for port: %s' % (vcenter_port.vlan_id, vcenter_port.port_key)
        wait_for_task(task, success_message, fault_message)

    def get_vlan_id(self, vcenter_port):
        logger.info('Reading VLAN ID of port %s', vcenter_port.port_key)
        dv_port = self._fetch_port_from_dvs(vcenter_port.port_key)
        if not dv_port.config.setting.vlan.inherited:
            vlan_id = dv_port.config.setting.vlan.vlanId
            logger.info('Port: %s VLAN ID: %s', vcenter_port.port_key, vlan_id)
            return vlan_id
        logger.info('Port: %s has no VLAN ID', vcenter_port.port_key)
        return None

    def restore_vlan_id(self, vcenter_port):
        logger.info('Restoring VLAN ID of port %s to inherited value', vcenter_port.port_key)
        dv_port = self._fetch_port_from_dvs(vcenter_port.port_key)
        dv_port_config_spec = make_dv_port_spec(dv_port)
        task = self._dvs.ReconfigureDVPort_Task(port=[dv_port_config_spec])
        success_message = 'Successfully restored VLAN ID for port: %s' % (vcenter_port.port_key,)
        fault_message = 'Failed to restore VLAN ID for port: %s' % (vcenter_port.port_key,)
        wait_for_task(task, success_message, fault_message)

    def get_reserved_vlan_ids(self, vrouter_uuid):
        """In this method treats vrouter_uuid as esxi host id"""
        criteria = vim.dvs.PortCriteria()
        criteria.connected = True
        logger.info('Retrieving reserved VLAN IDs')
        reserved_vland_ids = []
        for port in self._dvs.FetchDVPorts(criteria=criteria):
            if not isinstance(port.config.setting.vlan, vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec):
                continue
            if find_vrouter_uuid(port.proxyHost) != vrouter_uuid:
                continue
            reserved_vland_ids.append(port.config.setting.vlan.vlanId)
        reserved_vland_ids.extend(self._get_private_vlan_ids())
        return reserved_vland_ids

    def _get_private_vlan_ids(self):
        for pvlan_entry in self._dvs.config.pvlanConfig:
            yield pvlan_entry.primaryVlanId
            if pvlan_entry.secondaryVlanId is not None:
                yield pvlan_entry.secondaryVlanId

    def _get_datacenter(self, name):
        return self._get_object([vim.Datacenter], name)

    def _get_dvswitch(self, name):
        return self._get_object([vim.dvs.VmwareDistributedVirtualSwitch], name)

    def _fetch_port_from_dvs(self, port_key):
        criteria = vim.dvs.PortCriteria()
        criteria.portKey = port_key
        try:
            return next(port for port in self._dvs.FetchDVPorts(criteria))
        except StopIteration:
            return None

    @staticmethod
    def enable_vlan_override(portgroup):
        if portgroup.config.policy.vlanOverrideAllowed:
            logger.info('VLAN Override for portgroup %s already allowed.', portgroup.name)
            return
        pg_config_spec = make_pg_config_vlan_override(portgroup)
        task = portgroup.ReconfigureDVPortgroup_Task(pg_config_spec)
        success_message = 'Enabled vCenter portgroup %s vlan override' % portgroup.name
        fault_message = 'Enabling VLAN override on portgroup {} failed: %s'.format(portgroup.name)
        wait_for_task(task, success_message, fault_message)

    def can_remove_vm(self, uuid):
        return not self._get_vm_by_uuid(uuid)

    def can_rename_vm(self, vm_model, new_name):
        vmware_vm = self._get_object([vim.VirtualMachine], new_name)
        return vmware_vm and (vmware_vm.summary.runtime.host.name == vm_model.host_name)

    def can_remove_vmi(self, vnc_vmi):
        vm_uuid = get_vm_uuid_for_vmi(vnc_vmi)
        return self.can_remove_vm(uuid=vm_uuid)

    def can_rename_vmi(self, vmi_model, new_name):
        return self.can_rename_vm(vmi_model.vm_model, new_name)


def make_dv_port_spec(dv_port, vlan_id=None):
    dv_port_config_spec = vim.dvs.DistributedVirtualPort.ConfigSpec()
    dv_port_config_spec.key = dv_port.key
    dv_port_config_spec.operation = 'edit'
    dv_port_config_spec.configVersion = dv_port.config.configVersion
    vlan_spec = vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec()
    if vlan_id:
        vlan_spec.vlanId = vlan_id
    else:
        vlan_spec.inherited = True
    dv_port_setting = vim.dvs.VmwareDistributedVirtualSwitch.VmwarePortConfigPolicy()
    dv_port_setting.vlan = vlan_spec
    dv_port_config_spec.setting = dv_port_setting
    return dv_port_config_spec


def make_pg_config_vlan_override(portgroup):
    pg_config_spec = vim.dvs.DistributedVirtualPortgroup.ConfigSpec()
    pg_config_spec.configVersion = portgroup.config.configVersion
    pg_config_spec.name = portgroup.config.name
    pg_config_spec.numPorts = portgroup.config.numPorts
    pg_config_spec.defaultPortConfig = portgroup.config.defaultPortConfig
    pg_config_spec.type = portgroup.config.type
    pg_config_spec.policy = portgroup.config.policy
    pg_config_spec.policy.vlanOverrideAllowed = True
    pg_config_spec.autoExpand = portgroup.config.autoExpand
    pg_config_spec.vmVnicNetworkResourcePoolKey = portgroup.config.vmVnicNetworkResourcePoolKey
    pg_config_spec.description = portgroup.config.description
    return pg_config_spec


def wait_for_task(task, success_message, fault_message):
    state = WaitForTask(task)
    if state == 'success':
        logger.info(success_message)
    else:
        logger.error(fault_message, task.info.error.msg)


def get_vm_uuid_for_vmi(vnc_vmi):
    refs = vnc_vmi.get_virtual_machine_refs() or []
    if refs:
        return refs[0]['uuid']
    return None


class VNCAPIClient(object):
    def __init__(self, vnc_cfg):
        vnc_cfg['api_server_host'] = vnc_cfg['api_server_host'].split(',')
        random.shuffle(vnc_cfg['api_server_host'])
        vnc_cfg['auth_host'] = vnc_cfg['auth_host'].split(',')
        random.shuffle(vnc_cfg['auth_host'])
        self.vnc_lib = vnc_api.VncApi(
            username=vnc_cfg.get('username'),
            password=vnc_cfg.get('password'),
            tenant_name=vnc_cfg.get('tenant_name'),
            api_server_host=vnc_cfg.get('api_server_host'),
            api_server_port=vnc_cfg.get('api_server_port'),
            auth_host=vnc_cfg.get('auth_host'),
            auth_port=vnc_cfg.get('auth_port')
        )
        self.id_perms = vnc_api.IdPermsType()
        self.id_perms.set_creator('vcenter-manager')
        self.id_perms.set_enable(True)

    def delete_vm(self, uuid):
        logger.info('Attempting to delete Virtual Machine %s from VNC...', uuid)
        vm = self.read_vm(uuid)
        for vmi_ref in vm.get_virtual_machine_interface_back_refs() or []:
            self.delete_vmi(vmi_ref.get('uuid'))
        try:
            self.vnc_lib.virtual_machine_delete(id=uuid)
            logger.info('Virtual Machine %s removed from VNC', uuid)
        except NoIdError:
            logger.error('Virtual Machine %s not found in VNC. Unable to delete', uuid)

    def update_vm(self, vnc_vm):
        try:
            logger.info('Attempting to update Virtual Machine %s in VNC', vnc_vm.name)
            self._update_vm(vnc_vm)
        except NoIdError:
            logger.info('Virtual Machine %s not found in VNC - creating', vnc_vm.name)
            self._create_vm(vnc_vm)

    def _update_vm(self, vnc_vm):
        self.vnc_lib.virtual_machine_update(vnc_vm)
        logger.info('Virtual Machine %s updated in VNC', vnc_vm.name)

    def _create_vm(self, vnc_vm):
        self.vnc_lib.virtual_machine_create(vnc_vm)
        logger.info('Virtual Machine %s created in VNC', vnc_vm.name)

    def get_all_vms(self):
        vms = self.vnc_lib.virtual_machines_list().get('virtual-machines')
        return [self.read_vm(vm['uuid']) for vm in vms]

    def read_vm(self, uuid):
        return self.vnc_lib.virtual_machine_read(id=uuid)

    def update_vmi(self, vnc_vmi):
        logger.info('Attempting to update Virtual Machine Interface %s in VNC', vnc_vmi.name)
        try:
            old_vmi = self.vnc_lib.virtual_machine_interface_read(id=vnc_vmi.uuid)
            self._update_vmi_vn(old_vmi, vnc_vmi)
            self._rename_vmi(old_vmi, vnc_vmi)
            self.vnc_lib.virtual_machine_interface_update(old_vmi)
        except NoIdError:
            logger.info('Virtual Machine Interface %s not found in VNC - creating', vnc_vmi.name)
            self.create_vmi(vnc_vmi)
        return self.vnc_lib.virtual_machine_interface_read(id=vnc_vmi.uuid)

    def _update_vmi_vn(self, old_vmi, new_vmi):
        new_vn_fq_name = self._get_vn_fq_name_for_vmi(new_vmi)
        old_vn_fq_name = self._get_vn_fq_name_for_vmi(old_vmi)
        if new_vn_fq_name == old_vn_fq_name:
            logger.info('No network change detected.')
            return

        logger.info('Network change detected. Updating Interface %s info in VNC.', new_vmi.name)

        self._delete_instance_ip_of(old_vmi)
        logger.info('Updating Virtual Network of Interface %s to %s', new_vmi.name, new_vn_fq_name[2])
        vnc_vn = self.read_vn(new_vn_fq_name)
        old_vmi.set_virtual_network(vnc_vn)

    def _delete_instance_ip_of(self, vnc_vmi):
        logger.info('Deleting old Instance IP for Interface %s', vnc_vmi.name)
        instance_ip_fq_name = self._get_ip_fq_name_for_vmi(vnc_vmi)
        self.vnc_lib.instance_ip_delete(instance_ip_fq_name)

    @staticmethod
    def _rename_vmi(old_vmi, new_vmi):
        old_vmi.set_display_name(new_vmi.display_name)

    def create_vmi(self, vnc_vmi):
        try:
            self.vnc_lib.virtual_machine_interface_create(vnc_vmi)
            logger.info('Virtual Machine Interface %s created in VNC', vnc_vmi.name)
        except RefsExistError:
            logger.info('Virtual Machine Interface %s already exists in VNC', vnc_vmi.name)

    def delete_vmi(self, uuid):
        vmi = self.read_vmi(uuid)
        if not vmi:
            logger.error('Virtual Machine Interface %s not found in VNC. Unable to delete', uuid)
            return

        self._detach_floating_ips(vmi)

        for instance_ip_ref in vmi.get_instance_ip_back_refs() or []:
            self._detach_service_instances_from_instance_ip(instance_ip_ref['uuid'])
            self.delete_instance_ip(instance_ip_ref.get('uuid'))

        self.vnc_lib.virtual_machine_interface_delete(id=uuid)
        logger.info('Virtual Machine Interface %s removed from VNC', uuid)

    def get_vmis_by_project(self, project):
        vmis = self.vnc_lib.virtual_machine_interfaces_list(parent_id=project.uuid).get('virtual-machine-interfaces')
        return [self.vnc_lib.virtual_machine_interface_read(vmi['fq_name']) for vmi in vmis]

    def read_vmi(self, uuid):
        try:
            return self.vnc_lib.virtual_machine_interface_read(id=uuid)
        except NoIdError:
            logger.error('Could not find VMI %s in VNC', uuid)
        return None

    def get_vns_by_project(self, project):
        vns = self.vnc_lib.virtual_networks_list(parent_id=project.uuid).get('virtual-networks')
        return [self.vnc_lib.virtual_network_read(vn['fq_name']) for vn in vns]

    @staticmethod
    def _get_vn_fq_name_for_vmi(vnc_vmi):
        if vnc_vmi.get_virtual_network_refs():
            return vnc_vmi.get_virtual_network_refs()[0]['to']
        return None

    @staticmethod
    def _get_ip_fq_name_for_vmi(vnc_vmi):
        if vnc_vmi.get_instance_ip_back_refs():
            return vnc_vmi.get_instance_ip_back_refs()[0]['to']
        return None

    def read_vn(self, fq_name):
        try:
            return self.vnc_lib.virtual_network_read(fq_name)
        except NoIdError:
            logger.error('VN %s not found in VNC', fq_name[2])
        return None

    def read_or_create_project(self):
        try:
            return self._read_project()
        except NoIdError:
            logger.warn('Project not found: %s, creating...', VNC_VCENTER_PROJECT)
            return self._create_project()

    def _create_project(self):
        project = construct_project()
        project.set_id_perms(self.id_perms)
        self.vnc_lib.project_create(project)
        logger.info('Project created: %s', project.name)
        return project

    def _read_project(self):
        fq_name = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT]
        return self.vnc_lib.project_read(fq_name)

    def read_or_create_security_group(self):
        try:
            return self._read_security_group()
        except NoIdError:
            logger.warn('Security group not found: %s, creating...', VNC_VCENTER_DEFAULT_SG_FQN)
            return self._create_security_group()

    def _read_security_group(self):
        return self.vnc_lib.security_group_read(VNC_VCENTER_DEFAULT_SG_FQN)

    def _create_security_group(self):
        project = self._read_project()
        security_group = construct_security_group(project)
        self.vnc_lib.security_group_create(security_group)
        logger.info('Security group created: %s', security_group.name)
        return security_group

    def read_or_create_ipam(self):
        try:
            return self._read_ipam()
        except NoIdError:
            logger.warn('Ipam not found: %s, creating...', VNC_VCENTER_IPAM_FQN)
            return self._create_ipam()

    def _read_ipam(self):
        return self.vnc_lib.network_ipam_read(VNC_VCENTER_IPAM_FQN)

    def _create_ipam(self):
        project = self._read_project()
        ipam = construct_ipam(project)
        self.vnc_lib.network_ipam_create(ipam)
        logger.info('Network IPAM created: %s', ipam.name)
        return ipam

    def create_and_read_instance_ip(self, vmi_model):
        instance_ip = self._read_instance_ip(vmi_model)
        if instance_ip:
            return instance_ip
        try:
            instance_ip = vmi_model.vnc_instance_ip
            self.vnc_lib.instance_ip_create(instance_ip)
            logger.info("Created Instance IP: %s with IP: %s", instance_ip.name, instance_ip.instance_ip_address)
            return self._read_instance_ip(vmi_model)
        except Exception, e:
            logger.error("Unable to create Instance IP: %s due to: %s", instance_ip.name, e)

    def delete_instance_ip(self, uuid):
        try:
            self.vnc_lib.instance_ip_delete(id=uuid)
        except NoIdError:
            logger.error('Instance IP not found: %s', uuid)

    def _read_instance_ip(self, vmi_model):
        vmi_vnc = self.read_vmi(vmi_model.uuid)
        ip_back_refs = vmi_vnc.get_instance_ip_back_refs()
        if not ip_back_refs:
            return None
        ip_uuid = ip_back_refs[0]['uuid']
        try:
            return self.vnc_lib.instance_ip_read(id=ip_uuid)
        except NoIdError:
            return None

    def _detach_floating_ips(self, vmi):
        fip_refs = vmi.get_floating_ip_back_refs()
        if fip_refs is None:
            return
        for fip_ref in fip_refs:
            fip = self.vnc_lib.floating_ip_read(id=fip_ref['uuid'])
            fip.del_virtual_machine_interface(vmi)
            self.vnc_lib.floating_ip_update(fip)

    def _detach_service_instances_from_instance_ip(self, instance_ip_uuid):
        instance_ip = self.vnc_lib.instance_ip_read(id=instance_ip_uuid)
        service_refs = instance_ip.get_service_instance_back_refs()
        if service_refs is None:
            return
        for service_ref in service_refs:
            service_instance = self.vnc_lib.service_instance_read(id=service_ref['uuid'])
            service_instance.del_instance_ip(instance_ip)
            self.vnc_lib.service_instance_update(service_instance)


def construct_ipam(project):
    return vnc_api.NetworkIpam(
        name=VNC_VCENTER_IPAM,
        parent_obj=project
    )


def construct_security_group(project):
    security_group = vnc_api.SecurityGroup(name=VNC_VCENTER_DEFAULT_SG,
                                           parent_obj=project)

    security_group_entry = vnc_api.PolicyEntriesType()

    ingress_rule = vnc_api.PolicyRuleType(
        rule_uuid=str(uuid4()),
        direction='>',
        protocol='any',
        src_addresses=[vnc_api.AddressType(
            security_group=':'.join(VNC_VCENTER_DEFAULT_SG_FQN))],
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
        dst_addresses=[vnc_api.AddressType(subnet=vnc_api.SubnetType('0.0.0.0', 0))],
        dst_ports=[vnc_api.PortType(0, 65535)],
        ethertype='IPv4',
    )

    security_group_entry.add_policy_rule(ingress_rule)
    security_group_entry.add_policy_rule(egress_rule)

    security_group.set_security_group_entries(security_group_entry)
    return security_group


def construct_project():
    return vnc_api.Project(name=VNC_VCENTER_PROJECT)


class VRouterAPIClient(object):
    """ A client for Contrail VRouter Agent REST API. """

    def __init__(self):
        self.vrouter_host = 'http://localhost'
        self.vrouter_port = '9091'
        self._port_files_dir = '/var/lib/contrail/ports/'
        self._dir_exists = False
        self._create_ports_directory()
        self._session = requests.Session()

    def _create_ports_directory(self):
        if os.path.isdir(self._port_files_dir):
            self._dir_exists = True
            return
        try:
            os.makedirs(self._port_files_dir)
            self._dir_exists = True
        except OSError:
            logger.error('Unable to create %s directory', self._port_files_dir)
            self._dir_exists = False

    def _write_port_to_file(self, port_uuid, port_data):
        if not self._dir_exists:
            logger.error('Unable to create port file because %s does not exists', self._port_files_dir)
        filename = "%s%s" % (self._port_files_dir, port_uuid)
        with open(filename, 'w') as outfile:
            json.dump(port_data, outfile, True)

    def _read_port_from_file(self, port_uuid):
        filename = "%s%s" % (self._port_files_dir, port_uuid)
        with open(filename, 'r') as port_file:
            json_data = port_file.read()
            return json.loads(json_data)

    def _delete_port_file(self, port_uuid):
        filename = "%s%s" % (self._port_files_dir, port_uuid)
        if os.path.isfile(filename):
            os.remove(filename)

    def add_port(self, vmi_model):
        """ Add port to VRouter Agent. """
        try:
            ip_address = vmi_model.ip_address
            if vmi_model.vnc_instance_ip:
                ip_address = vmi_model.vnc_instance_ip.instance_ip_address

            parameters = {
                "id": vmi_model.uuid,
                "instance-id": vmi_model.vm_model.uuid,
                "display-name": vmi_model.vm_model.name,
                "ip-address": ip_address,
                "ip6-address": "::",
                "vn-id": vmi_model.vn_model.uuid,
                "vm-project-id": vmi_model.vn_model.vnc_vn.parent_uuid,
                "mac-address": vmi_model.vcenter_port.mac_address,
                "system-name": vmi_model.uuid,
                "type": 2,
                "rx-vlan-id": vmi_model.vcenter_port.vlan_id,
                "tx-vlan-id": vmi_model.vcenter_port.vlan_id,
                "vhostuser-mode": 0,
                "link-state": 0,
                "author": "contrail-vcenter-manager",
                "time": str(datetime.datetime.now()),

            }
            parameters = json.dumps(parameters)
            request_url = '{host}:{port}/port'.format(host=self.vrouter_host, port=self.vrouter_port)
            response = self._session.post(request_url, data=parameters, headers={'content-type': 'application/json'})
            if response.status_code == requests.codes.ok:
                logger.info('Added port to vRouter with parameters: %s', parameters)
            else:
                logger.error('Add port vRouter call return fail %s code with data %s', response.status_code, parameters)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)
            logger.info('Dumping port %s to file', vmi_model.uuid)
            self._write_port_to_file(vmi_model.uuid, parameters)

    def delete_port(self, vmi_uuid):
        """ Delete port from VRouter Agent. """
        request_url = '{host}:{port}/port/{uuid}'.format(host=self.vrouter_host,
                                                         port=self.vrouter_port,
                                                         uuid=vmi_uuid)
        try:
            response = self._session.delete(request_url)
            if response.status_code == requests.codes.ok:
                logger.info('Removed port from vRouter with uuid: %s', vmi_uuid)
            else:
                logger.error('Delete port vRouter call return fail %s code', response.status_code)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)
            logger.info('Deleting port %s file', vmi_uuid)
            self._delete_port_file(vmi_uuid)

    def enable_port(self, vmi_uuid):
        try:
            request_url = '{host}:{port}/enable-port/{uuid}'.format(host=self.vrouter_host,
                                                             port=self.vrouter_port,
                                                             uuid=vmi_uuid)
            response = self._session.put(request_url)
            if response.status_code == requests.codes.ok:
                logger.info('Enabled port from vRouter with uuid: %s', vmi_uuid)
            else:
                logger.error('Enable port vRouter call return fail %s code', response.status_code)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)
            logger.info('Updating port %s file', vmi_uuid)
            port_data = self._read_port_from_file(vmi_uuid)
            port_data['link-state'] = 1
            self._write_port_to_file(vmi_uuid, port_data)

    def disable_port(self, vmi_uuid):
        try:
            request_url = '{host}:{port}/disable-port/{uuid}'.format(host=self.vrouter_host,
                                                                    port=self.vrouter_port,
                                                                    uuid=vmi_uuid)
            response = self._session.put(request_url)
            if response.status_code == requests.codes.ok:
                logger.info('Disabled port from vRouter with uuid: %s', vmi_uuid)
            else:
                logger.error('Disable port vRouter call return fail %s code', response.status_code)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)
            logger.info('Updating port %s file', vmi_uuid)
            port_data = self._read_port_from_file(vmi_uuid)
            port_data['link-state'] = 0
            self._write_port_to_file(vmi_uuid, port_data)

    def read_port(self, vmi_uuid):
        request_url = '{host}:{port}/port/{uuid}'.format(host=self.vrouter_host,
                                                         port=self.vrouter_port,
                                                         uuid=vmi_uuid)
        try:
            response = self._session.get(request_url)
            if response.status_code == requests.codes.ok:
                port_properties = json.loads(response.content)
                logger.info('Read vRouter port with uuid: %s, port properties: %s', vmi_uuid, port_properties)
                return port_properties
            else:
                logger.info('Read port vRouter call return fail %s code', response.status_code)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)
