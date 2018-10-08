class VRouterPortService(object):
    def __init__(self, vrouter_api_client, database):
        self._vrouter_api_client = vrouter_api_client
        self._database = database

    def sync_ports(self):
        self._delete_ports()
        self._update_ports()
        self.sync_port_states()

    def sync_port_states(self):
        ports = [vmi_model for vmi_model in self._database.ports_to_update]
        for vmi_model in ports:
            self._set_port_state(vmi_model)
            self._database.ports_to_update.remove(vmi_model)

    def _delete_ports(self):
        uuids = [uuid for uuid in self._database.ports_to_delete]
        for uuid in uuids:
            self._delete_port(uuid)
            self._database.ports_to_delete.remove(uuid)

    def _delete_port(self, uuid):
        self._vrouter_api_client.delete_port(uuid)

    def _update_ports(self):
        ports = [vmi_model for vmi_model in self._database.ports_to_update]
        for vmi_model in ports:
            if self._port_needs_an_update(vmi_model):
                self._update_port(vmi_model)

    def _port_needs_an_update(self, vmi_model):
        vrouter_port = self._vrouter_api_client.read_port(vmi_model.uuid)
        if not vrouter_port:
            return True
        return (vrouter_port.get('instance-id') != vmi_model.vm_model.uuid or
                vrouter_port.get('vn-id') != vmi_model.vn_model.uuid or
                vrouter_port.get('rx-vlan-id') != vmi_model.vcenter_port.vlan_id or
                vrouter_port.get('tx-vlan-id') != vmi_model.vcenter_port.vlan_id or
                vrouter_port.get('ip-address') != vmi_model.vnc_instance_ip.instance_ip_address)

    def _update_port(self, vmi_model):
        self._vrouter_api_client.delete_port(vmi_model.uuid)
        self._vrouter_api_client.add_port(vmi_model)

    def _set_port_state(self, vmi_model):
        if vmi_model.vm_model.is_powered_on:
            self._vrouter_api_client.enable_port(vmi_model.uuid)
        else:
            self._vrouter_api_client.disable_port(vmi_model.uuid)
