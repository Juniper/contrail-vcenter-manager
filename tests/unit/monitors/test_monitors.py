# pylint: disable=redefined-outer-name
import pytest
from mock import Mock

from cvm.constants import EVENTS_TO_OBSERVE
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


def test_configure_esxi_client(esxi_api_client, controller):
    ehc = Mock()
    esxi_api_client.create_event_history_collector.return_value = ehc

    VMwareMonitor(esxi_api_client, controller)

    esxi_api_client.create_event_history_collector.assert_called_once_with(EVENTS_TO_OBSERVE)
    esxi_api_client.add_filter.assert_called_once_with(ehc, ['latestPage'])
    esxi_api_client.make_wait_options.assert_called_once_with(120)
