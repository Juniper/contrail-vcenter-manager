import atexit
import json
import logging
from uuid import uuid4

import requests
from contrail_vrouter_api.vrouter_api import ContrailVRouterApi
from pyVim.connect import Disconnect, SmartConnectNoSSL
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.exceptions import NoIdError

from cvm.constants import (VM_PROPERTY_FILTERS, VNC_ROOT_DOMAIN,
                           VNC_VCENTER_DEFAULT_SG, VNC_VCENTER_DEFAULT_SG_FQN,
                           VNC_VCENTER_IPAM, VNC_VCENTER_IPAM_FQN,
                           VNC_VCENTER_PROJECT)
from cvm.models import find_vrouter_uuid

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
    pg_config_spec.policy = portgroup.config.policy
    pg_config_spec.policy.vlanOverrideAllowed = True
    pg_config_spec.configVersion = portgroup.config.configVersion
    return pg_config_spec


def fetch_port_from_dvs(dvs, port_key):
    criteria = vim.dvs.PortCriteria()
    criteria.portKey = port_key
    try:
        return next(port for port in dvs.FetchDVPorts(criteria))
    except StopIteration:
        return None


class VSphereAPIClient(object):
    def __init__(self):
        self._si = None
        self._datacenter = None

    def _get_datacenter(self, name):
        return self._get_object([vim.Datacenter], name)

    def _get_object(self, vimtype, name):
        """
         Get the vsphere object associated with a given text name
        """
        content = self._si.content
        container = content.viewManager.CreateContainerView(content.rootFolder, vimtype, True)
        try:
            return [obj for obj in container.view if obj.name == name][0]
        except IndexError:
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
        self._datacenter = self._get_datacenter(esxi_cfg.get('datacenter'))
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
        return {prop.name: prop.val for prop in prop_set}

    def read_vrouter_uuid(self):
        host = self._datacenter.hostFolder.childEntity[0].host[0]
        return find_vrouter_uuid(host)


class VCenterAPIClient(VSphereAPIClient):
    def __init__(self, vcenter_cfg):
        super(VCenterAPIClient, self).__init__()
        self._vcenter_cfg = vcenter_cfg

    def __enter__(self):
        self._si = SmartConnectNoSSL(
            host=self._vcenter_cfg.get('host'),
            user=self._vcenter_cfg.get('username'),
            pwd=self._vcenter_cfg.get('password'),
            port=self._vcenter_cfg.get('port'),
            preferredApiVersions=self._vcenter_cfg.get('preferred_api_versions')
        )
        self._datacenter = self._get_datacenter(self._vcenter_cfg.get('datacenter'))

    def __exit__(self, *args):
        Disconnect(self._si)

    def get_dpg_by_name(self, name):
        for dpg in self._datacenter.network:
            if dpg.name == name and isinstance(dpg, vim.dvs.DistributedVirtualPortgroup):
                return dpg
        return None

    def set_vlan_id(self, vcenter_port):
        dvs = self._get_dvs_by_uuid(vcenter_port.dvs_uuid)
        dv_port = fetch_port_from_dvs(dvs, vcenter_port.port_key)
        if not dv_port:
            return
        dv_port_spec = make_dv_port_spec(dv_port, vcenter_port.vlan_id)
        logger.info('Setting VLAN ID of port %s to %d', vcenter_port.port_key, vcenter_port.vlan_id)
        dvs.ReconfigureDVPort_Task(port=[dv_port_spec])

    def get_vlan_id(self, vcenter_port):
        dvs = self._get_dvs_by_uuid(vcenter_port.dvs_uuid)
        dv_port = fetch_port_from_dvs(dvs, vcenter_port.port_key)
        if not dv_port.config.setting.vlan.inherited:
            return dv_port.config.setting.vlan.vlanId
        return None

    def restore_vlan_id(self, vcenter_port):
        dvs = self._get_dvs_by_uuid(vcenter_port.dvs_uuid)
        dv_port = fetch_port_from_dvs(dvs, vcenter_port.port_key)
        dv_port_config_spec = make_dv_port_spec(dv_port)
        dvs.ReconfigureDVPort_Task(port=[dv_port_config_spec])

    def _get_dvs_by_uuid(self, uuid):
        dvs_manager = self._si.content.dvSwitchManager
        return dvs_manager.QueryDvsByUuid(uuid)

    @staticmethod
    def enable_vlan_override(portgroup):
        pg_config_spec = make_pg_config_vlan_override(portgroup)
        portgroup.ReconfigureDVPortgroup_Task(pg_config_spec)


