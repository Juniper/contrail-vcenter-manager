from cvm.clients import VCenterAPIClient
from mock import Mock, patch


def test_set_vlan_id(vcenter_api_client, dvs, vcenter_port):
    vcenter_port.vlan_id = 10

    with patch('cvm.clients.wait_for_task'):
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
    with patch('cvm.clients.wait_for_task'):
        with patch('cvm.clients.SmartConnectNoSSL'):
            with vcenter_api_client:
                vcenter_api_client.enable_vlan_override(portgroup=portgroup)

    portgroup.ReconfigureDVPortgroup_Task.assert_called_once()
    config = portgroup.ReconfigureDVPortgroup_Task.call_args[0][0]
    assert config.policy.vlanOverrideAllowed is True
    assert config.configVersion == '1'


def test_vlan_override_enabled(vcenter_api_client, portgroup):
    portgroup.config.policy.vlanOverrideAllowed = True

    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            vcenter_api_client.enable_vlan_override(portgroup=portgroup)

    portgroup.ReconfigureDVPortgroup_Task.assert_not_called()


def test_get_vlan_id(vcenter_api_client, dvs, vcenter_port, dv_port):
    dv_port.config.setting.vlan.vlanId = 10
    dv_port.config.setting.vlan.inherited = False

    with patch('cvm.clients.SmartConnectNoSSL'):
        with patch.object(VCenterAPIClient, '_get_dvswitch', return_value=dvs):
            with vcenter_api_client:
                result = vcenter_api_client.get_vlan_id(vcenter_port)

    assert result == 10


def test_restore_vlan_id(vcenter_api_client, dvs, vcenter_port):
    with patch('cvm.clients.wait_for_task'):
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


def test_can_remove_vm(vcenter_api_client, vm_model, vmware_vm_1):
    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_vm_by_uuid', return_value=vmware_vm_1):
                assert not vcenter_api_client.can_remove_vm(vm_model.uuid)

    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_vm_by_uuid', return_value=None):
                assert vcenter_api_client.can_remove_vm(vm_model.uuid)


def test_can_rename_vm(vcenter_api_client, vm_model, vmware_vm_1, host_2):
    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_object', return_value=vmware_vm_1):
                assert vcenter_api_client.can_rename_vm(vm_model, 'VM-renamed')

    vmware_vm_1.summary.runtime.host = host_2
    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_object', return_value=vmware_vm_1):
                assert not vcenter_api_client.can_rename_vm(vm_model, 'VM-renamed')


def test_can_remove_vmi(vcenter_api_client, vnc_vmi_1, vmware_vm_1):
    vnc_vmi_1.get_virtual_machine_refs.return_value = [{'uuid': vmware_vm_1.config.instanceUuid}]
    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_vm_by_uuid', return_value=vmware_vm_1):
                assert not vcenter_api_client.can_remove_vmi(vnc_vmi_1)

    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_vm_by_uuid', return_value=None):
                assert vcenter_api_client.can_remove_vmi(vnc_vmi_1)


def test_can_rename_vmi(vcenter_api_client, vmi_model, vmware_vm_1, host_2):
    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_object', return_value=vmware_vm_1):
                assert vcenter_api_client.can_rename_vmi(vmi_model, 'VM-renamed')

    vmware_vm_1.summary.runtime.host = host_2
    with patch('cvm.clients.SmartConnectNoSSL'):
        with vcenter_api_client:
            with patch.object(VCenterAPIClient, '_get_object', return_value=vmware_vm_1):
                assert not vcenter_api_client.can_rename_vmi(vmi_model, 'VM-renamed')


def test_get_all_vms(vcenter_api_client, vmware_vm_1, vmware_vm_2):
    with patch.object(VCenterAPIClient, '_get_datacenter') as dc_mock:
        dc_mock.return_value.datastore = [Mock(vm=[vmware_vm_1]), Mock(vm=[vmware_vm_2]), Mock(vm=[3])]
        with patch('cvm.clients.SmartConnectNoSSL'):
            with vcenter_api_client:
                vms = vcenter_api_client.get_all_vms()

    assert vms == [vmware_vm_1, vmware_vm_2]
