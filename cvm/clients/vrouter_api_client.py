import json
import logging

import requests

from contrail_vrouter_api.vrouter_api import ContrailVRouterApi

logger = logging.getLogger(__name__)


class VRouterAPIClient(object):
    """ A client for Contrail VRouter Agent REST API. """

    def __init__(self):
        self.vrouter_api = ContrailVRouterApi()
        self.vrouter_host = 'http://localhost'
        self.vrouter_port = '9091'

    def add_port(self, vmi_model):
        """ Add port to VRouter Agent. """
        try:
            ip_address = vmi_model.ip_address
            if vmi_model.vnc_instance_ip:
                ip_address = vmi_model.vnc_instance_ip.instance_ip_address

            parameters = dict(
                vm_uuid_str=vmi_model.vm_model.uuid,
                vif_uuid_str=vmi_model.uuid,
                interface_name=vmi_model.uuid,
                mac_address=vmi_model.vcenter_port.mac_address,
                ip_address=ip_address,
                vn_id=vmi_model.vn_model.uuid,
                display_name=vmi_model.vm_model.name,
                vlan=vmi_model.vcenter_port.vlan_id,
                rx_vlan=vmi_model.vcenter_port.vlan_id,
                port_type=2,
                # vrouter-port-control accepts only project's uuid without dashes
                vm_project_id=vmi_model.vn_model.vnc_vn.parent_uuid.replace('-', ''),
            )
            self.vrouter_api.add_port(**parameters)
            logger.info('Added port to vRouter with parameters: %s', parameters)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)

    def delete_port(self, vmi_uuid):
        """ Delete port from VRouter Agent. """
        try:
            self.vrouter_api.delete_port(vmi_uuid)
            logger.info('Removed port from vRouter with uuid: %s', vmi_uuid)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)

    def enable_port(self, vmi_uuid):
        try:
            self.vrouter_api.enable_port(vmi_uuid)
            logger.info('Enabled vRouter port with uuid: %s', vmi_uuid)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)

    def disable_port(self, vmi_uuid):
        try:
            self.vrouter_api.disable_port(vmi_uuid)
            logger.info('Disabled vRouter port with uuid: %s', vmi_uuid)
        except Exception, e:
            logger.error('There was a problem with vRouter API Client: %s', e)

    def read_port(self, vmi_uuid):
        request_url = '{host}:{port}/port/{uuid}'.format(host=self.vrouter_host,
                                                         port=self.vrouter_port,
                                                         uuid=vmi_uuid)
        response = requests.get(request_url)
        if response.status_code != requests.codes.ok:
            logger.info('Unable to read vRouter port with uuid: %s', vmi_uuid)
            return None

        port_properties = json.loads(response.content)
        logger.info('Read vRouter port with uuid: %s, port properties: %s', vmi_uuid, port_properties)
        return port_properties
