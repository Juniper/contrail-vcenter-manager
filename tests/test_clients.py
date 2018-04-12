from unittest import TestCase

from mock import Mock, patch
from pyVmomi import vim

from cvm.clients import ESXiAPIClient, VCenterAPIClient, make_dv_port_spec
from tests.test_services import create_vmware_vm_mock


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

    def test_set_vlan_id(self):
        dv_port = Mock(key='8')
        dv_port.config.configVersion = '1'
        dvs = Mock()
        dvs.FetchDVPorts.return_value = [dv_port]
        with patch('cvm.clients.SmartConnectNoSSL'):
            with self.vcenter_client:
                self.vcenter_client.set_vlan_id(dvs=dvs, key='8', vlan_id=10)

        dvs.ReconfigureDVPort_Task.assert_called_once()
        spec = dvs.ReconfigureDVPort_Task.call_args[1].get('port', [None])[0]
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
                self.vcenter_client.enable_vlan_override(portgroup=portgroup)

        portgroup.ReconfigureDVPortgroup_Task.assert_called_once()
        config = portgroup.ReconfigureDVPortgroup_Task.call_args
        self.assertTrue(config.policy.vlanOverrideAllowed)
        self.assertEqual('1', config.configVersion)


class TestFunctions(TestCase):
    def test_make_dv_port_spec(self):
        dv_port = Mock(key='8')
        dv_port.config.configVersion = '1'
        spec = make_dv_port_spec(dv_port, 10)
        self.assertEqual('8', spec.key)
        self.assertEqual('edit', spec.operation)
        self.assertEqual(10, spec.setting.vlan.vlanId)
        self.assertEqual('1', spec.configVersion)
