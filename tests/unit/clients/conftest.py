# pylint: disable=redefined-outer-name
import pytest
from mock import Mock, patch
from vnc_api import vnc_api

from cvm.clients import VCenterAPIClient, VNCAPIClient
from cvm.models import VCenterPort
from tests.utils import create_dv_port


@pytest.fixture()
def dv_port():
    port = Mock(key='8')
    port.config.configVersion = '1'
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
    pvlan_entry = Mock(primaryVlanId=1, secondaryVlanId=2)
    dvswitch.config.pvlanConfig = [pvlan_entry]
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
        vnc_api_client = VNCAPIClient({'api_server_host': '', 'auth_host': ''})
        vnc_api_client._detach_floating_ips = Mock()
        vnc_api_client._detach_service_instances_from_instance_ip = Mock()
        return vnc_api_client


@pytest.fixture()
def vnc_vm():
    vnc_vm = Mock()
    vnc_vm.uuid = 'vm-uuid'
    vnc_vm.name = 'vm-name'
    return vnc_vm


@pytest.fixture()
def vnc_vmi_1():
    vmi = Mock(uuid='vmi-uuid-1')
    vmi.get_virtual_network_refs.return_value = [{'to': ['domain', 'project', 'vnc-vn-1']}]
    return vmi


@pytest.fixture()
def vnc_vmi_2():
    vmi = Mock(uuid='vmi-uuid-2')
    vmi.get_virtual_network_refs.return_value = [{'to': ['domain', 'project', 'vnc-vn-2']}]
    return vmi


@pytest.fixture()
def vnc_vn_1():
    vnc_vn = Mock()
    vnc_vn.get_fq_name.return_value = ['domain', 'project', 'vnc-vn-1']
    return vnc_vn


@pytest.fixture()
def vnc_vn_2():
    vnc_vn = Mock()
    vnc_vn.get_fq_name.return_value = ['domain', 'project', 'vnc-vn-2']
    return vnc_vn
