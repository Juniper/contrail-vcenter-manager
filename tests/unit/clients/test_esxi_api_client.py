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
def esxi_api_client(property_collector, vm_register_task_info):
    with patch('cvm.clients.SmartConnectNoSSL') as si_mock:
        si_mock.return_value.content.propertyCollector = property_collector
        si_mock.return_value.content.taskManager.recentTask = [vm_register_task_info.task]
        return ESXiAPIClient({})


def test_read_vm(esxi_api_client, vmware_vm_1):
    result = esxi_api_client.read_vm_properties(vmware_vm_1)

    assert result.get('name') == 'VM1'


def test_find_task(esxi_api_client, vm_register_task_info, vmware_vm_1):
    task = esxi_api_client.find_task(vmware_vm_1, 'vim.Folder.registerVm')

    assert task.info == vm_register_task_info


def test_is_task_finished(esxi_api_client, vm_register_task_info):
    with patch('cvm.clients.WaitForTask', return_value='success') as wait_mock:
        result = esxi_api_client.is_task_finished(vm_register_task_info.task)

    assert result
    wait_mock.assert_called_once_with(vm_register_task_info.task)
