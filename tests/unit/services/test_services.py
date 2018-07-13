from unittest import TestCase

from mock import Mock

from cvm.models import VlanIdPool
from cvm.services import VirtualMachineInterfaceService, is_contrail_vm_name
from tests.utils import (create_vcenter_client_mock, create_vnc_client_mock,
                         reserve_vlan_ids)


class TestContrailVM(TestCase):
    def test_contrail_vm_name(self):
        contrail_name = 'ContrailVM-datacenter-0.0.0.0'
        regular_name = 'VM1'

        contrail_result = is_contrail_vm_name(contrail_name)
        regular_result = is_contrail_vm_name(regular_name)

        self.assertTrue(contrail_result)
        self.assertFalse(regular_result)


class TestVlanIds(TestCase):
    def setUp(self):
        self.vcenter_api_client = create_vcenter_client_mock()
        self.vcenter_api_client.get_reserved_vlans_for_dpg.return_value = []
        self.vlan_id_pool = VlanIdPool(0, 100)
        self.vmi_service = VirtualMachineInterfaceService(
            vcenter_api_client=self.vcenter_api_client,
            vnc_api_client=create_vnc_client_mock(),
            database=None,
            vlan_id_pool=self.vlan_id_pool
        )

    def test_sync_vlan_ids(self):
        self.vcenter_api_client.get_reserved_vlan_ids.return_value = [0, 1]

        self.vmi_service.sync_vlan_ids()
        new_vlan_id = self.vlan_id_pool.get_available()

        self.assertEqual(2, new_vlan_id)

    def test_assign_new_vlan_id(self):
        reserve_vlan_ids(self.vlan_id_pool, [0, 1])
        self.vcenter_api_client.get_vlan_id.return_value = None
        self.vcenter_api_client.get_reserved_vlans_for_dpg.return_value = [2]
        vmi_model = Mock()

        self.vmi_service._assign_vlan_id(vmi_model)

        vcenter_port = self.vcenter_api_client.set_vlan_id.call_args[0][0]
        self.assertEqual(3, vcenter_port.vlan_id)

    def test_retain_old_vlan_id(self):
        reserve_vlan_ids(self.vlan_id_pool, [20])
        self.vcenter_api_client.get_vlan_id.return_value = 20
        vmi_model = Mock()

        self.vmi_service._assign_vlan_id(vmi_model)

        self.assertEqual(0, vmi_model.vcenter_port.vlan_id)
        self.assertFalse(self.vlan_id_pool.is_available(20))
        self.vcenter_api_client.set_vlan_id.assert_called_once_with(vmi_model.vcenter_port)

    def test_restore_vlan_id(self):
        reserve_vlan_ids(self.vlan_id_pool, [20])
        vmi_model = Mock()
        vmi_model.vcenter_port.vlan_id = 20

        self.vmi_service._restore_vlan_id(vmi_model)

        self.vcenter_api_client.restore_vlan_id.assert_called_once_with(
            vmi_model.vcenter_port)
        self.assertIn(20, self.vlan_id_pool._available_ids)
