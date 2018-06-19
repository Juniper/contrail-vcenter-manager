from unittest import TestCase

from mock import Mock, patch
from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.gen.resource_xsd import KeyValuePair, KeyValuePairs

from cvm.clients import VNCAPIClient
from cvm.constants import (VNC_ROOT_DOMAIN, VNC_VCENTER_DEFAULT_SG,
                           VNC_VCENTER_IPAM, VNC_VCENTER_PROJECT)
from cvm.database import Database
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)
from cvm.services import (Service, VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService)
from tests.utils import (create_dpg_mock, create_property_filter,
                         create_vcenter_client_mock, create_vmware_vm_mock,
                         create_vn_model, create_vnc_client_mock)


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

        with patch('cvm.services.VirtualMachineService._can_delete_from_vnc') as can_delete:
            can_delete.return_value = True
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

        self.vm_service.get_vms_from_vmware()

        self.database.save.assert_called_once()
        self.vnc_client.update_or_create_vm.assert_called_once()
        self.assertEqual(self.vmware_vm, self.database.save.call_args[0][0].vmware_vm)

    def test_sync_no_vms(self):
        """ Syncing when there's no VMware VMs doesn't update anything. """
        self.esxi_api_client.get_all_vms.return_value = []
        self.vnc_client.get_all_vms.return_value = []

        self.vm_service.get_vms_from_vmware()

        self.database.save.assert_not_called()
        self.vnc_client.update_vm.assert_not_called()

    def test_delete_unused_vms(self):
        self.esxi_api_client.get_all_vms.return_value = []
        vnc_vm = vnc_api.VirtualMachine('d376b6b4-943d-4599-862f-d852fd6ba425')
        vnc_vm.set_uuid('d376b6b4-943d-4599-862f-d852fd6ba425')
        self.vnc_client.get_all_vms.return_value = [vnc_vm]

        with patch('cvm.services.VirtualMachineService._can_delete_from_vnc') as can_delete:
            can_delete.return_value = True
            self.vm_service.delete_unused_vms_in_vnc()

        self.vnc_client.delete_vm.assert_called_once_with('d376b6b4-943d-4599-862f-d852fd6ba425')

    def test_remove_vm(self):
        vm_model = Mock(uuid='d376b6b4-943d-4599-862f-d852fd6ba425')
        vm_model.vnc_vm.uuid = 'd376b6b4-943d-4599-862f-d852fd6ba425'
        self.database.get_vm_model_by_name.return_value = vm_model

        with patch('cvm.services.VirtualMachineService._can_delete_from_vnc') as can_delete:
            can_delete.return_value = True
            self.vm_service.remove_vm('VM')

        self.database.delete_vm_model.assert_called_once_with(vm_model.uuid)
        self.vnc_client.delete_vm.assert_called_once_with('d376b6b4-943d-4599-862f-d852fd6ba425')

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

    def test_rename_vm(self):
        vm_model = Mock()
        vm_model.configure_mock(name='VM')
        self.database.get_vm_model_by_name.return_value = vm_model
        vmware_vm = Mock()
        vmware_vm.configure_mock(name='VM-renamed')

        self.vm_service.rename_vm('VM', 'VM-renamed')

        vm_model.rename.assert_called_once_with('VM-renamed')
        self.vnc_client.update_or_create_vm.assert_called_once()
        self.database.save.assert_called_once_with(vm_model)


