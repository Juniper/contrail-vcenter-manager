# pylint: disable=redefined-outer-name
import pytest
from mock import Mock
from pyVmomi import vmodl  # pylint: disable=no-name-in-module

from cvm.monitors import VMwareMonitor


@pytest.fixture()
def update_set():
    return vmodl.query.PropertyCollector.UpdateSet()


@pytest.fixture()
def esxi_api_client(update_set):
    api_client = Mock()
    api_client.wait_for_updates.return_value = update_set
    return api_client


@pytest.fixture()
def vmware_controller():
    controller = Mock()
    controller.handle_update.side_effect = StopIteration
    return controller


def test_pass_update_to_controller(esxi_api_client, vmware_controller, update_set):
    monitor = VMwareMonitor(esxi_api_client, vmware_controller)

    try:
        monitor.start()
    except StopIteration:
        pass

    vmware_controller.handle_update.assert_called_once_with(update_set)
