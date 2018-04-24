from unittest import TestCase

import uuid
from mock import Mock, patch
from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.vnc_api import Project, SecurityGroup

from cvm.models import (ID_PERMS, VirtualMachineInterfaceModel,
                        VirtualMachineModel, VirtualNetworkModel,
                        find_virtual_machine_ip_address)
from tests.test_services import create_vmware_vm_mock


class TestFindVirtualMachineIpAddress(TestCase):
    def setUp(self):
        self.vm = Mock()

    def test_standard_case(self):
        desired_portgroup, expected_ip = 'second', '10.7.0.60'
        self.vm.guest.net = [
            self._create_mock(
                network='first',
                ipAddress=['1.1.1.1', 'fe80::257:56ff:fe90:d265'],
            ),
            self._create_mock(
                network=desired_portgroup,
                ipAddress=['fe80::250:56ff:fe90:d265', expected_ip],
            ),
        ]

        result = find_virtual_machine_ip_address(self.vm, desired_portgroup)

        self.assertEqual(result, expected_ip)

    def test_unmatched_portgroup_name(self):
        desired_portgroup, expected_ip = 'non-existent', None
        self.vm.guest.net = [
            self._create_mock(
                network='first',
                ipAddress=['1.1.1.1', 'fe80::257:56ff:fe90:d265'],
            ),
            self._create_mock(
                network='second',
                ipAddress=['fe80::250:56ff:fe90:d265', expected_ip],

            ),
        ]

        result = find_virtual_machine_ip_address(self.vm, desired_portgroup)

        self.assertEqual(result, expected_ip)

    def test_unmatched_ip_type(self):
        desired_portgroup, expected_ip = 'second', None
        self.vm.guest.net = [
            self._create_mock(
                network='first',
                ipAddress=['1.1.1.1', 'fe80::257:56ff:fe90:d265'],
            ),
            self._create_mock(
                network=desired_portgroup,
                ipAddress=['fe80::250:56ff:fe90:d265'],
            ),
        ]

        result = find_virtual_machine_ip_address(self.vm, desired_portgroup)

        self.assertEqual(result, expected_ip)

    def test_missing_field(self):
        desired_portgroup, expected_ip = 'irrelevant', None
        self.vm.guest = None

        result = find_virtual_machine_ip_address(self.vm, desired_portgroup)

        self.assertEqual(result, expected_ip)

    def test_missing_field_in_network(self):
        desired_portgroup, expected_ip = 'second', '10.7.0.60'
        self.vm.guest.net = [
            None,
            self._create_mock(
                network=desired_portgroup,
                ipAddress=['fe80::250:56ff:fe90:d265', expected_ip],
            ),
        ]

        result = find_virtual_machine_ip_address(self.vm, desired_portgroup)

        self.assertEqual(result, expected_ip)

    @staticmethod
    def _create_mock(**kwargs):
        mock = Mock()
        for kwarg in kwargs:
            setattr(mock, kwarg, kwargs[kwarg])
        return mock


class TestVirtualMachineModel(TestCase):
    def setUp(self):
        self.vmware_vm, self.vm_properties = create_vmware_vm_mock()

    def test_init(self):
        vm_model = VirtualMachineModel(self.vmware_vm, self.vm_properties)

        self.assertEqual(self.vmware_vm, vm_model.vmware_vm)
        self.assertEqual('d376b6b4-943d-4599-862f-d852fd6ba425', vm_model.uuid)
        self.assertEqual('VM', vm_model.name)
        self.assertTrue(vm_model.is_powered_on)
        self.assertTrue(vm_model.tools_running)

    def test_to_vnc(self):
        vm_model = VirtualMachineModel(self.vmware_vm, self.vm_properties)
        vm_model.vm_properties['config.instanceUuid'] = 'd376b6b4-943d-4599-862f-d852fd6ba425'
        vm_model.vrouter_ip_address = '192.168.0.10'

        vnc_vm = vm_model.vnc_vm

        self.assertEqual(vnc_vm.name, vm_model.uuid)
        self.assertEqual(vnc_vm.uuid, vm_model.uuid)
        self.assertEqual(vnc_vm.display_name, vm_model.vrouter_ip_address)
        self.assertEqual(vnc_vm.fq_name, [vm_model.uuid])

    def test_update(self):
        vm_model = VirtualMachineModel(self.vmware_vm, self.vm_properties)
        vmware_vm = Mock()
        vmware_vm.summary.runtime.host = None
        vmware_vm.config.hardware.device = []
        new_properties = {
            'config.instanceUuid': '52073317-45b6-c3ee-596f-63dd49dd689e',
            'name': 'VM',
            'runtime.powerState': 'poweredOff',
            'guest.toolsRunningStatus': 'guestToolsNotRunning',
        }

        vm_model.update(vmware_vm, new_properties)

        self.assertEqual(vmware_vm, vm_model.vmware_vm)
        self.assertEqual('52073317-45b6-c3ee-596f-63dd49dd689e', vm_model.uuid)
        self.assertEqual('VM', vm_model.name)
        self.assertFalse(vm_model.is_powered_on)
        self.assertFalse(vm_model.tools_running)


