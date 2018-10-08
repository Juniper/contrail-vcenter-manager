class Service(object):
    def __init__(self, vnc_api_client, database, esxi_api_client=None, vcenter_api_client=None):
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._esxi_api_client = esxi_api_client
        self._vcenter_api_client = vcenter_api_client
        self._project = self._vnc_api_client.read_or_create_project()
        self._default_security_group = self._vnc_api_client.read_or_create_security_group()
        self._ipam = self._vnc_api_client.read_or_create_ipam()
        if self._esxi_api_client:
            self._vrouter_uuid = esxi_api_client.read_vrouter_uuid()
