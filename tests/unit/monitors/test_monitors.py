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


@pytest.fixture()
def update_set_queue(vm_created_update):
    queue = Mock()
    queue.get.return_value = vm_created_update
    return queue


def test_pass_update_to_controller(monitor, controller, update_set_queue, vm_created_update):
    try:
        monitor.start(update_set_queue)
    except StopIteration:
        pass

    controller.handle_update.assert_called_once_with(vm_created_update)
