from unittest import TestCase

from mock import Mock, patch
from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api.exceptions import NoIdError

from cvm.clients import (ESXiAPIClient, VCenterAPIClient, VNCAPIClient,
                         make_dv_port_spec)
from tests.utils import create_vmware_vm_mock


class TestESXiAPIClient(TestCase):
    def setUp(self):
        with patch('cvm.clients.SmartConnectNoSSL') as self.si_mock:
            self.property_collector = Mock()
            self.si_mock.return_value.content.propertyCollector = self.property_collector
            self.esxi_client = ESXiAPIClient({})

        self.vmware_vm, _ = create_vmware_vm_mock()

    def test_read_vm(self):
        dynamic_property = Mock(val='VM')
        dynamic_property.configure_mock(name='name')
        object_content = Mock(obj=self.vmware_vm, propSet=[dynamic_property])
        self.property_collector.RetrievePropertiesEx.return_value.objects = [object_content]

        result = self.esxi_client.read_vm_properties(self.vmware_vm)

        self.assertEqual('VM', result.get('name'))


class TestVCenterAPIClient(TestCase):
    def setUp(self):
        self.vcenter_client = VCenterAPIClient({})
        self.dvs = Mock()

    def test_set_vlan_id(self):
        dv_port = Mock(key='8')
        dv_port.config.configVersion = '1'
        self.dvs.FetchDVPorts.return_value = [dv_port]
        vcenter_port = Mock(port_key='8', vlan_id=10)

        with patch('cvm.clients.SmartConnectNoSSL'):
            with self.vcenter_client:
                self.vcenter_client._dvs = self.dvs
                self.vcenter_client.set_vlan_id(vcenter_port)

        self.dvs.ReconfigureDVPort_Task.assert_called_once()
        spec = self.dvs.ReconfigureDVPort_Task.call_args[1].get('port', [None])[0]
        self.assertIsNotNone(spec)
        self.assertEqual('8', spec.key)
        self.assertEqual('1', spec.configVersion)
        self.assertEqual(10, spec.setting.vlan.vlanId)

    def test_enable_vlan_override(self):
        portgroup = Mock()
        portgroup.config.policy = Mock(spec=vim.dvs.DistributedVirtualPortgroup.PortgroupPolicy())
        portgroup.config.configVersion = '1'

        with patch('cvm.clients.SmartConnectNoSSL'):
            with self.vcenter_client:
                self.vcenter_client._dvs = self.dvs
                self.vcenter_client.enable_vlan_override(portgroup=portgroup)

        portgroup.ReconfigureDVPortgroup_Task.assert_called_once()
        config = portgroup.ReconfigureDVPortgroup_Task.call_args
        self.assertTrue(config.policy.vlanOverrideAllowed)
        self.assertEqual('1', config.configVersion)

    def test_get_vlan_id(self):
        dv_port = Mock(key='20')
        dv_port.config.setting.vlan.vlanId = 10
        dv_port.config.setting.vlan.inherited = False
        self.dvs.FetchDVPorts.return_value = [dv_port]
        vcenter_port = Mock(port_key='20')

        with patch('cvm.clients.SmartConnectNoSSL'):
            with self.vcenter_client:
                self.vcenter_client._dvs = self.dvs
                result = self.vcenter_client.get_vlan_id(vcenter_port)

        self.assertEqual(10, result)

    def test_restore_vlan_id(self):
        dv_port = Mock(key='8')
        dv_port.config.configVersion = '1'
        self.dvs.FetchDVPorts.return_value = [dv_port]
        vcenter_port = Mock(port_key='8', vlan_id=10)

        with patch('cvm.clients.SmartConnectNoSSL'):
            with self.vcenter_client:
                self.vcenter_client._dvs = self.dvs
                self.vcenter_client.restore_vlan_id(vcenter_port)

        self.dvs.ReconfigureDVPort_Task.assert_called_once()
        spec = self.dvs.ReconfigureDVPort_Task.call_args[1].get('port', [None])[0]
        self.assertIsNotNone(spec)
        self.assertEqual('8', spec.key)
        self.assertEqual('1', spec.configVersion)
        self.assertTrue(spec.setting.vlan.inherited)


class TestFunctions(TestCase):
    def test_make_dv_port_spec(self):
        dv_port = Mock(key='8')
        dv_port.config.configVersion = '1'
        spec = make_dv_port_spec(dv_port, 10)
        self.assertEqual('8', spec.key)
        self.assertEqual('edit', spec.operation)
        self.assertEqual(10, spec.setting.vlan.vlanId)
        self.assertFalse(spec.setting.vlan.inherited)
        self.assertEqual('1', spec.configVersion)

    def test_make_port_spec_restore(self):
        dv_port = Mock(key='8')
        dv_port.config.configVersion = '1'
        spec = make_dv_port_spec(dv_port)
        self.assertEqual('8', spec.key)
        self.assertEqual('edit', spec.operation)
        self.assertTrue(spec.setting.vlan.inherited)
        self.assertEqual('1', spec.configVersion)


