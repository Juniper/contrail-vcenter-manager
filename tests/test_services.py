from unittest import TestCase
from mock import Mock
from pyVmomi import vim  # pylint: disable=no-name-in-module
from cvm.database import Database
from cvm.models import VirtualNetworkModel, VirtualMachineModel
from cvm.services import VirtualMachineService


class TestVirtualMachineModel(TestCase):

    def setUp(self):
        self.vmware_dpg = self._create_dpg_mock(key='dvportgroup-51')
        vmware_vm = self._create_vmware_vm_mock([
            self.vmware_dpg,
            Mock(spec=vim.Network),
        ])
        self.vm_model = VirtualMachineModel(vmware_vm)

    def test_get_vn_models_for_vm(self):
        vn_model = VirtualNetworkModel(self.vmware_dpg, None)
        database = Database()
        database.save(vn_model)
        vm_service = VirtualMachineService(None, None, database)

        result = vm_service._get_vn_models_for_vm(self.vm_model)

        self.assertEqual([vn_model], result)

    def test_get_vn_models_for_vm_e_db(self):
        """ No VN models in Database. """
        database = Database()
        vm_service = VirtualMachineService(None, None, database)

        result = vm_service._get_vn_models_for_vm(self.vm_model)

        self.assertEqual([], result)

    @staticmethod
    def _create_vmware_vm_mock(network):
        vmware_vm = Mock()
        vmware_vm.summary.runtime.host.vm = []
        vmware_vm.network = network
        return vmware_vm

    @staticmethod
    def _create_dpg_mock(key):
        vmware_dpg = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
        vmware_dpg.config.key = key
        return vmware_dpg
