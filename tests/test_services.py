from unittest import TestCase

from mock import Mock, patch
from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api import vnc_api
from vnc_api.gen.resource_xsd import KeyValuePair, KeyValuePairs

from cvm.clients import VNCAPIClient
from cvm.constants import (VM_UPDATE_FILTERS, VNC_ROOT_DOMAIN,
                           VNC_VCENTER_DEFAULT_SG, VNC_VCENTER_IPAM,
                           VNC_VCENTER_PROJECT)
from cvm.database import Database
from cvm.models import (VCenterPort, VirtualMachineInterfaceModel,
                        VirtualMachineModel, VlanIdPool)
from cvm.services import (Service, VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService,
                          VRouterPortService, is_contrail_vm_name)
from tests.utils import (create_dpg_mock, create_property_filter,
                         create_vcenter_client_mock, create_vmware_vm_mock,
                         create_vn_model, create_vnc_client_mock,
                         reserve_vlan_ids)


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
        self.vm_service.update(self.vmware_vm)

        vm_model = self.database.save.call_args[0][0]
        self.assertIsNotNone(vm_model)
        self.assertEqual(self.vm_properties, vm_model.vm_properties)
        self.assertEqual(self.vmware_vm.config.hardware.device, vm_model.devices)
        self.assertEqual({'c8:5b:76:53:0f:f5': 'dportgroup-50'},
                         {vm_model.ports[0].mac_address: vm_model.ports[0].portgroup_key})
        self.vnc_client.update_or_create_vm.assert_called_once()
        self.database.save.assert_called_once_with(vm_model)

    def test_create_property_filter(self):
        property_filter = create_property_filter(
            self.vmware_vm,
            VM_UPDATE_FILTERS
        )
        self.esxi_api_client.add_filter.return_value = property_filter

        self.vm_service.update(self.vmware_vm)

        self.esxi_api_client.add_filter.assert_called_once_with(
            self.vmware_vm, VM_UPDATE_FILTERS
        )
        vm_model = self.database.save.call_args[0][0]
        self.assertEqual(property_filter, vm_model.property_filter)

    def test_destroy_property_filter(self):
        vm_model = Mock()
        self.database.get_vm_model_by_name.return_value = vm_model

        with patch('cvm.services.VirtualMachineService._can_modify_in_vnc') as can_modify:
            can_modify.return_value = True
            self.vm_service.remove_vm('VM')

        vm_model.destroy_property_filter.assert_called_once()

    def test_update_existing_vm(self):
        old_vm_model = Mock(vmi_models=[])
        self.database.get_vm_model_by_uuid.return_value = old_vm_model

        self.vm_service.update(self.vmware_vm)

        new_vm_model = self.database.save.call_args[0][0]
        self.assertEqual(old_vm_model, new_vm_model)
        old_vm_model.update.assert_called_once_with(self.vmware_vm, self.vm_properties)
        self.vnc_client.update_or_create_vm.assert_not_called()

    def test_sync_vms(self):
        self.esxi_api_client.get_all_vms.return_value = [self.vmware_vm]
        self.vnc_client.get_all_vms.return_value = []

        self.vm_service.get_vms_from_vmware()

        self.database.save.assert_called_once()
        self.vnc_client.update_or_create_vm.assert_called_once()
        self.assertEqual(self.vmware_vm.config.hardware.device,
                         self.database.save.call_args[0][0].devices)

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

        with patch('cvm.services.VirtualMachineService._can_modify_in_vnc') as can_modify:
            can_modify.return_value = True
            self.vm_service.delete_unused_vms_in_vnc()

        self.vnc_client.delete_vm.assert_called_once_with('d376b6b4-943d-4599-862f-d852fd6ba425')

    def test_remove_vm(self):
        vm_model = Mock(uuid='d376b6b4-943d-4599-862f-d852fd6ba425')
        vm_model.vnc_vm.uuid = 'd376b6b4-943d-4599-862f-d852fd6ba425'
        self.database.get_vm_model_by_name.return_value = vm_model

        with patch('cvm.services.VirtualMachineService._can_modify_in_vnc') as can_modify:
            can_modify.return_value = True
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
        vmware_vm, vm_properties = create_vmware_vm_mock(uuid='vm-uuid')
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        vmi_model = Mock(uuid='vmi-uuid')
        vm_model.vmi_models = [vmi_model]
        self.database.get_vm_model_by_uuid.return_value = vm_model
        self.database.ports_to_update = []

        self.vm_service.update_vmware_tools_status(vmware_vm, 'guestToolsNotRunning')

        self.assertFalse(vm_model.tools_running)
        self.database.save.assert_called_once_with(vm_model)

    def test_set_same_tools_status(self):
        vmware_vm, vm_properties = create_vmware_vm_mock(uuid='vm-uuid')
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        vmi_model = Mock(uuid='vmi-uuid')
        vm_model.vmi_models = [vmi_model]
        self.database.get_vm_model_by_uuid.return_value = vm_model
        self.database.ports_to_update = []

        self.vm_service.update_vmware_tools_status(vmware_vm, 'guestToolsRunning')

        self.assertTrue(vm_model.tools_running)
        self.database.save.assert_not_called()

    def test_rename_vm(self):
        vm_model = Mock()
        vm_model.configure_mock(name='VM')
        self.database.get_vm_model_by_name.return_value = vm_model
        vmware_vm = Mock()
        vmware_vm.configure_mock(name='VM-renamed')

        with patch('cvm.services.VirtualMachineService._can_modify_in_vnc') as can_modify:
            can_modify.return_value = True
            self.vm_service.rename_vm('VM', 'VM-renamed')

        vm_model.rename.assert_called_once_with('VM-renamed')
        self.vnc_client.update_or_create_vm.assert_called_once()
        self.database.save.assert_called_once_with(vm_model)

    def test_update_power_state(self):
        vmware_vm, vm_properties = create_vmware_vm_mock(uuid='vm-uuid')
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        vmi_model = Mock(uuid='vmi-uuid')
        vm_model.vmi_models = [vmi_model]
        self.database.get_vm_model_by_uuid.return_value = vm_model
        self.database.ports_to_update = []

        self.vm_service.update_power_state(vmware_vm, 'poweredOff')

        self.assertFalse(vm_model.is_powered_on)
        self.assertEqual([vmi_model], self.database.ports_to_update)

    def test_update_same_power_state(self):
        vmware_vm, vm_properties = create_vmware_vm_mock(uuid='vm-uuid')
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        vmi_model = Mock(uuid='vmi-uuid')
        vm_model.vmi_models = [vmi_model]
        self.database.get_vm_model_by_uuid.return_value = vm_model
        self.database.ports_to_update = []

        self.vm_service.update_power_state(vmware_vm, 'poweredOn')

        self.database.save.assert_not_called()
        self.assertTrue(vm_model.is_powered_on)
        self.assertEqual([], self.database.ports_to_update)


