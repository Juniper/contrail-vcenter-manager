# pylint: disable=redefined-outer-name
import pytest
from mock import Mock


@pytest.fixture()
def vrouter_response():
    return {'author': '/usr/bin/contrail-vrouter-agent',
            'dns-server': '192.168.200.2',
            'gateway': '192.168.200.254',
            'id': 'fe71b44d-0654-36aa-9841-ab9b78d628c5',
            'instance-id': '502789bb-240a-841f-e24c-1564537218f7',
            'ip-address': '192.168.200.5',
            'ip6-address': '::',
            'mac-address': '00:50:56:bf:7d:a1',
            'plen': 24,
            'rx-vlan-id': 7,
            'system-name': 'fe71b44d-0654-36aa-9841-ab9b78d628c5',
            'time': '424716:04:42.065040',
            'tx-vlan-id': 7,
            'vhostuser-mode': 0,
            'vm-project-id': '00000000-0000-0000-0000-000000000000',
            'vn-id': 'f94fe52e-cf19-48dd-9697-8c2085e7cbee'}


@pytest.fixture()
def vmi_model():
    vmi = Mock()
    vmi.uuid = 'fe71b44d-0654-36aa-9841-ab9b78d628c5'
    vmi.vm_model.uuid = '502789bb-240a-841f-e24c-1564537218f7'
    vmi.vn_model.uuid = 'f94fe52e-cf19-48dd-9697-8c2085e7cbee'
    vmi.vcenter_port.vlan_id = 7
    vmi.vnc_instance_ip.instance_ip_address = '192.168.200.5'
    vmi.ip_address = '192.168.200.5'
    return vmi


def test_false(vrouter_port_service, database, vrouter_api_client, vmi_model, vrouter_response):
    database.ports_to_update.append(vmi_model)
    vrouter_api_client.read_port.return_value = vrouter_response

    vrouter_port_service.sync_ports()

    vrouter_api_client.delete_port.assert_not_called()
    vrouter_api_client.add_port.assert_not_called()


def test_true(vrouter_port_service, database, vrouter_api_client, vmi_model):
    database.ports_to_update.append(vmi_model)
    vrouter_api_client.read_port.return_value = None

    vrouter_port_service.sync_ports()

    vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)
    vrouter_api_client.add_port.assert_called_once_with(vmi_model)
