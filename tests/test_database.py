from unittest import TestCase

from mock import Mock

from cvm.database import Database
from cvm.models import (VirtualMachineInterfaceModel)
from tests.utils import create_vn_model, create_vm_model


class TestFindVirtualMachineIpAddress(TestCase):
    def setUp(self):
        self.database = Database()

    def test_get_vm_model_by_uuid(self):
        vm_model = create_vm_model(uuid='test-uuid')
        self.database.save(vm_model)
        self.assertEqual(self.database.get_vm_model_by_uuid('test-uuid'), vm_model)
        self.assertEqual(self.database.get_vm_model_by_uuid('dummy-uuid'), None)

    def test_get_vn_model_by_uuid(self):
        vn_model = create_vn_model('vn-model', 'key', uuid='test-uuid')
        self.database.save(vn_model)
        self.assertEqual(self.database.get_vn_model_by_uuid('test-uuid'), vn_model)
        self.assertEqual(self.database.get_vn_model_by_uuid('dummy-uuid'), None)

    def test_get_vn_model_by_key(self):
        vn_model = create_vn_model('vn-model', 'key')
        self.database.save(vn_model)
        self.assertEqual(self.database.get_vn_model_by_key('key'), vn_model)
        self.assertEqual(self.database.get_vn_model_by_uuid('dummy-key'), None)

    def test_delete_vm_model(self):
        vm_model = create_vm_model(uuid='uuid')
        self.database.save(vm_model)
        self.database.delete_vm_model('uuid')
        self.assertEqual(self.database.get_vm_model_by_uuid('uuid'), None)

    def test_delete_vn_model(self):
        vn_model = create_vn_model('vn-model', 'key')
        self.database.save(vn_model)
        self.database.delete_vn_model('key')
        self.assertEqual(self.database.get_vn_model_by_key('key'), None)

    def test_delete_vmi_model(self):
        vmi_model = Mock(spec=VirtualMachineInterfaceModel)
        vmi_model.uuid = 'test-uuid'
        self.database.save(vmi_model)
        self.database.delete_vmi_model('uuid')
        self.assertEqual(self.database.get_vmi_model_by_uuid('uuid'), None)