class TestVirtualNetworkService(TestCase):

    def setUp(self):
        self.database = Database()
        self.vnc_client = create_vnc_client_mock()
        self.vcenter_client = create_vcenter_client_mock()
        self.vn_service = VirtualNetworkService(self.vcenter_client,
                                                self.vnc_client, self.database)

    def test_update_vns_no_vns(self):
        self.database.vmis_to_update = []

        self.vn_service.update_vns()

        self.assertEqual({}, self.database.vn_models)
        self.vcenter_client.get_dpg_by_key.assert_not_called()
        self.vnc_client.read_vn.assert_not_called()

    def test_update_vns(self):
        vmi_model = Mock()
        vmi_model.vcenter_port.portgroup_key = 'dvportgroup-62'
        self.database.vmis_to_update = [vmi_model]

        dpg_mock = create_dpg_mock(key='dvportgroup-62', name='network_name')
        self.vcenter_client.get_dpg_by_key.return_value = dpg_mock

        vnc_vn_mock = Mock()
        self.vnc_client.read_vn.return_value = vnc_vn_mock

        self.vn_service.update_vns()

        vn_model = self.database.get_vn_model_by_key('dvportgroup-62')
        assert vn_model is not None
        assert vn_model.vnc_vn == vnc_vn_mock
        assert vn_model.vmware_vn == dpg_mock
        assert vn_model.key == 'dvportgroup-62'

        self.vcenter_client.get_dpg_by_key.called_once_with('dvportgroup-62')
        self.vcenter_client.enable_vlan_override.called_once_with(dpg_mock)

        fq_name = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, 'network_name']
        self.vnc_client.read_vn.called_once_with(fq_name)


