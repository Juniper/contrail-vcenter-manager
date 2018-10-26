import pytest
from mock import patch

from tests.utils import reserve_vlan_ids


@pytest.fixture(autouse=True)
def prepare_database(database, vm_model, vn_model_1):
    database.save(vm_model)
    database.save(vn_model_1)
    return database


def test_sync_vlan_ids(vlan_id_service, vcenter_api_client, vlan_id_pool):
    vcenter_api_client.get_reserved_vlan_ids.return_value = [0, 1]

    vlan_id_service.sync_vlan_ids()
    new_vlan_id = vlan_id_pool.get_available()

    assert new_vlan_id == 2


@patch('cvm.services.time.sleep', return_value=None)
def test_assign_new_vlan_id(_, vlan_id_service, database, vcenter_api_client,
                            vlan_id_pool, vmi_model):
    database.vlans_to_update.append(vmi_model)
    reserve_vlan_ids(vlan_id_pool, [0, 1])
    vcenter_api_client.get_vlan_id.return_value = None

    vlan_id_service.update_vlan_ids()

    assert vmi_model.vcenter_port.vlan_id == 2
    assert not database.vlans_to_update


def test_retain_old_vlan_id(vlan_id_service, database, vcenter_api_client, vmi_model):
    database.vlans_to_update.append(vmi_model)
    vcenter_api_client.get_vlan_id.return_value = 20

    vlan_id_service.update_vlan_ids()

    assert vmi_model.vcenter_port.vlan_id == 20
    assert not database.vlans_to_update


@patch('cvm.services.time.sleep')
def test_current_not_available(_, vlan_id_service, database, vcenter_api_client,
                               vlan_id_pool, vmi_model, vmi_model_2):
    database.vlans_to_update.append(vmi_model)
    vmi_model_2.vcenter_port.vlan_id = 20
    database.save(vmi_model_2)
    vcenter_api_client.get_vlan_id.return_value = 20
    reserve_vlan_ids(vlan_id_pool, [20])

    vlan_id_service.update_vlan_ids()

    assert vmi_model.vcenter_port.vlan_id == 0
    assert not database.vlans_to_update


def test_restore_vlan_id(vlan_id_service, database, vcenter_api_client,
                         vlan_id_pool, vmi_model):
    reserve_vlan_ids(vlan_id_pool, [20])
    database.vlans_to_restore.append(vmi_model)
    vmi_model.vcenter_port.vlan_id = 20

    vlan_id_service.update_vlan_ids()

    vcenter_api_client.restore_vlan_id.assert_called_once_with(
        vmi_model.vcenter_port)
    assert vlan_id_pool.is_available(20)
    assert not database.vlans_to_restore
