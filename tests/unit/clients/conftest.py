# pylint: disable=redefined-outer-name
import pytest
from mock import Mock, patch
from pyVmomi import vim  # pylint: disable=no-name-in-module
from vnc_api import vnc_api

from cvm.clients import VCenterAPIClient, VNCAPIClient
from cvm.models import VCenterPort


@pytest.fixture()
def dv_port():
    port = Mock(key='8')
    port.config.setting.vlan = Mock(spec=vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec)
    port.config.configVersion = '1'
    return port


@pytest.fixture()
def vcenter_port():
    device = Mock(macAddress='mac-address')
    device.backing.port.portKey = '8'
    device.backing.port.portgroupKey = 'portgroup-key'
    return VCenterPort(device)


@pytest.fixture()
def dvs(dv_port):
    dvswitch = Mock()
    dvswitch.FetchDVPorts.return_value = [dv_port]
    return dvswitch


@pytest.fixture()
def vcenter_api_client():
    return VCenterAPIClient({})


@pytest.fixture()
def vnc_lib():
    return Mock()


@pytest.fixture()
def vnc_api_client(vnc_lib):
    with patch.object(vnc_api, 'VncApi', return_value=vnc_lib):
        return VNCAPIClient({})


@pytest.fixture()
def vnc_vm():
    return Mock(uuid='vm-uuid')


@pytest.fixture()
def vnc_vmi():
    return Mock(uuid='vmi-uuid')