class VNCAPIClient(object):
    def __init__(self, vnc_cfg):
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
        vm = self.read_vm(uuid)
        for vmi_ref in vm.get_virtual_machine_interface_back_refs() or []:
            self.delete_vmi(vmi_ref.get('uuid'))
        try:
            self.vnc_lib.virtual_machine_delete(id=uuid)
            logger.info('Virtual Machine removed: %s', uuid)
        except NoIdError:
            logger.error('Virtual Machine not found: %s', uuid)

    def update_or_create_vm(self, vnc_vm):
        try:
            self._update_vm(vnc_vm)
        except NoIdError:
            logger.info('Virtual Machine not found - creating: %s', vnc_vm.name)
            self._create_vm(vnc_vm)

    def _update_vm(self, vnc_vm):
        self.vnc_lib.virtual_machine_update(vnc_vm)
        logger.info('Virtual Machine updated: %s', vnc_vm.name)

    def _create_vm(self, vnc_vm):
        self.vnc_lib.virtual_machine_create(vnc_vm)
        logger.info('Virtual Machine created: %s', vnc_vm.name)

    def get_all_vms(self):
        vms = self.vnc_lib.virtual_machines_list().get('virtual-machines')
        return [self.read_vm(vm['uuid']) for vm in vms]

    def read_vm(self, uuid):
        return self.vnc_lib.virtual_machine_read(id=uuid)

    def update_or_create_vmi(self, vnc_vmi):
        try:
            self._update_vmi(vnc_vmi)
        except NoIdError:
            logger.info('Virtual Machine Interface not found - creating: %s', vnc_vmi.name)
            self._create_vmi(vnc_vmi)

    def _update_vmi(self, vnc_vmi):
        self.vnc_lib.virtual_machine_interface_update(vnc_vmi)
        logger.info('Virtual Machine Interface updated: %s', vnc_vmi.name)

    def _create_vmi(self, vmi):
        self.vnc_lib.virtual_machine_interface_create(vmi)
        logger.info('Virtual Machine Interface created: %s', vmi.display_name)

    def delete_vmi(self, uuid):
        vmi = self.read_vmi(uuid)
        for instance_ip_ref in vmi.get_instance_ip_back_refs() or []:
            self.delete_instance_ip(instance_ip_ref.get('uuid'))

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
        return [self.read_vmi(vmi['uuid']) for vmi in vmis]

    def read_vmi(self, uuid):
        try:
            return self.vnc_lib.virtual_machine_interface_read(id=uuid)
        except NoIdError:
            logger.error('Virtual Machine Interface not found %s', uuid)
            return None

    def get_vns_by_project(self, project):
        vns = self.vnc_lib.virtual_networks_list(parent_id=project.uuid).get('virtual-networks')
        return [self._read_vn(vn['fq_name']) for vn in vns]

    def _read_vn(self, fq_name):
        return self.vnc_lib.virtual_network_read(fq_name)

    def read_or_create_project(self):
        try:
            return self._read_project()
        except NoIdError:
            logger.error('Project not found: %s, creating...', VNC_VCENTER_PROJECT)
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
            logger.error('Security group not found: %s, creating...', VNC_VCENTER_DEFAULT_SG_FQN)
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
            logger.error('Ipam not found: %s, creating...', VNC_VCENTER_IPAM_FQN)
            return self._create_ipam()

    def _read_ipam(self):
        return self.vnc_lib.network_ipam_read(VNC_VCENTER_IPAM_FQN)

    def _create_ipam(self):
        project = self._read_project()
        ipam = construct_ipam(project)
        self.vnc_lib.network_ipam_create(ipam)
        logger.info('Network IPAM created: %s', ipam.name)
        return ipam

    def create_and_read_instance_ip(self, instance_ip):
        try:
            return self._read_instance_ip(instance_ip.uuid)
        except NoIdError:
            self.vnc_lib.instance_ip_create(instance_ip)
            logger.debug("Created instanceIP: %s", instance_ip.name)
        return self._read_instance_ip(instance_ip.uuid)

    def delete_instance_ip(self, uuid):
        try:
            self.vnc_lib.instance_ip_delete(id=uuid)
        except NoIdError:
            logger.error('Instance IP not found: %s', uuid)

    def _read_instance_ip(self, uuid):
        return self.vnc_lib.instance_ip_read(id=uuid)


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


def construct_project():
    return vnc_api.Project(name=VNC_VCENTER_PROJECT)


class VRouterAPIClient(object):
    """ A client for Contrail VRouter Agent REST API. """

    def __init__(self):
        self.vrouter_api = ContrailVRouterApi()
        self.vrouter_host = 'http://localhost'
        self.vrouter_port = '9091'

    def add_port(self, vmi_model):
        """ Add port to VRouter Agent. """
        try:
            self.vrouter_api.add_port(
                vm_uuid_str=vmi_model.vm_model.uuid,
                vif_uuid_str=vmi_model.uuid,
                interface_name=vmi_model.uuid,
                mac_address=vmi_model.vcenter_port.mac_address,
                ip_address=vmi_model.vnc_instance_ip.instance_ip_address,
                vn_id=vmi_model.vn_model.uuid,
                display_name=vmi_model.vm_model.name,
                vlan=vmi_model.vcenter_port.vlan_id,
                rx_vlan=vmi_model.vcenter_port.vlan_id,
                port_type=2,
                vm_project_id=vmi_model.vn_model.vnc_vn.parent_uuid,
            )
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)

    def delete_port(self, vmi_uuid):
        """ Delete port from VRouter Agent. """
        try:
            self.vrouter_api.delete_port(vmi_uuid)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)

    def enable_port(self, vmi_uuid):
        try:
            self.vrouter_api.enable_port(vmi_uuid)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)

    def read_port(self, vmi_uuid):
        request_url = '{host}:{port}/port/{uuid}'.format(host=self.vrouter_host,
                                                         port=self.vrouter_port,
                                                         uuid=vmi_uuid)
        response = requests.get(request_url)
        if response.status_code != requests.codes.ok:
            return None

        return json.loads(response.content)
