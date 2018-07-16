from cvm.constants import VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT
from tests.utils import assert_vn_model_state


def test_update_vns_no_vns(vn_service, database, vcenter_api_client, vnc_api_client):
    database.vmis_to_update = []

    vn_service.update_vns()

    assert database.get_all_vn_models() == []
    vcenter_api_client.get_dpg_by_key.assert_not_called()
    vnc_api_client.read_vn.assert_not_called()


def test_update_vns(vn_service, database, vcenter_api_client, vnc_api_client, vmi_model, vnc_vn_1, portgroup):
    vmi_model.vcenter_port.portgroup_key = 'dvportgroup-1'
    database.vmis_to_update.append(vmi_model)
    vcenter_api_client.get_dpg_by_key.return_value = portgroup
    vnc_api_client.read_vn.return_value = vnc_vn_1

    vn_service.update_vns()

    vn_model = database.get_vn_model_by_key('dvportgroup-1')
    assert vn_model is not None
    assert_vn_model_state(
        vn_model,
        key='dvportgroup-1',
        vnc_vn=vnc_vn_1,
        vmware_vn=portgroup,
    )
    vcenter_api_client.get_dpg_by_key.called_once_with('dvportgroup-1')
    vcenter_api_client.enable_vlan_override.called_once_with(portgroup)
    fq_name = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, 'DPG1']
    vnc_api_client.read_vn.called_once_with(fq_name)
