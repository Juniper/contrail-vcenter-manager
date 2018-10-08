import logging

from cvm.constants import VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT
from cvm.models import VirtualNetworkModel
from cvm.services.service import Service

logger = logging.getLogger(__name__)


class VirtualNetworkService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, database):
        super(VirtualNetworkService, self).__init__(vnc_api_client, database)
        self._vcenter_api_client = vcenter_api_client

    def sync_vns(self):
        with self._vcenter_api_client:
            for vnc_vn in self._vnc_api_client.get_vns_by_project(self._project):
                dpg = self._vcenter_api_client.get_dpg_by_name(vnc_vn.name)
                if vnc_vn and dpg:
                    self._create_vn_model(dpg, vnc_vn)
                else:
                    logger.error('Unable to fetch new portgroup for name: %s', vnc_vn.name)

    def update_vns(self):
        for vmi_model in self._database.vmis_to_update:
            portgroup_key = vmi_model.vcenter_port.portgroup_key
            if self._database.get_vn_model_by_key(portgroup_key) is not None:
                continue
            logger.info('Fetching new portgroup for key: %s', portgroup_key)
            with self._vcenter_api_client:
                dpg = self._vcenter_api_client.get_dpg_by_key(portgroup_key)
                fq_name = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, dpg.name]
                vnc_vn = self._vnc_api_client.read_vn(fq_name)
                if dpg and vnc_vn:
                    self._create_vn_model(dpg, vnc_vn)
                else:
                    logger.error('Unable to fetch new portgroup for key: %s', portgroup_key)

    def _create_vn_model(self, dpg, vnc_vn):
        logger.info('Fetched new portgroup key: %s name: %s', dpg.key, vnc_vn.name)
        vn_model = VirtualNetworkModel(dpg, vnc_vn)
        self._vcenter_api_client.enable_vlan_override(vn_model.vmware_vn)
        self._database.save(vn_model)
        logger.info('Created %s', vn_model)
