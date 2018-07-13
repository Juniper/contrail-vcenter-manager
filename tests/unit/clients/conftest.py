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


def create_dv_port(vlan_id, vrouter_uuid):
    port = Mock()
    port.config.setting.vlan = Mock(spec=vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec)
    port.config.setting.vlan.vlanId = vlan_id
    vm_mock = Mock()
    vm_mock.name = 'ContrailVM'
    vm_mock.config.instanceUuid = vrouter_uuid
    port.proxyHost.vm = [vm_mock]
    return port


@pytest.fixture()
def dv_port_1():
    return create_dv_port(10, 'vrouter_uuid_1')


@pytest.fixture()
def dv_port_2():
    return create_dv_port(7, 'vrouter_uuid_1')


@pytest.fixture()
def dv_port_3():
    return create_dv_port(5, 'vrouter_uuid_2')


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
def dvs_1(dv_port_1, dv_port_2, dv_port_3):
    dvswitch = Mock()
    dvswitch.FetchDVPorts.return_value = [dv_port_1, dv_port_2, dv_port_3]
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