class TestVirtualMachineInterfaceService(TestCase):

    def setUp(self):
        self.database = Database()

        self.vnc_client = create_vnc_client_mock()
        self.vrouter_api_client = Mock()

        self.vmi_service = VirtualMachineInterfaceService(
            create_vcenter_client_mock(),
            self.vnc_client,
            self.vrouter_api_client,
            self.database
        )

        self.vn_model = create_vn_model(name='VM Portgroup', key='dportgroup-50')
        self.database.save(self.vn_model)
        vmware_vm, vm_properties = create_vmware_vm_mock([self.vn_model.vmware_vn])
        self.vm_model = VirtualMachineModel(vmware_vm, vm_properties)

    def test_create_vmis_proper_vm_dpg(self):
        """ A new VMI is being created with proper VM/DPG pair. """
        self.database.save(self.vm_model)
        other_vn_model = create_vn_model(name='DPortGroup', key='dportgroup-51', uuid='uuid_2')
        self.database.save(other_vn_model)

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(1, len(self.database.get_all_vmi_models()))
        saved_vmi = self.database.get_all_vmi_models()[0]
        self.assertEqual(self.vm_model, saved_vmi.vm_model)
        self.assertEqual(self.vn_model, saved_vmi.vn_model)
        self.vrouter_api_client.add_port.assert_called_once_with(saved_vmi)
        self.vrouter_api_client.enable_port.assert_called_once_with(saved_vmi.uuid)
        vnc_vmi = self.vnc_client.update_or_create_vmi.call_args[0][0]
        self.assertIn(self.vn_model.uuid, [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()])
        self.assertTrue(saved_vmi.vrouter_port_added)

    def test_no_update_for_no_dpgs(self):
        """ No new VMIs are created for VM not connected to any DPG. """
        self.vm_model.interfaces = {}

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(0, len(self.database.get_all_vmi_models()))
        self.vnc_client.update_or_create_vmi.assert_not_called()
        self.vrouter_api_client.add_port.assert_not_called()

    def test_update_existing_vmi(self):
        """ Existing VMI is updated when VM changes the DPG to which it is connected. """
        second_vn_model = create_vn_model(name='DPortGroup', key='dportgroup-51')
        self.database.save(second_vn_model)
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        vnc_instance_ip = Mock()
        vnc_instance_ip.uuid = 'uuid'
        vmi_model.vnc_instance_ip = vnc_instance_ip
        vmi_model.vrouter_port_added = True
        self.database.save(vmi_model)
        self.vm_model.interfaces['c8:5b:76:53:0f:f5'] = 'dportgroup-51'
        self.vm_model.vmware_vm.config.hardware.device[0].backing.port.portgroupKey = 'dportgroup-51'

        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertEqual(1, len(self.database.get_all_vmi_models()))
        saved_vmi = self.database.get_all_vmi_models()[0]
        self.assertEqual(self.vm_model, saved_vmi.vm_model)
        self.assertEqual(second_vn_model, saved_vmi.vn_model)
        vnc_vmi = self.vnc_client.update_or_create_vmi.call_args[0][0]
        self.assertIn(second_vn_model.uuid, [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()])
        self.assertTrue(saved_vmi.vrouter_port_added)
        self.vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)
        self.vrouter_api_client.add_port.assert_called_once()
        self.vrouter_api_client.enable_port.assert_called_once_with(saved_vmi.uuid)

    def test_removes_unused_vmis(self):
        """ VMIs are deleted when the VM is no longer connected to corresponding DPG. """
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        vmi_model.vnc_instance_ip = Mock()
        vmi_model.vrouter_port_added = True
        self.database.save(vmi_model)

        self.vm_model.interfaces = {}
        self.vmi_service.update_vmis_for_vm_model(self.vm_model)

        self.assertFalse(self.database.get_all_vmi_models())
        self.vnc_client.delete_vmi.assert_called_once_with(
            VirtualMachineInterfaceModel.get_uuid('c8:5b:76:53:0f:f5'))
        self.vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)

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

        with patch('cvm.services.VirtualMachineInterfaceService._can_delete_from_vnc') as can_delete:
            can_delete.return_value = True
            self.vmi_service.sync_vmis()

        self.vnc_client.delete_vmi.assert_called_once()

    def test_remove_vmis_for_vm_model(self):
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        vmi_model.vnc_instance_ip = Mock()
        self.database.save(vmi_model)
        self.database.save(self.vm_model)

        with patch('cvm.services.VirtualMachineInterfaceService._can_delete_from_vnc') as can_delete:
            can_delete.return_value = True
            self.vmi_service.remove_vmis_for_vm_model(self.vm_model.name)

        self.assertNotIn(vmi_model, self.database.get_all_vmi_models())
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

    def test_rename_vmis(self):
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 vnc_api.Project(), vnc_api.SecurityGroup())
        vmi_model.vrouter_port_added = True
        self.database.save(vmi_model)
        self.vm_model.update(*create_vmware_vm_mock(name='VM-renamed'))
        self.database.save(self.vm_model)

        self.vmi_service.rename_vmis('VM-renamed')

        self.assertEqual('vmi-VM Portgroup-VM-renamed', vmi_model.display_name)
        self.assertEqual(0, self.vnc_client.create_and_read_instance_ip.call_count)
        self.vnc_client.update_or_create_vmi.assert_called_once()
        self.vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)
        self.vrouter_api_client.add_port.assert_called_once_with(vmi_model)
        self.vrouter_api_client.enable_port.assert_called_once_with(vmi_model.uuid)


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
        self.vmi_service = VirtualMachineInterfaceService(
            create_vcenter_client_mock(),
            self.vnc_client,
            Mock(),
            self.database
        )

    def test_update_vmi(self):
        self.vmi_service._create_or_update(self.vmi_model)

        self.vnc_client.create_and_read_instance_ip.assert_called_once_with(self.instance_ip)