class TestVNCAPIClient(TestCase):
    def setUp(self):
        self.vnc_lib = Mock()
        with patch('cvm.clients.vnc_api.VncApi') as vnc_api_mock:
            vnc_api_mock.return_value = self.vnc_lib
            self.vnc_client = VNCAPIClient({})

    def test_update_create_vm(self):
        vnc_vm = Mock()

        self.vnc_client.update_or_create_vm(vnc_vm)

        self.vnc_lib.virtual_machine_update.assert_called_once()

    def test_update_create_new_vm(self):
        vnc_vm = Mock()
        self.vnc_lib.virtual_machine_update.side_effect = NoIdError(None)

        self.vnc_client.update_or_create_vm(vnc_vm)

        self.vnc_lib.virtual_machine_create.called_once_with(vnc_vm)

    def test_update_create_vmi(self):
        vnc_vmi = Mock()
        self.vnc_lib.virtual_machine_interface_read.side_effect = NoIdError(None)

        self.vnc_client.update_vmi(vnc_vmi)

        self.vnc_lib.virtual_machine_interface_create.assert_called_once()

    def test_update_create_new_vmi(self):
        vnc_vmi = Mock()
        self.vnc_lib.virtual_machine_interface_read.side_effect = NoIdError(None)

        self.vnc_client.update_vmi(vnc_vmi)

        self.vnc_lib.virtual_machine_interface_create.assert_called_once_with(vnc_vmi)

    def test_get_all_vms(self):
        self.vnc_lib.virtual_machines_list.return_value = {
            u'virtual-machines': [{
                u'fq_name': [u'5027a82e-fbc7-0898-b64c-4bf9f5b9d07c'],
                u'href': u'http://10.100.0.84:8082/virtual-machine/5027a82e-fbc7-0898-b64c-4bf9f5b9d07c',
                u'uuid': u'5027a82e-fbc7-0898-b64c-4bf9f5b9d07c',
            }]
        }
        vnc_vm = Mock()
        self.vnc_lib.virtual_machine_read.return_value = vnc_vm

        all_vms = self.vnc_client.get_all_vms()

        self.vnc_lib.virtual_machine_read.assert_called_once_with(id=u'5027a82e-fbc7-0898-b64c-4bf9f5b9d07c')
        self.assertEqual([vnc_vm], all_vms)


class TestBackRefs(TestCase):
    """ Deleting objects should also delete it's back-ref objects. """

    def setUp(self):
        self.vnc_lib = Mock()
        with patch('cvm.clients.vnc_api.VncApi') as vnc_api_mock:
            vnc_api_mock.return_value = self.vnc_lib
            self.vnc_client = VNCAPIClient({})

    def test_delete_vmi(self):
        vmi = Mock(uuid='vmi_uuid')
        vmi.get_instance_ip_back_refs.return_value = [{'uuid': 'instance_ip_uuid'}]
        self.vnc_lib.virtual_machine_interface_read.return_value = vmi

        self.vnc_client.delete_vmi('vmi_uuid')

        self.vnc_lib.instance_ip_delete.assert_called_once_with(id='instance_ip_uuid')
        self.vnc_lib.virtual_machine_interface_delete.assert_called_once_with(id='vmi_uuid')

    def test_vmi_no_back_refs(self):
        vmi = Mock(uuid='vmi_uuid')
        vmi.get_instance_ip_back_refs.return_value = None
        self.vnc_lib.virtual_machine_interface_read.return_value = vmi

        self.vnc_client.delete_vmi('vmi_uuid')

        self.assertEqual(0, self.vnc_lib.instance_ip_delete.call_count)

    def test_delete_vm(self):
        vm = Mock(uuid='vm_uuid')
        vm.get_virtual_machine_interface_back_refs.return_value = [{'uuid': 'vmi_uuid'}]
        self.vnc_lib.virtual_machine_read.return_value = vm
        vmi = Mock(uuid='vmi_uuid')
        vmi.get_instance_ip_back_refs.return_value = [{'uuid': 'instance_ip_uuid'}]
        self.vnc_lib.virtual_machine_interface_read.return_value = vmi

        self.vnc_client.delete_vm('vm_uuid')

        self.vnc_lib.virtual_machine_interface_delete.assert_called_once_with(id='vmi_uuid')
        self.vnc_lib.virtual_machine_delete.assert_called_once_with(id='vm_uuid')

    def test_vm_no_back_refs(self):
        vm = Mock(uuid='vm_uuid')
        vm.get_virtual_machine_interface_back_refs.return_value = None
        self.vnc_lib.virtual_machine_read.return_value = vm

        self.vnc_client.delete_vm('vm_uuid')

        self.assertEqual(0, self.vnc_lib.virtual_machine_interface_delete.call_count)
