from unittest import TestCase

from mock import Mock
from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api import vnc_api

from cvm.database import Database
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)
from cvm.services import VirtualMachineInterfaceService, VirtualMachineService


def create_vmware_vm_mock(network):
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


def create_dpg_mock(**kwargs):
    dpg_mock = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
    for kwarg in kwargs:
        setattr(dpg_mock, kwarg, kwargs[kwarg])
    return dpg_mock


class TestVirtualMachineService(TestCase):

    def setUp(self):
        self.vmware_dpg = create_dpg_mock(name='VM Portgroup', key='dportgroup-50')
        self.vmware_vm = create_vmware_vm_mock([
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
    def _create_vcenter_client_mock():
        vcenter_client = Mock()
        vcenter_client.__enter__ = Mock()
        vcenter_client.__exit__ = Mock()
        vcenter_client.get_ip_pool_for_dpg.return_value = None
        return vcenter_client


class TestVirtualMachineInterface(TestCase):

    def setUp(self):
        self.database = Database()

        self.vnc_client = Mock()
        self.vnc_client.read_project.return_value = vnc_api.Project()

        self.vmi_service = VirtualMachineInterfaceService(self.vnc_client, self.database)

        self.vn_model = self._create_vn_model(name='VM Portgroup', key='dportgroup-50')
        self.database.save(self.vn_model)
        vmware_vm = create_vmware_vm_mock([self.vn_model.vmware_vn])

        self.vm_model = VirtualMachineModel(vmware_vm)

    def test_create_vmis_proper_vm_dpg(self):
        """ A new VMI is being created with proper VM/DPG pair. """
        other_vn_model = self._create_vn_model(name='DPortGroup', key='dportgroup-51')
        self.database.save(other_vn_model)

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(1, len(self.database.get_all_vmi_models()))
        saved_vmi = self.database.get_all_vmi_models()[0]
        self.assertEqual(self.vm_model, saved_vmi.vm_model)
        self.assertEqual(self.vn_model, saved_vmi.vn_model)
        self.vnc_client.update_vmi.assert_called_once_with(saved_vmi.to_vnc())
        self.assertTrue(saved_vmi.vrouter_port_added)

    def test_no_update_for_no_dpgs(self):
        """ No new VMIs are created for VM not connected to any DPG. """
        self.vm_model.interfaces = {}

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(0, len(self.database.get_all_vmi_models()))
        self.vnc_client.update_vmi.assert_not_called()

    def test_update_existing_vmi(self):
        """ Existing VMI is updated when VM changes the DPG to which it is connected. """
        second_vn_model = self._create_vn_model(name='DPortGroup', key='dportgroup-51')
        self.database.save(second_vn_model)
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        self.database.save(vmi_model)
        self.vm_model.interfaces['c8:5b:76:53:0f:f5'] = 'dportgroup-51'

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(1, len(self.database.get_all_vmi_models()))
        saved_vmi = self.database.get_all_vmi_models()[0]
        self.assertEqual(self.vm_model, saved_vmi.vm_model)
        self.assertEqual(second_vn_model, saved_vmi.vn_model)
        self.vnc_client.update_vmi.assert_called_once_with(saved_vmi.to_vnc())
        self.assertTrue(saved_vmi.vrouter_port_added)

    def test_removes_unused_vmis(self):
        """ VMIs are deleted when the VM is no longer connected to corresponding DPG. """
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        self.database.save(vmi_model)

        self.vm_model.interfaces = {}
        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertFalse(self.database.get_all_vmi_models())
        self.vnc_client.delete_vmi.assert_called_once_with(
            VirtualMachineInterfaceModel.get_uuid('c8:5b:76:53:0f:f5'))

    @staticmethod
    def _create_vn_model(name, key):
        vnc_vn = Mock()
        vnc_vn.name = name
        vmware_dpg = create_dpg_mock(name=name, key=key)
        return VirtualNetworkModel(vmware_dpg, vnc_vn, None)
