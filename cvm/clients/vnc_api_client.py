import logging
import random
from uuid import uuid4

from vnc_api import vnc_api
from vnc_api.exceptions import NoIdError, RefsExistError

from cvm.constants import (VNC_ROOT_DOMAIN, VNC_VCENTER_DEFAULT_SG,
                           VNC_VCENTER_DEFAULT_SG_FQN, VNC_VCENTER_IPAM,
                           VNC_VCENTER_IPAM_FQN, VNC_VCENTER_PROJECT)

logger = logging.getLogger(__name__)


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

    def update_or_create_vm(self, vnc_vm):
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
        vn_fq_name = new_vmi.get_virtual_network_refs()[0]['to']
        logger.info('Updating Virtual Network of Interface %s to %s', new_vmi.name, vn_fq_name[2])
        vnc_vn = self.read_vn(vn_fq_name)
        old_vmi.set_virtual_network(vnc_vn)

    def _rename_vmi(self, old_vmi, new_vmi):
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

        for instance_ip_ref in vmi.get_instance_ip_back_refs() or []:
            self.delete_instance_ip(instance_ip_ref.get('uuid'))

        self.vnc_lib.virtual_machine_interface_delete(id=uuid)
        logger.info('Virtual Machine Interface %s removed from VNC', uuid)

    @classmethod
    def _update_vrouter_uuid(cls, vnc_obj, vrouter_uuid):
        new_annotations = vnc_api.KeyValuePairs()
        annotations = vnc_obj.get_annotations() or vnc_api.KeyValuePairs()
        for pair in annotations.key_value_pair:
            if pair.key != 'vrouter-uuid':
                new_annotations.add_key_value_pair(vnc_api.KeyValuePair(pair.key, pair.value))
        new_annotations.add_key_value_pair(
            vnc_api.KeyValuePair('vrouter-uuid', vrouter_uuid)
        )
        vnc_obj.annotations = new_annotations

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
            logger.error('Could not find VMI %s in VNC', uuid)
        return None

    def get_vns_by_project(self, project):
        vns = self.vnc_lib.virtual_networks_list(parent_id=project.uuid).get('virtual-networks')
        return [self.vnc_lib.virtual_network_read(vn['fq_name']) for vn in vns]

    def get_vn_uuid_for_vmi(self, vnc_vmi):
        return vnc_vmi.get_virtual_network_refs()[0]['uuid']

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

    def create_and_read_instance_ip(self, instance_ip):
        try:
            return self.read_instance_ip(instance_ip.uuid)
        except NoIdError:
            self.vnc_lib.instance_ip_create(instance_ip)
            logger.info("Created Instance IP: %s", instance_ip.name)
        return self.read_instance_ip(instance_ip.uuid)

    def delete_instance_ip(self, uuid):
        try:
            self.vnc_lib.instance_ip_delete(id=uuid)
        except NoIdError:
            logger.error('Instance IP not found: %s', uuid)

    def read_instance_ip(self, uuid):
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
