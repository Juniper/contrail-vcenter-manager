import logging

from pyVim.connect import Disconnect, SmartConnectNoSSL
from pyVmomi import vim  # pylint: disable=no-name-in-module

from cvm.clients.vsphere_api_client import VSphereAPIClient
from cvm.models import find_vrouter_uuid

logger = logging.getLogger(__name__)


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

    def can_remove_vm(self, name=None, uuid=None):
        if not (name or uuid):
            return False

        if name and self._get_object(vim.VirtualMachine, name):
            return False

        if uuid and self._get_vm_by_uuid(uuid):
            return False

        return True

    def can_rename_vm(self, vm_model, new_name):
        vmware_vm = self._get_object(vim.VirtualMachine, new_name)
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
    while task.info.state == 'running':
        continue
    if task.info.state == 'success':
        logger.info(success_message)
    elif task.info.state == 'error':
        logger.error(fault_message, task.info.error.msg)
    else:
        logger.error('vCenter task in unknown state: %s', task.info.state)


def get_vm_uuid_for_vmi(vnc_vmi):
    refs = vnc_vmi.get_virtual_machine_refs() or []
    if refs:
        return refs[0]['uuid']
