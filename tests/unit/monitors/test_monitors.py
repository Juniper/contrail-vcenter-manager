# pylint: disable=redefined-outer-name
import pytest
from mock import Mock

from cvm.monitors import VMwareMonitor


@pytest.fixture()
def controller():
    ctrlr = Mock()
    ctrlr.handle_update.side_effect = StopIteration
    return ctrlr


@pytest.fixture()
def monitor(controller, esxi_api_client):
    return VMwareMonitor(esxi_api_client, controller)


def test_pass_update_to_controller(monitor, controller, esxi_api_client, vm_created_update):
    esxi_api_client.wait_for_updates.return_value = vm_created_update

    try:
        monitor.start()
    except StopIteration:
        pass

    controller.handle_update.assert_called_once_with(vm_created_update)
