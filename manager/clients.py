import atexit
import logging

from pyVim.connect import SmartConnectNoSSL, Disconnect
from vnc_api import vnc_api
from vnc_api.exceptions import RefsExistError, NoIdError
from constants import VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VCenterAPIClient(object):
    """A connector for interacting with vCenter API."""
    _version = ''

    def __init__(self, esxi_cfg):
        self.si = SmartConnectNoSSL(host=esxi_cfg['host'],
                                    user=esxi_cfg['username'],
                                    pwd=esxi_cfg['password'],
                                    port=esxi_cfg['port'],
                                    preferredApiVersions=esxi_cfg['preferred_api_versions'])
        atexit.register(Disconnect, self.si)


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
        self.vcenter_project = self.read_project([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT])
        if not self.vcenter_project:
            project = vnc_api.Project(VNC_VCENTER_PROJECT)
            self.create_project(project)

    def wait_for_changes(self):
        return None

    def create_vm(self, vm_model):
        try:
            self.vnc_lib.virtual_machine_create(vm_model.to_vnc_vm())
            logger.info('Virtual Machine created: {}'.format(vm_model.display_name))
        except RefsExistError:
            logger.error('Virtual Machine already exists: {}'.format(vm_model.display_name))

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

    def create_vmi(self, vmi):
        try:
            vmi.set_parent(self.vcenter_project)
            self.vnc_lib.virtual_machine_interface_create(vmi)
            logger.info('Virtual Machine Interface created: {}'.format(vmi.display_name))
        except RefsExistError:
            logger.error('Virtual Machine Interface already exists: {}')

    def read_vmi(self, name, uuid):
        try:
            return self.vnc_lib.virtual_machine_interface_read([name, uuid])
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(name))
            return None

    def read_vn(self, fq_name):
        try:
            return self.vnc_lib.virtual_network_read(fq_name)
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(fq_name))
            return None

    def create_project(self, project):
        try:
            project.set_id_perms(self.id_perms)
            self.vnc_lib.project_create(project)
            logger.info('Project created: {}'.format(project.name))
        except RefsExistError:
            logger.error('Project already exists: {}')

    def read_project(self, fq_name):
        try:
            return self.vnc_lib.project_read(fq_name)
        except NoIdError:
            logger.error('Project not found: {}')
            return None
