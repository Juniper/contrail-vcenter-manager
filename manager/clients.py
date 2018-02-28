import atexit
import logging

from pyVim.connect import SmartConnectNoSSL, Disconnect
from vnc_api import vnc_api
from vnc_api.exceptions import RefsExistError, NoIdError

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

    def wait_for_changes(self):
        return None

    def create_vm(self, vm):
        try:
            self.vnc_lib.virtual_machine_create(vm)
            logger.info('Virtual Machine created: {}'.format(vm.name))
        except RefsExistError:
            logger.error('Virtual Machine already exists: {}'.format(vm.name))

    def delete_vm(self, name):
        try:
            self.vnc_lib.virtual_machine_delete([name])
            logger.info('Virtual Machine removed: {}'.format(name))
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(name))

    def read_vm(self, name):
        try:
            return self.vnc_lib.virtual_machine_read([name])
        except NoIdError:
            logger.error('Virtual Machine not found: {}'.format(name))
            return None

    def create_vmi(self, vmi):
        try:
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