class TestVirtualMachineInterfaceService(TestCase):

    def setUp(self):
        self.database = Database()

        self.vnc_client = create_vnc_client_mock()

        self.vmi_service = VirtualMachineInterfaceService(
            create_vcenter_client_mock(),
            self.vnc_client,
            self.database,
            vlan_id_pool=Mock()
        )

        self.vn_model = create_vn_model(name='VM Portgroup', key='dportgroup-50')
        self.database.save(self.vn_model)
        vmware_vm, vm_properties = create_vmware_vm_mock([self.vn_model.vmware_vn])
        self.vm_model = VirtualMachineModel(vmware_vm, vm_properties)

    def test_create_vmis_proper_vm_dpg(self):
        """ A new VMI is being created with proper VM/DPG pair. """
        self.database.save(self.vm_model)
        self.database.vmis_to_update.append(self.vm_model.vmi_models[0])
        other_vn_model = create_vn_model(name='DPortGroup', key='dportgroup-51', uuid='uuid_2')
        self.database.save(other_vn_model)

        self.vmi_service.update_vmis()

        self.assertEqual(1, len(self.database.get_all_vmi_models()))
        saved_vmi = self.database.get_all_vmi_models()[0]
        self.assertEqual(self.vm_model, saved_vmi.vm_model)
        self.assertEqual(self.vn_model, saved_vmi.vn_model)
        self.assertIn(saved_vmi, self.database.ports_to_update)
        vnc_vmi = self.vnc_client.update_vmi.call_args[0][0]
        self.assertIn(self.vn_model.uuid, [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()])

    def test_no_update_for_no_dpgs(self):
        """ No new VMIs are created for VM not connected to any DPG. """
        self.vm_model.ports = {}
        self.vm_model.vmi_models = []
        self.database.save(self.vm_model)

        self.vmi_service.update_vmis()

        self.assertEqual(0, len(self.database.get_all_vmi_models()))
        self.vnc_client.update_vmi.assert_not_called()
        self.assertEqual([], self.database.ports_to_update)

    def test_update_existing_vmi(self):
        """ Existing VMI is updated when VM changes the DPG to which it is connected. """
        self.database.save(self.vm_model)
        second_vn_model = create_vn_model(name='DPortGroup', key='dportgroup-51')
        self.database.save(second_vn_model)
        device = Mock(macAddress='c8:5b:76:53:0f:f5')
        device.backing.port.portgroupKey = 'dportgroup-50'
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 VCenterPort(device))
        vmi_model.parent = vnc_api.Project()
        vmi_model.security_group = vnc_api.SecurityGroup()
        vnc_instance_ip = Mock()
        vnc_instance_ip.uuid = 'uuid'
        vmi_model.vnc_instance_ip = vnc_instance_ip
        self.database.save(vmi_model)
        device.backing.port.portgroupKey = 'dportgroup-51'
        self.vm_model.ports[0] = VCenterPort(device)
        self.vm_model.vmi_models[0] = VirtualMachineInterfaceModel(
            self.vm_model, None, self.vm_model.ports[0]
        )
        self.database.vmis_to_update.append(self.vm_model.vmi_models[0])

        self.vmi_service.update_vmis()

        self.assertEqual(1, len(self.database.get_all_vmi_models()))
        saved_vmi = self.database.get_all_vmi_models()[0]
        self.assertEqual(self.vm_model, saved_vmi.vm_model)
        self.assertEqual(second_vn_model, saved_vmi.vn_model)
        vnc_vmi = self.vnc_client.update_vmi.call_args[0][0]
        self.assertIn(second_vn_model.uuid, [ref['uuid'] for ref in vnc_vmi.get_virtual_network_refs()])
        self.assertIn(saved_vmi, self.database.ports_to_update)

    def test_sync_vmis(self):
        self.database.save(self.vm_model)
        self.database.save(Mock(vn_model=self.vn_model))
        self.database.vmis_to_update.append(self.vm_model.vmi_models[0])
        self.vnc_client.get_vmis_by_project.return_value = []

        self.vmi_service.sync_vmis()

        self.assertEqual(1, len(self.database.get_all_vmi_models()))

    def test_syncs_one_vmi_once(self):
        self.database.save(self.vm_model)
        self.database.vmis_to_update.append(self.vm_model.vmi_models[0])
        self.vnc_client.get_vmis_by_project.return_value = []

        with patch.object(self.database, 'save') as database_save_mock:
            self.vmi_service.sync_vmis()

        database_save_mock.assert_called_once()

    def test_sync_no_vmis(self):
        self.vnc_client.get_vmis_by_project.return_value = []

        self.vmi_service.sync_vmis()

        self.assertEqual(0, len(self.database.get_all_vmi_models()))

    def test_sync_deletes_unused_vmis(self):
        vnc_vmi = Mock()
        vnc_vmi.get_uuid.return_value = 'vmi-uuid'
        self.vnc_client.get_vmis_by_project.return_value = [vnc_vmi]

        with patch('cvm.services.VirtualMachineInterfaceService._can_modify_in_vnc') as can_modify:
            can_modify.return_value = True
            self.vmi_service.sync_vmis()

        self.vnc_client.delete_vmi.assert_called_once()
        self.assertEqual('vmi-uuid', self.database.ports_to_delete[0])

    def test_remove_vmis_for_vm_model(self):
        device = Mock(macAddress='mac_addr')
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model, VCenterPort(device))
        self.vmi_service._add_vnc_info_to(vmi_model)
        vmi_model.vnc_instance_ip = Mock()
        self.database.save(vmi_model)
        self.database.save(self.vm_model)

        with patch('cvm.services.VirtualMachineInterfaceService._can_modify_in_vnc') as can_modify:
            can_modify.return_value = True
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
                                                 VCenterPort(Mock(macAddress='mac_addr')))
        vmi_model.parent = vnc_api.Project()
        vmi_model.security_group = vnc_api.SecurityGroup()
        self.database.save(vmi_model)
        self.vm_model.update(*create_vmware_vm_mock(name='VM-renamed'))
        self.database.save(self.vm_model)

        with patch('cvm.services.VirtualMachineInterfaceService._can_modify_in_vnc') as can_modify:
            can_modify.return_value = True
            self.vmi_service.rename_vmis('VM-renamed')

        self.assertEqual('vmi-VM Portgroup-VM-renamed', vmi_model.display_name)
        self.assertEqual(0, self.vnc_client.create_and_read_instance_ip.call_count)
        self.vnc_client.update_vmi.assert_called_once()
        self.assertIn(vmi_model, self.database.ports_to_update)

    def test_update_nic(self):
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model,
                                                 VCenterPort(Mock(macAddress='mac_addr')))
        vmi_model.parent = vnc_api.Project()
        vmi_model.security_group = vnc_api.SecurityGroup()
        self.database.save(vmi_model)
        nic_info = Mock(macAddress='mac_addr', ipAddress=['192.168.100.5'])

        self.vmi_service.update_nic(nic_info)

        self.assertEqual('192.168.100.5', vmi_model.ip_address)


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
                                                          None, esxi_api_client=esxi_api_client)

    def test_vnc_vm_true(self):
        vnc_vm = vnc_api.VirtualMachine('VM', vnc_api.Project())
        vnc_vm.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_1')]))
        self.vnc_api_client.read_vm.return_value = vnc_vm

        result = self.vm_service._can_modify_in_vnc(vnc_vm)

        self.assertTrue(result)

    def test_vnc_vm_false(self):
        vnc_vm = vnc_api.VirtualMachine('VM', vnc_api.Project())
        vnc_vm.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_2')]))
        self.vnc_api_client.read_vm.return_value = vnc_vm

        result = self.vm_service._can_modify_in_vnc(vnc_vm)

        self.assertFalse(result)

    def test_vnc_vmi_true(self):
        vnc_vmi = vnc_api.VirtualMachineInterface('VMI', vnc_api.Project())
        vnc_vmi.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_1')]))
        self.vnc_api_client.read_vmi.return_value = vnc_vmi

        result = self.vmi_service._can_modify_in_vnc(vnc_vmi)

        self.assertTrue(result)

    def test_vnc_vmi_false(self):
        vnc_vmi = vnc_api.VirtualMachineInterface('VMI', vnc_api.Project())
        vnc_vmi.set_annotations(KeyValuePairs(
            [KeyValuePair('vrouter-uuid', 'vrouter_uuid_2')]))
        self.vnc_api_client.read_vmi.return_value = vnc_vmi

        result = self.vmi_service._can_modify_in_vnc(vnc_vmi)

        self.assertFalse(result)

    def test_no_annotations(self):
        vnc_vm = vnc_api.VirtualMachine('VM', vnc_api.Project())
        self.vnc_api_client.read_vm.return_value = vnc_vm

        result = self.vm_service._can_modify_in_vnc(vnc_vm)

        self.assertFalse(result)

    def test_no_vrouter_uuid(self):
        vnc_vm = vnc_api.VirtualMachine('VM', vnc_api.Project())
        vnc_vm.set_annotations(KeyValuePairs(
            [KeyValuePair('key', 'value')]))
        self.vnc_api_client.read_vm.return_value = vnc_vm

        result = self.vm_service._can_modify_in_vnc(vnc_vm)

        self.assertFalse(result)