class TestVirtualMachineInterfaceModel(TestCase):
    def setUp(self):
        self.project = Project()
        self.security_group = SecurityGroup()

        vmware_vm, vm_properties = create_vmware_vm_mock()
        device = Mock()
        device.backing.port.portgroupKey = '123'
        device.macAddress = 'c8:5b:76:53:0f:f5'
        vmware_vm.config.hardware.device = [device]
        self.vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        self.vm_model.vm_properties['config.instanceUuid'] = 'd376b6b4-943d-4599-862f-d852fd6ba425'
        self.vm_model.vrouter_ip_address = '192.168.0.10'

        vmware_vn = Mock()
        vnc_vn = Mock(uuid='d376b6b4-943d-4599-862f-d852fd6ba425')
        vnc_vn.name = 'VM Network'
        self.vn_model = VirtualNetworkModel(vmware_vn, vnc_vn, None)
        self.vn_model.key = '123'

    def test_to_vnc(self):
        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model, self.project, self.security_group)

        vnc_vmi = vmi_model.to_vnc()

        self.assertEqual(vnc_vmi.name, vmi_model.uuid)
        self.assertEqual(vnc_vmi.parent_name, self.project.name)
        self.assertEqual(vnc_vmi.display_name, vmi_model.display_name)
        self.assertEqual(vnc_vmi.uuid, vmi_model.uuid)
        self.assertEqual(vnc_vmi.virtual_machine_interface_mac_addresses.mac_address, [vmi_model.mac_address])
        self.assertEqual(vnc_vmi.get_id_perms(), ID_PERMS)

    @patch('cvm.models.find_vm_mac_address')
    @patch('cvm.models.VirtualMachineInterfaceModel.to_vnc')
    @patch('cvm.models.VirtualMachineInterfaceModel._find_ip_address')
    @patch('cvm.models.VirtualMachineInterfaceModel._should_construct_instance_ip')
    def test_construct_instance_ip(self, should_construct, ip_mock, to_vnc_mock, _):
        ip_mock.return_value = '192.168.1.100'
        should_construct.return_value = True
        to_vnc_mock.return_value.uuid = 'd376b6b4-943d-4599-862f-d852fd6ba425'

        vmi_model = VirtualMachineInterfaceModel(self.vm_model, self.vn_model, None, None)
        instance_ip = vmi_model.vnc_instance_ip

        self.assertEqual('192.168.1.100', instance_ip.instance_ip_address)
        self.assertEqual('d376b6b4-943d-4599-862f-d852fd6ba425',
                         instance_ip.virtual_machine_interface_refs[0]['uuid'])
        self.assertEqual(
            str(uuid.uuid3(uuid.NAMESPACE_DNS,
                           'ip-' + self.vn_model.name + '-' + self.vm_model.name)),
            instance_ip.uuid
        )


