from unittest import TestCase

from cvm.database import VlanIdPool


class TestVlanIdPool(TestCase):
    def setUp(self):
        self.vlan_id_pool = VlanIdPool()

    def test_reserve(self):
        self.vlan_id_pool.reserve(0)

        self.assertNotIn(0, self.vlan_id_pool._available_ids)

    def test_reserve_existing(self):
        self.vlan_id_pool.reserve(0)

        self.vlan_id_pool.reserve(0)

        self.assertNotIn(0, self.vlan_id_pool._available_ids)

    def test_get_first_available(self):
        self.vlan_id_pool.reserve(0)

        result = self.vlan_id_pool.get_available()

        self.assertEqual(1, result)
        self.assertNotIn(1, self.vlan_id_pool._available_ids)

    def test_no_available(self):
        for i in range(4095):
            self.vlan_id_pool.reserve(i)

        result = self.vlan_id_pool.get_available()

        self.assertIsNone(result)

    def test_free(self):
        self.vlan_id_pool.reserve(0)

        self.vlan_id_pool.free(0)

        self.assertIn(0, self.vlan_id_pool._available_ids)