def construct_vrouter_response():
    return {'author': '/usr/bin/contrail-vrouter-agent',
            'dns-server': '192.168.200.2',
            'gateway': '192.168.200.254',
            'id': 'fe71b44d-0654-36aa-9841-ab9b78d628c5',
            'instance-id': '502789bb-240a-841f-e24c-1564537218f7',
            'ip-address': '192.168.200.5',
            'ip6-address': '::',
            'mac-address': '00:50:56:bf:7d:a1',
            'plen': 24,
            'rx-vlan-id': 7,
            'system-name': 'fe71b44d-0654-36aa-9841-ab9b78d628c5',
            'time': '424716:04:42.065040',
            'tx-vlan-id': 7,
            'vhostuser-mode': 0,
            'vm-project-id': '00000000-0000-0000-0000-000000000000',
            'vn-id': 'f94fe52e-cf19-48dd-9697-8c2085e7cbee'}


def construct_vmi_model():
    vmi = Mock()
    vmi.uuid = 'fe71b44d-0654-36aa-9841-ab9b78d628c5'
    vmi.vm_model.uuid = '502789bb-240a-841f-e24c-1564537218f7'
    vmi.vn_model.uuid = 'f94fe52e-cf19-48dd-9697-8c2085e7cbee'
    vmi.vcenter_port.vlan_id = 7
    vmi.vnc_instance_ip.instance_ip_address = '192.168.200.5'
    vmi.ip_address = '192.168.200.5'
    return vmi