class TestVirtualNetworkModel(TestCase):
    def setUp(self):
        self.vmware_vn = Mock()

    def test_populate_vlans(self):
        entry_1 = self._create_pvlan_map_entry_mock('isolated', 2, 3)
        entry_2 = self._create_pvlan_map_entry_mock('promiscuous', 2, 3)
        entry_3 = self._create_pvlan_map_entry_mock('isolated', 3, 4)
        self.vmware_vn.config.distributedVirtualSwitch.config.pvlanConfig = [entry_1, entry_2, entry_3]
        self.vmware_vn.config.defaultPortConfig = self._create_pvlan_port_config_mock(3)

        vn_model = VirtualNetworkModel(self.vmware_vn, None, None)

        self.assertEqual(vn_model.isolated_vlan_id, 3)
        self.assertEqual(vn_model.primary_vlan_id, 2)

    def test_populate_vlans_no_p_found(self):
        """ No primary vlan corresponding to isolated vlan in vlan map. """
        entry = self._create_pvlan_map_entry_mock('isolated', 4, 5)
        self.vmware_vn.config.distributedVirtualSwitch.config.pvlanConfig = [entry]
        self.vmware_vn.config.defaultPortConfig = self._create_pvlan_port_config_mock(3)

        vn_model = VirtualNetworkModel(self.vmware_vn, None, None)

        self.assertEqual(vn_model.isolated_vlan_id, 3)
        self.assertEqual(vn_model.primary_vlan_id, None)

    def test_populate_vlans_not_p(self):
        """
        default_port_config.vlan is instance of
        vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec.
        VlanType = VLAN.
        """
        self.vmware_vn.config.defaultPortConfig = self._create_vlan_port_config_mock(3)

        vn_model = VirtualNetworkModel(self.vmware_vn, None, None)

        self.assertEqual(vn_model.isolated_vlan_id, 3)
        self.assertEqual(vn_model.primary_vlan_id, 3)

    def test_populate_vlans_inv_spec(self):
        """ Sometimes vlan_spec is of invalid type, e.g. TrunkVlanSpec. """
        self.vmware_vn.config.defaultPortConfig.vlan = Mock(spec=vim.dvs.VmwareDistributedVirtualSwitch.TrunkVlanSpec)

        vn_model = VirtualNetworkModel(self.vmware_vn, None, None)

        self.assertIsNone(vn_model.primary_vlan_id)
        self.assertIsNone(vn_model.isolated_vlan_id)

    def test_populate_vlans_no_map(self):
        """ Private vlan not configured on dvSwitch. """
        self.vmware_vn.config.distributedVirtualSwitch.config.pvlanConfig = None

        vn_model = VirtualNetworkModel(self.vmware_vn, None, None)

        self.assertIsNone(vn_model.primary_vlan_id)
        self.assertIsNone(vn_model.isolated_vlan_id)

    def test_populate_vlans_no_spec(self):
        """
        vn_model.default_port_config has no vlan field.
        Invalid port setting.
        """
        entry = self._create_pvlan_map_entry_mock('isolated', 2, 3)
        self.vmware_vn.config.distributedVirtualSwitch.config.pvlanConfig = [entry]
        self.vmware_vn.config.defaultPortConfig = None

        vn_model = VirtualNetworkModel(self.vmware_vn, None, None)

        self.assertIsNone(vn_model.primary_vlan_id)
        self.assertIsNone(vn_model.isolated_vlan_id)

    @staticmethod
    def _create_pvlan_port_config_mock(pvlan_id):
        default_port_config = Mock()
        default_port_config.vlan = Mock(spec=vim.dvs.VmwareDistributedVirtualSwitch.PvlanSpec)
        default_port_config.vlan.pvlanId = pvlan_id
        return default_port_config

    @staticmethod
    def _create_vlan_port_config_mock(vlan_id):
        default_port_config = Mock()
        default_port_config.vlan = Mock(spec=vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec)
        default_port_config.vlan.vlanId = vlan_id
        return default_port_config

    @staticmethod
    def _create_pvlan_map_entry_mock(pvlan_type, primary_id, secondary_id):
        entry = Mock()
        entry.pvlanType = pvlan_type
        entry.primaryVlanId = primary_id
        entry.secondaryVlanId = secondary_id
        return entry
