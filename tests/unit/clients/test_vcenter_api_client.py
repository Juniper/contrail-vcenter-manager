from mock import patch

from cvm.clients import VCenterAPIClient


def test_set_vlan_id(vcenter_api_client, dvs, vcenter_port):
    vcenter_port.vlan_id = 10

    with patch('cvm.clients.SmartConnectNoSSL'):
        with patch.object(VCenterAPIClient, '_get_dvswitch', return_value=dvs):
            with vcenter_api_client:
                vcenter_api_client.set_vlan_id(vcenter_port)

    dvs.ReconfigureDVPort_Task.assert_called_once()
    spec = dvs.ReconfigureDVPort_Task.call_args[1].get('port', [None])[0]
    assert spec is not None
    assert spec.key == '8'
    assert spec.configVersion == '1'
    assert spec.setting.vlan.vlanId == 10


def test_enable_vlan_override(vcenter_api_client, portgroup):
    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            vcenter_api_client.enable_vlan_override(portgroup=portgroup)

    portgroup.ReconfigureDVPortgroup_Task.assert_called_once()
    config = portgroup.ReconfigureDVPortgroup_Task.call_args[0][0]
    assert config.policy.vlanOverrideAllowed is True
    assert config.configVersion == '1'


def test_get_vlan_id(vcenter_api_client, dvs, vcenter_port, dv_port):
    dv_port.config.setting.vlan.vlanId = 10
    dv_port.config.setting.vlan.inherited = False

    with patch('cvm.clients.SmartConnectNoSSL'):
        with patch.object(VCenterAPIClient, '_get_dvswitch', return_value=dvs):
            with vcenter_api_client:
                result = vcenter_api_client.get_vlan_id(vcenter_port)

    assert result == 10


def test_restore_vlan_id(vcenter_api_client, dvs, vcenter_port):
    with patch('cvm.clients.SmartConnectNoSSL'):
        with patch.object(VCenterAPIClient, '_get_dvswitch', return_value=dvs):
            with vcenter_api_client:
                vcenter_api_client.restore_vlan_id(vcenter_port)

    dvs.ReconfigureDVPort_Task.assert_called_once()
    spec = dvs.ReconfigureDVPort_Task.call_args[1].get('port', [None])[0]
    assert spec is not None
    assert spec.key == '8'
    assert spec.configVersion == '1'
    assert spec.setting.vlan.inherited is True


def test_reserved_vlans_for_dpg(vcenter_api_client, dvs, dv_port):
    dv_port.config.setting.vlan.vlanId = 10
    dv_port.config.setting.vlan.inherited = False

    with patch('cvm.clients.SmartConnectNoSSL'):
        with patch.object(VCenterAPIClient, '_get_dvswitch', return_value=dvs):
            with vcenter_api_client:
                vlans = vcenter_api_client.get_reserved_vlans_for_dpg('dvportgroup-1')

    assert vlans == [10]