class TestPortNeedsUpdate(TestCase):
    def setUp(self):
        self.vrouter_api_client = Mock()
        self.port_service = VRouterPortService(self.vrouter_api_client, None)
        self.vmi_model = construct_vmi_model()

    def test_false(self):
        self.vrouter_api_client.read_port.return_value = construct_vrouter_response()

        result = self.port_service._port_needs_an_update(self.vmi_model)

        self.assertFalse(result)

    def test_true(self):
        self.vrouter_api_client.return_value = None

        result = self.port_service._port_needs_an_update(self.vmi_model)

        self.assertTrue(result)


class TestPortService(TestCase):
    def setUp(self):
        self.vrouter_api_client = Mock()
        self.database = Database()
        self.port_service = VRouterPortService(self.vrouter_api_client, self.database)

    def test_create_port(self):
        vmi_model = construct_vmi_model()
        self.database.ports_to_update.append(vmi_model)

        with patch('cvm.services.VRouterPortService._port_needs_an_update') as port_check:
            port_check.return_value = True
            self.port_service.sync_ports()

        self.vrouter_api_client.delete_port.assert_called_once_with('fe71b44d-0654-36aa-9841-ab9b78d628c5')
        self.vrouter_api_client.add_port.assert_called_once_with(vmi_model)
        self.vrouter_api_client.enable_port.assert_called_once_with('fe71b44d-0654-36aa-9841-ab9b78d628c5')

    def test_no_update(self):
        vmi_model = construct_vmi_model()
        self.database.ports_to_update.append(vmi_model)

        with patch('cvm.services.VRouterPortService._port_needs_an_update') as port_check:
            port_check.return_value = False
            self.port_service.sync_ports()

        self.vrouter_api_client.delete_port.assert_not_called()
        self.vrouter_api_client.add_port.assert_not_called()
        self.assertEqual([], self.database.ports_to_update)

    def test_delete_port(self):
        self.database.ports_to_delete.append('fe71b44d-0654-36aa-9841-ab9b78d628c5')

        self.port_service.sync_ports()

        self.vrouter_api_client.delete_port.assert_called_once_with('fe71b44d-0654-36aa-9841-ab9b78d628c5')

    def test_enable_port(self):
        vmi_model = construct_vmi_model()
        vmi_model.vm_model.update_power_state = True
        self.database.ports_to_update.append(vmi_model)

        with patch('cvm.services.VRouterPortService._port_needs_an_update') as port_check:
            port_check.return_value = False
            self.port_service.sync_ports()

        self.vrouter_api_client.enable_port.assert_called_once_with('fe71b44d-0654-36aa-9841-ab9b78d628c5')
        self.vrouter_api_client.disable_port.assert_not_called()

    def test_disable_port(self):
        vmi_model = construct_vmi_model()
        vmi_model.vm_model.is_powered_on = False
        self.database.ports_to_update.append(vmi_model)

        with patch('cvm.services.VRouterPortService._port_needs_an_update') as port_check:
            port_check.return_value = False
            self.port_service.sync_ports()

        self.vrouter_api_client.disable_port.assert_called_once_with('fe71b44d-0654-36aa-9841-ab9b78d628c5')
        self.vrouter_api_client.enable_port.assert_not_called()


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
        vmi_model = Mock()

        self.vmi_service._assign_vlan_id(vmi_model)

        vcenter_port = self.vcenter_api_client.set_vlan_id.call_args[0][0]
        self.assertEqual(2, vcenter_port.vlan_id)

    def test_retain_old_vlan_id(self):
        reserve_vlan_ids(self.vlan_id_pool, [20])
        self.vcenter_api_client.get_vlan_id.return_value = 20
        vmi_model = Mock()

        self.vmi_service._assign_vlan_id(vmi_model)

        self.assertEqual(20, vmi_model.vcenter_port.vlan_id)

    def test_restore_vlan_id(self):
        reserve_vlan_ids(self.vlan_id_pool, [20])
        vmi_model = Mock()
        vmi_model.vcenter_port.vlan_id = 20

        self.vmi_service._restore_vlan_id(vmi_model)

        self.vcenter_api_client.restore_vlan_id.assert_called_once_with(
            vmi_model.vcenter_port)
        self.assertIn(20, self.vlan_id_pool._available_ids)
