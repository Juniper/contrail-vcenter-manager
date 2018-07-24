import pytest

from tests.utils import reserve_vlan_ids


@pytest.fixture(autouse=True)
def prepare_database(database, vm_model, vn_model_1):
    database.save(vm_model)
    database.save(vn_model_1)
    return database


def test_sync_vlan_ids(vmi_service, vcenter_api_client, vlan_id_pool):
    vcenter_api_client.get_reserved_vlan_ids.return_value = [0, 1]

    vmi_service.sync_vlan_ids()
    new_vlan_id = vlan_id_pool.get_available()

    assert new_vlan_id == 2


def test_assign_new_vlan_id(vmi_service, database, vcenter_api_client,
                            vlan_id_pool, vmi_model):
    database.vmis_to_update.append(vmi_model)
    reserve_vlan_ids(vlan_id_pool, [0, 1])
    vcenter_api_client.get_vlan_id.return_value = None

    vmi_service.update_vmis()

    assert vmi_model.vcenter_port.vlan_id == 2


def test_retain_old_vlan_id(vmi_service, database, vcenter_api_client,
                            vlan_id_pool, vmi_model):
    database.vmis_to_update.append(vmi_model)
    reserve_vlan_ids(vlan_id_pool, [20])
    vcenter_api_client.get_vlan_id.return_value = 20

    vmi_service.update_vmis()

    assert vmi_model.vcenter_port.vlan_id == 20


def test_restore_vlan_id(vmi_service, database, vcenter_api_client,
                         vlan_id_pool, vmi_model):
    reserve_vlan_ids(vlan_id_pool, [20])
    database.vmis_to_delete.append(vmi_model)
    vmi_model.vcenter_port.vlan_id = 20

    vmi_service.update_vmis()

    vcenter_api_client.restore_vlan_id.assert_called_once_with(
        vmi_model.vcenter_port)
    assert vlan_id_pool.is_available(20)
