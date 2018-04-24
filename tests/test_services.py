from unittest import TestCase, skip

from mock import Mock, patch
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api

from cvm.clients import make_filter_spec
from cvm.database import Database
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService)


def create_vmware_vm_mock(network=None):
    vmware_vm = Mock(spec=vim.VirtualMachine)
    vmware_vm.summary.runtime.host = Mock(vm=[vmware_vm])
    vmware_vm.config.hardware.device = []
    vm_properties = {
        'config.instanceUuid': 'd376b6b4-943d-4599-862f-d852fd6ba425',
        'name': 'VM',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }
    vmware_vm.network = network
    vmware_vm.guest.net = []
    if network:
        device = Mock()
        backing_mock = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo())
        device.backing = backing_mock
        device.backing.port.portgroupKey = network[0].key
        device.macAddress = 'c8:5b:76:53:0f:f5'
        vmware_vm.config.hardware.device = [device]
    return vmware_vm, vm_properties


def create_dpg_mock(**kwargs):
    dpg_mock = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
    for kwarg in kwargs:
        setattr(dpg_mock, kwarg, kwargs[kwarg])
    return dpg_mock


def create_vcenter_client_mock():
    vcenter_client = Mock()
    vcenter_client.__enter__ = Mock()
    vcenter_client.__exit__ = Mock()
    vcenter_client.get_ip_pool_for_dpg.return_value = None
    return vcenter_client


def create_vnc_client_mock():
    vnc_client = Mock()
    vnc_client.read_project.return_value = vnc_api.Project()
    vnc_client.read_security_group.return_value = vnc_api.SecurityGroup()
    return vnc_client


def create_property_filter(obj, filters):
    filter_spec = make_filter_spec(obj, filters)
    return vmodl.query.PropertyCollector.Filter(filter_spec)


class TestVirtualMachineService(TestCase):

    def setUp(self):
        vmware_dpg = create_dpg_mock(name='VM Portgroup', key='dportgroup-50')
        self.vmware_vm, self.vm_properties = create_vmware_vm_mock([
            vmware_dpg,
            Mock(spec=vim.Network),
        ])
        self.vnc_client = Mock()
        self.vcenter_client = create_vcenter_client_mock()
        self.database = Mock()
        self.database.get_vm_model_by_uuid.return_value = None
        self.esxi_api_client = Mock()
        self.esxi_api_client.read_vm_properties.return_value = self.vm_properties
        self.vm_service = VirtualMachineService(self.esxi_api_client, self.vnc_client, self.database)

    def test_update_new_vm(self):
        vm_model = self.vm_service.update(self.vmware_vm)

        self.assertIsNotNone(vm_model)
        self.assertEqual(self.vm_properties, vm_model.vm_properties)
        self.assertEqual(self.vmware_vm, vm_model.vmware_vm)
        self.assertEqual({'c8:5b:76:53:0f:f5': 'dportgroup-50'}, vm_model.interfaces)
        self.vnc_client.update_or_create_vm.assert_called_once_with(vm_model.vnc_vm)
        self.database.save.assert_called_once_with(vm_model)

    def test_create_property_filter(self):
        property_filter = create_property_filter(
            self.vmware_vm,
            ['guest.toolsRunningStatus', 'guest.net']
        )
        self.esxi_api_client.add_filter.return_value = property_filter

        vm_model = self.vm_service.update(self.vmware_vm)

        self.esxi_api_client.add_filter.assert_called_once_with(
            self.vmware_vm, ['guest.toolsRunningStatus', 'guest.net']
        )
        self.assertEqual(property_filter, vm_model.property_filter)

    def test_destroy_property_filter(self):
        vm_model = Mock()
        self.database.get_vm_model_by_name.return_value = vm_model

        self.vm_service.remove_vm('VM')

        vm_model.destroy_property_filter.assert_called_once()

    def test_update_existing_vm(self):
        old_vm_model = Mock()
        self.database.get_vm_model_by_uuid.return_value = old_vm_model

        new_vm_model = self.vm_service.update(self.vmware_vm)

        self.assertEqual(old_vm_model, new_vm_model)
        old_vm_model.update.assert_called_once_with(self.vmware_vm, self.vm_properties)
        self.vnc_client.update_vm.assert_not_called()

    def test_sync_vms(self):
        self.esxi_api_client.get_all_vms.return_value = [self.vmware_vm]
        self.vnc_client.get_all_vms.return_value = []

        self.vm_service.sync_vms()

        self.database.save.assert_called_once()
        self.vnc_client.update_or_create_vm.assert_called_once()
        self.assertEqual(self.vmware_vm, self.database.save.call_args[0][0].vmware_vm)

    def test_sync_no_vms(self):
        """ Syncing when there's no VMware VMs doesn't update anything. """
        self.esxi_api_client.get_all_vms.return_value = []
        self.vnc_client.get_all_vms.return_value = []

        self.vm_service.sync_vms()

        self.database.save.assert_not_called()
        self.vnc_client.update_vm.assert_not_called()

    @skip("Deleting is disabled for now")
    def test_delete_unused_vms(self):
        self.esxi_api_client.get_all_vms.return_value = []
        self.vnc_client.get_all_vms.return_value = [
            vnc_api.VirtualMachine('d376b6b4-943d-4599-862f-d852fd6ba425')]

        self.vm_service.sync_vms()

        self.database.save.assert_not_called()
        self.vnc_client.delete_vm.assert_called_once_with('d376b6b4-943d-4599-862f-d852fd6ba425')

    def test_remove_vm(self):
        vm_model = Mock(uuid='d376b6b4-943d-4599-862f-d852fd6ba425')
        self.database.get_vm_model_by_name.return_value = vm_model

        self.vm_service.remove_vm('VM')

        self.database.delete_vm_model.assert_called_once_with(vm_model.uuid)
        self.vnc_client.delete_vm.assert_called_once_with(vm_model.uuid)

    def test_remove_no_vm(self):
        """ Remove VM should do nothing when VM doesn't exist in database. """
        self.database.get_vm_model_by_name.return_value = None

        self.vm_service.remove_vm('VM')

        self.database.delete_vm_model.assert_not_called()
        self.vnc_client.delete_vm.assert_not_called()

    def test_set_tools_running_status(self):
        vm_model = Mock()
        self.database.get_vm_model_by_uuid.return_value = vm_model
        vmware_vm = Mock()
        value = 'guestToolsNotRunning'

        self.vm_service.set_tools_running_status(vmware_vm, value)

        self.assertEqual(value, vm_model.tools_running_status)
        self.database.save.assert_called_once_with(vm_model)


