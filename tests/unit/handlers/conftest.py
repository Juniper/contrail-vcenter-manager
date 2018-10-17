import pytest
from mock import Mock


@pytest.fixture()
def vm_service():
    service = Mock()
    service.wait_for_task_for_event.return_value = 'success'
    return service


@pytest.fixture()
def vn_service():
    return Mock()


@pytest.fixture()
def vmi_service():
    return Mock()


@pytest.fixture()
def vrouter_port_service():
    return Mock()


@pytest.fixture()
def vrouter_api_client():
    return Mock()
