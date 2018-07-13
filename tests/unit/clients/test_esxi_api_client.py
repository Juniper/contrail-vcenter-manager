# pylint: disable=redefined-outer-name
import pytest
from mock import Mock, patch

from cvm.clients import ESXiAPIClient


@pytest.fixture()
def vm_esxi_properties(vmware_vm_1):
    dynamic_property = Mock(val='VM1')
    dynamic_property.configure_mock(name='name')
    return Mock(obj=vmware_vm_1, propSet=[dynamic_property])


@pytest.fixture()
def property_collector(vm_esxi_properties):
    pc = Mock()
    pc.RetrievePropertiesEx.return_value.objects = [vm_esxi_properties]
    return pc


@pytest.fixture()
def esxi_api_client(property_collector):
    with patch('cvm.clients.SmartConnectNoSSL') as si_mock:
        si_mock.return_value.content.propertyCollector = property_collector
        return ESXiAPIClient({})


def test_read_vm(esxi_api_client, vmware_vm_1):
    result = esxi_api_client.read_vm_properties(vmware_vm_1)

    assert result.get('name') == 'VM1'
