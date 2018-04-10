from unittest import TestCase

from mock import Mock, patch

from cvm.clients import ESXiAPIClient
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
        self.property_collector.RetrievePropertiesEx.return_value = object_content

        result = self.esxi_client.read_vm_properties(self.vmware_vm)

        self.assertEqual('VM', result.get('name'))
