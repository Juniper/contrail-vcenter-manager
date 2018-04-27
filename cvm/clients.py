import atexit
import logging
from uuid import uuid4

from contrail_vrouter_api.vrouter_api import ContrailVRouterApi
from pyVim.connect import Disconnect, SmartConnectNoSSL
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.exceptions import NoIdError, RefsExistError

from cvm.constants import (VM_PROPERTY_FILTERS, VNC_ROOT_DOMAIN,
                           VNC_VCENTER_DEFAULT_SG, VNC_VCENTER_DEFAULT_SG_FQN,
                           VNC_VCENTER_IPAM, VNC_VCENTER_PROJECT)

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


def make_dv_port_spec(dv_port, vlan_id):
    dv_port_config_spec = vim.dvs.DistributedVirtualPort.ConfigSpec()
    dv_port_config_spec.key = dv_port.key
    dv_port_config_spec.operation = 'edit'
    dv_port_config_spec.configVersion = dv_port.config.configVersion
    vlan_spec = vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec()
    vlan_spec.vlanId = vlan_id
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

    def get_ip_pool_for_dpg(self, dpg):
        return self._get_ip_pool_by_id(dpg.summary.ipPoolId)

    def _get_ip_pool_by_id(self, pool_id):
        for ip_pool in self._si.content.ipPoolManager.QueryIpPools(self._datacenter):
            if ip_pool.id == pool_id:
                return ip_pool
        return None

    @staticmethod
    def set_vlan_id(dvs, key, vlan_id):
        dv_port = [port for port in dvs.FetchDVPorts() if port.key == key][0]
        dv_port_spec = make_dv_port_spec(dv_port, vlan_id)
        dvs.ReconfigureDVPort_Task(port=[dv_port_spec])

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
        return [self._read_vm(vm['fq_name']) for vm in vms]

    def _read_vm(self, fq_name):
        return self.vnc_lib.virtual_machine_read(fq_name)

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
        return [self._read_vmi(vmi['fq_name']) for vmi in vmis]

    def _read_vmi(self, fq_name):
        return self.vnc_lib.virtual_machine_interface_read(fq_name)

    def get_vns_by_project(self, project):
        vns = self.vnc_lib.virtual_networks_list(parent_id=project.uuid).get('virtual-networks')
        return [self._read_vn(vn['fq_name']) for vn in vns]

    def _read_vn(self, fq_name):
        return self.vnc_lib.virtual_network_read(fq_name)

    def create_or_read_project(self):
        try:
            self._create_project()
        except vnc_api.RefsExistError:
            pass
        return self._read_project()

    def _create_project(self):
        project = construct_project()
        try:
            project.set_id_perms(self.id_perms)
            self.vnc_lib.project_create(project)
            logger.info('Project created: %s', project.name)
        except RefsExistError:
            logger.error('Project already exists: %s', project.name)

    def _read_project(self):
        fq_name = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT]
        return self.vnc_lib.project_read(fq_name)

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


def construct_project():
    return vnc_api.Project(name=VNC_VCENTER_PROJECT)


class VRouterAPIClient(object):
    """ A client for Contrail VRouter Agent REST API. """

    def __init__(self):
        self.vrouter_api = ContrailVRouterApi()

    def add_port(self, vmi_model):
        """ Add port to VRouter Agent. """
        try:
            self.vrouter_api.add_port(
                vm_uuid_str=vmi_model.vm_model.uuid,
                vif_uuid_str=vmi_model.uuid,
                interface_name=vmi_model.uuid,
                mac_address=vmi_model.mac_address,
                ip_address=vmi_model.ip_address,
                vn_id=vmi_model.vn_model.uuid,
                display_name=vmi_model.vm_model.name,
                vlan=vmi_model.vn_model.primary_vlan_id,
            )
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s' % e)

    def delete_port(self, vmi_uuid):
        """ Delete port from VRouter Agent. """
        try:
            self.vrouter_api.delete_port(vmi_uuid)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s' % e)