class TestVirtualMachineInterfaceService(TestCase):

    def setUp(self):
        self.database = Database()

        self.vnc_client = create_vnc_client_mock()

        self.vmi_service = VirtualMachineInterfaceService(self.vnc_client, self.database)

        self.vn_model = self._create_vn_model(name='VM Portgroup', key='dportgroup-50')
        self.database.save(self.vn_model)
        vmware_vm, vm_properties = create_vmware_vm_mock([self.vn_model.vmware_vn])
        self.vm_model = VirtualMachineModel(vmware_vm, vm_properties)

    def test_create_vmis_proper_vm_dpg(self):
        """ A new VMI is being created with proper VM/DPG pair. """
        other_vn_model = self._create_vn_model(name='DPortGroup', key='dportgroup-51')
        self.database.save(other_vn_model)

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(1, len(self.database.get_all_vmi_models()))
        saved_vmi = self.database.get_all_vmi_models()[0]
        self.assertEqual(self.vm_model, saved_vmi.vm_model)
        self.assertEqual(self.vn_model, saved_vmi.vn_model)
        self.vnc_client.update_or_create_vmi.assert_called_once_with(saved_vmi.to_vnc())
        self.assertTrue(saved_vmi.vrouter_port_added)

    def test_no_update_for_no_dpgs(self):
        """ No new VMIs are created for VM not connected to any DPG. """
        self.vm_model.interfaces = {}

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(0, len(self.database.get_all_vmi_models()))
        self.vnc_client.update_or_create_vmi.assert_not_called()

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
        self.vnc_client.update_or_create_vmi.assert_called_once_with(saved_vmi.to_vnc())
        self.assertTrue(saved_vmi.vrouter_port_added)

    def test_removes_unused_vmis(self):
        """ VMIs are deleted when the VM is no longer connected to corresponding DPG. """
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        vmi_model.vnc_instance_ip = Mock()
        self.database.save(vmi_model)

        self.vm_model.interfaces = {}
        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertFalse(self.database.get_all_vmi_models())
        self.vnc_client.delete_vmi.assert_called_once_with(
            VirtualMachineInterfaceModel.get_uuid('c8:5b:76:53:0f:f5'))

    def test_sync_vmis(self):
        self.database.save(self.vm_model)
        self.vnc_client.get_vmis_by_project.return_value = []

        self.vmi_service.sync_vmis()

        self.assertEqual(1, len(self.database.get_all_vmi_models()))

    def test_syncs_one_vmi_once(self):
        self.database.save(self.vm_model)
        self.vnc_client.get_vmis_by_project.return_value = []

        with patch.object(self.database, 'save') as database_save_mock:
            self.vmi_service.sync_vmis()

        database_save_mock.assert_called_once()

    def test_sync_no_vmis(self):
        self.vnc_client.get_vmis_by_project.return_value = []

        self.vmi_service.sync_vmis()

        self.assertEqual(0, len(self.database.get_all_vmi_models()))

    def test_sync_deletes_unused_vmis(self):
        self.vnc_client.get_vmis_by_project.return_value = [Mock()]

        self.vmi_service.sync_vmis()

        self.vnc_client.delete_vmi.assert_called_once()

    def test_remove_vmis_for_vm_model(self):
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        vmi_model.vnc_instance_ip = Mock()
        self.database.save(vmi_model)
        self.database.save(self.vm_model)

        with patch.object(self.database, 'delete_vmi_model') as database_del_mock:
            self.vmi_service.remove_vmis_for_vm_model(self.vm_model.name)

        database_del_mock.assert_called_once_with(vmi_model.uuid)
        self.vnc_client.delete_vmi.assert_called_once_with(vmi_model.uuid)

    def test_remove_vmis_no_vm_model(self):
        """
        When the passed VM Model is None, we can't retrieve its interfaces
        and therefore remove them.
        """
        with patch.object(self.database, 'delete_vmi_model') as database_del_mock:
            self.vmi_service.remove_vmis_for_vm_model('VM')

        database_del_mock.assert_not_called()
        self.vnc_client.delete_vmi.assert_not_called()

    @staticmethod
    def _create_vn_model(name, key):
        vnc_vn = Mock()
        vnc_vn.name = name
        vmware_dpg = create_dpg_mock(name=name, key=key)
        return VirtualNetworkModel(vmware_dpg, vnc_vn, None)


