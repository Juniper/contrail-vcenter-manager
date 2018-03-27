from unittest import TestCase

from mock import Mock
from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import VirtualNetwork

from cvm.models import VirtualMachineModel, VirtualNetworkModel
from cvm.services import VirtualMachineService


class TestVirtualMachineModel(TestCase):

    def setUp(self):
        self.vmware_dpg = self._create_dpg_mock(name='VM Portgroup', key='dportgroup-50')
        vmware_vm = self._create_vmware_vm_mock([
            self.vmware_dpg,
            Mock(spec=vim.Network),
        ])
        vmware_vm.config.hardware.device = []
        self.vm_model = VirtualMachineModel(vmware_vm)
        self.vnc_client = Mock()
        self.vcenter_client = self._create_vcenter_client_mock(self.vmware_dpg)
        self.database = Mock()
        self.vm_service = VirtualMachineService(None, self.vnc_client, self.database)

    def test_get_vn_models_for_vm(self):
        vnc_vn = VirtualNetwork()
        self.database.get_vn_model_by_key.return_value = VirtualNetworkModel(self.vmware_dpg, vnc_vn, None)

        result = self.vm_service._get_vn_models_for_vm(self.vm_model)

        self.assertEqual([vnc_vn], [vn_model.vnc_vn for vn_model in result])

    def test_get_vn_models_for_vm_novn(self):
        """ Non-existing VNC VN. """
        self.database.get_vn_model_by_key.return_value = None

        result = self.vm_service._get_vn_models_for_vm(self.vm_model)

        self.assertEqual([], result)

    @staticmethod
    def _create_vmware_vm_mock(network):
        vmware_vm = Mock()
        vmware_vm.summary.runtime.host.vm = []
        vmware_vm.network = network
        return vmware_vm

    @staticmethod
    def _create_dpg_mock(**kwargs):
        dpg_mock = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
        for kwarg in kwargs:
            setattr(dpg_mock, kwarg, kwargs[kwarg])
        return dpg_mock

    @staticmethod
    def _create_vcenter_client_mock(vmware_dpg):
        vcenter_client = Mock()
        vcenter_client.get_dpgs_for_vm.return_value = [vmware_dpg]
        vcenter_client.__enter__ = Mock()
        vcenter_client.__exit__ = Mock()
        vcenter_client.get_ip_pool_for_dpg.return_value = None
        return vcenter_client