class TestVNCEnvironmentSetup(TestCase):
    def setUp(self):
        with patch('cvm.clients.vnc_api.VncApi') as vnc_api_mock:
            self.vnc_lib = vnc_api_mock.return_value
            self.vnc_client = VNCAPIClient({})

    def test_read_project(self):
        self.vnc_lib.project_read.return_value = vnc_api.Project(
            name=VNC_VCENTER_PROJECT,
            parent_obj=vnc_api.Domain(name=VNC_ROOT_DOMAIN)
        )

        service = Service(self.vnc_client, None)
        project = service._project

        self.assertEqual(VNC_VCENTER_PROJECT, project.name)
        self.assertEqual([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT], project.fq_name)

    def test_read_no_project(self):
        self.vnc_lib.project_read.side_effect = vnc_api.NoIdError(0)

        service = Service(self.vnc_client, None)
        project = service._project

        self.vnc_lib.project_create.assert_called_once()
        self.assertEqual(VNC_VCENTER_PROJECT, project.name)
        self.assertEqual([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT], project.fq_name)

    def test_read_security_group(self):
        self.vnc_lib.security_group_create.side_effect = vnc_api.RefsExistError()
        self.vnc_lib.security_group_read.return_value = vnc_api.SecurityGroup(
            name=VNC_VCENTER_DEFAULT_SG,
            parent_obj=vnc_api.Project(
                name=VNC_VCENTER_PROJECT,
                parent_obj=vnc_api.Domain(name=VNC_ROOT_DOMAIN)
            )
        )

        service = Service(self.vnc_client, None)
        security_group = service._default_security_group

        self.assertEqual(VNC_VCENTER_DEFAULT_SG, security_group.name)
        self.assertEqual(
            [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_DEFAULT_SG],
            security_group.fq_name
        )

    def test_read_no_security_group(self):
        self.vnc_lib.security_group_read.side_effect = vnc_api.NoIdError(0)
        self.vnc_lib.project_read.return_value = vnc_api.Project(
            name=VNC_VCENTER_PROJECT,
            parent_obj=vnc_api.Domain(name=VNC_ROOT_DOMAIN)
        )

        service = Service(self.vnc_client, None)
        security_group = service._default_security_group

        self.vnc_lib.security_group_create.assert_called_once()
        self.assertEqual(VNC_VCENTER_DEFAULT_SG, security_group.name)
        self.assertEqual(
            [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_DEFAULT_SG],
            security_group.fq_name
        )

    def test_read_ipam(self):
        self.vnc_lib.network_ipam_create.side_effect = vnc_api.RefsExistError()
        self.vnc_lib.network_ipam_read.return_value = vnc_api.SecurityGroup(
            name=VNC_VCENTER_IPAM,
            parent_obj=vnc_api.Project(
                name=VNC_VCENTER_PROJECT,
                parent_obj=vnc_api.Domain(name=VNC_ROOT_DOMAIN)
            )
        )

        service = Service(self.vnc_client, None)
        ipam = service._ipam

        self.assertEqual(VNC_VCENTER_IPAM, ipam.name)
        self.assertEqual(
            [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_IPAM],
            ipam.fq_name
        )

    def test_read_no_ipam(self):
        self.vnc_lib.network_ipam_read.side_effect = vnc_api.NoIdError(0)
        self.vnc_lib.project_read.return_value = vnc_api.Project(
            name=VNC_VCENTER_PROJECT,
            parent_obj=vnc_api.Domain(name=VNC_ROOT_DOMAIN)
        )

        service = Service(self.vnc_client, None)
        ipam = service._ipam

        self.vnc_lib.network_ipam_create.assert_called_once()
        self.assertEqual(VNC_VCENTER_IPAM, ipam.name)
        self.assertEqual(
            [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_IPAM],
            ipam.fq_name
        )


class TestCanDeleteFromVnc(TestCase):
    def setUp(self):
        self.vnc_api_client = Mock()
        esxi_api_client = Mock()
        esxi_api_client.read_vrouter_uuid.return_value = 'vrouter_uuid_1'
        self.vm_service = VirtualMachineService(esxi_api_client, self.vnc_api_client, None)
        self.vmi_service = VirtualMachineInterfaceService(esxi_api_client, self.vnc_api_client,
                                                          None, None, esxi_api_client=esxi_api_client)

    def test_vnc_vm_true(self):
        vnc_vm = vnc_api.VirtualMachine('VM', vnc_api.Project())
        vnc_vm.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_1')]))
        self.vnc_api_client.read_vm.return_value = vnc_vm

        result = self.vm_service._can_delete_from_vnc(vnc_vm)

        self.assertTrue(result)

    def test_vnc_vm_false(self):
        vnc_vm = vnc_api.VirtualMachine('VM', vnc_api.Project())
        vnc_vm.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_2')]))
        self.vnc_api_client.read_vm.return_value = vnc_vm

        result = self.vm_service._can_delete_from_vnc(vnc_vm)

        self.assertFalse(result)

    def test_vnc_vmi_true(self):
        vnc_vmi = vnc_api.VirtualMachineInterface('VMI', vnc_api.Project())
        vnc_vmi.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_1')]))
        self.vnc_api_client.read_vmi.return_value = vnc_vmi

        result = self.vmi_service._can_delete_from_vnc(vnc_vmi)

        self.assertTrue(result)

    def test_vnc_vmi_false(self):
        vnc_vmi = vnc_api.VirtualMachineInterface('VMI', vnc_api.Project())
        vnc_vmi.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_2')]))
        self.vnc_api_client.read_vmi.return_value = vnc_vmi

        result = self.vmi_service._can_delete_from_vnc(vnc_vmi)

        self.assertFalse(result)