class TestVirtualNetworkService(TestCase):

    def setUp(self):
        self.vcenter_api_client = create_vcenter_client_mock()
        self.vnc_api_client = create_vnc_client_mock()
        self.database = Database()
        self.vn_service = VirtualNetworkService(self.vcenter_api_client,
                                                self.vnc_api_client, self.database)

    def test_sync_no_vns(self):
        """ Syncing when there's no VNC VNs doesn't save anything to the database. """
        self.vnc_api_client.get_all_vns.return_value = None

        self.vn_service.sync_vns()

        self.assertFalse(self.database.vn_models)

    def test_sync_vns(self):
        first_vnc_vn = vnc_api.VirtualNetwork('VM Portgroup')
        second_vnc_vn = vnc_api.VirtualNetwork(VirtualNetworkModel.get_uuid('DPortgroup'))
        self.vnc_api_client.get_vns_by_project.return_value = [first_vnc_vn, second_vnc_vn]

        first_vmware_dpg = create_dpg_mock(name='VM Portgroup', key='dportgroup-50')
        second_vmware_dpg = create_dpg_mock(name='DPortgroup', key='dportgroup-51')
        self.vcenter_api_client.get_dpg_by_name.side_effect = [first_vmware_dpg, second_vmware_dpg]

        self.vn_service.sync_vns()

        self.assertEqual(first_vnc_vn, self.database.get_vn_model_by_key('dportgroup-50').vnc_vn)
        self.assertEqual(second_vnc_vn, self.database.get_vn_model_by_key('dportgroup-51').vnc_vn)


class TestVMIInstanceIp(TestCase):
    def setUp(self):
        self.instance_ip = Mock()
        self.vmi_model = Mock()
        self.vmi_model.vnc_instance_ip = self.instance_ip
        self.database = Database()
        self.vnc_client = create_vnc_client_mock()
        self.vmi_service = VirtualMachineInterfaceService(self.vnc_client, self.database)

    def test_update_vmi(self):
        self.vmi_service._create_or_update(self.vmi_model)

        self.vnc_client.update_or_create_instance_ip.assert_called_once_with(self.instance_ip)

    def test_delete_vmi(self):
        self.instance_ip.uuid = '63f2594b-3c7d-4b8a-bb3d-cc6a098ad284'

        self.vmi_service._delete(self.vmi_model)

        self.vnc_client.delete_instance_ip.assert_called_once_with(self.instance_ip.uuid)