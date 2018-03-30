from unittest import TestCase

from mock import Mock
from pyVmomi import vim  # pylint: disable=no-name-in-module

from cvm.services import VirtualMachineService


class TestVirtualMachineService(TestCase):

    def setUp(self):
        self.vmware_dpg = self._create_dpg_mock(name='VM Portgroup', key='dportgroup-50')
        self.vmware_vm = self._create_vmware_vm_mock([
            self.vmware_dpg,
            Mock(spec=vim.Network),
        ])
        self.vnc_client = Mock()
        self.vcenter_client = self._create_vcenter_client_mock()
        self.database = Mock()
        self.esxi_api_client = Mock()
        self.vm_service = VirtualMachineService(self.esxi_api_client, self.vnc_client, self.database)

    def test_update_new_vm(self):
        self.database.get_vm_model_by_uuid.return_value = None

        vm_model = self.vm_service.update(self.vmware_vm)

        self.assertIsNotNone(vm_model)
        self.assertEqual(self.vmware_vm, vm_model.vmware_vm)
        self.assertEqual({'c8:5b:76:53:0f:f5': 'dportgroup-50'}, vm_model.interfaces)
        self.esxi_api_client.add_filter.assert_called_once_with(
            self.vmware_vm, ['guest.toolsRunningStatus', 'guest.net']
        )
        self.vnc_client.update_vm.assert_called_once_with(vm_model.vnc_vm)
        self.database.save.assert_called_once_with(vm_model)

    def test_update_existing_vm(self):
        old_vm_model = Mock()
        self.database.get_vm_model_by_uuid.return_value = old_vm_model

        new_vm_model = self.vm_service.update(self.vmware_vm)

        self.assertEqual(old_vm_model, new_vm_model)
        old_vm_model.set_vmware_vm.assert_called_once_with(self.vmware_vm)
        self.vnc_client.update_vm.assert_not_called()

    def test_update_new_no_vmis(self):
        """ Test creating of a new VM with no Interfaces. """
        self.database.get_vm_model_by_uuid.return_value = None
        self.vmware_vm.config.hardware.device = []

        vm_model = self.vm_service.update(self.vmware_vm)

        self.assertEqual({}, vm_model.interfaces)
        self.esxi_api_client.add_filter.assert_not_called()
        self.vnc_client.update_vm.assert_not_called()
        self.database.save.assert_not_called()

    def test_update_no_vmis(self):
        """ Test updating an existing VM with no Interfaces. """
        old_vm_model = Mock()
        old_vm_model.interfaces = {}
        self.database.get_vm_model_by_uuid.return_value = old_vm_model

        new_vm_model = self.vm_service.update(self.vmware_vm)

        self.assertEqual(old_vm_model, new_vm_model)
        self.esxi_api_client.add_filter.assert_not_called()
        self.database.save.assert_not_called()
        self.database.delete_vm_model.assert_called_once_with(old_vm_model.uuid)
        self.vnc_client.update_vm.assert_not_called()
        self.vnc_client.delete_vm.assert_called_once_with(old_vm_model.uuid)

    @staticmethod
    def _create_vmware_vm_mock(network):
        vmware_vm = Mock()
        vmware_vm.summary.runtime.host.vm = []
        vmware_vm.network = network
        device = Mock()
        backing_mock = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo())
        device.backing = backing_mock
        device.backing.port.portgroupKey = network[0].key
        device.macAddress = 'c8:5b:76:53:0f:f5'
        vmware_vm.config.hardware.device = [device]
        return vmware_vm

    @staticmethod
    def _create_dpg_mock(**kwargs):
        dpg_mock = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
        for kwarg in kwargs:
            setattr(dpg_mock, kwarg, kwargs[kwarg])
        return dpg_mock

    @staticmethod
    def _create_vcenter_client_mock():
        vcenter_client = Mock()
        vcenter_client.__enter__ = Mock()
        vcenter_client.__exit__ = Mock()
        vcenter_client.get_ip_pool_for_dpg.return_value = None
        return vcenter_client
