from mock import Mock
from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module
from vnc_api import vnc_api

from cvm.clients import make_filter_spec
from cvm.models import VirtualNetworkModel, VirtualMachineModel


def create_vmware_vm_mock(network=None, uuid=None):
    vmware_vm = Mock(spec=vim.VirtualMachine)
    vmware_vm.summary.runtime.host = Mock(vm=[vmware_vm])
    vmware_vm.config.hardware.device = []
    vm_properties = {
        'config.instanceUuid': uuid or 'd376b6b4-943d-4599-862f-d852fd6ba425',
        'name': 'VM',
        'runtime.powerState': 'poweredOn',
        'guest.toolsRunningStatus': 'guestToolsRunning',
    }
    vmware_vm.network = network
    vmware_vm.guest.net = []
    if network:
        device = Mock()
        backing_mock = Mock(spec=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo())
        device.backing = backing_mock
        device.backing.port.portgroupKey = network[0].key
        device.macAddress = 'c8:5b:76:53:0f:f5'
        vmware_vm.config.hardware.device = [device]
    return vmware_vm, vm_properties


def create_dpg_mock(**kwargs):
    dpg_mock = Mock(spec=vim.dvs.DistributedVirtualPortgroup)
    for kwarg in kwargs:
        setattr(dpg_mock, kwarg, kwargs[kwarg])
    dpg_mock.config.distributedVirtualSwitch.FetchDVPorts.return_value = []
    return dpg_mock


def create_vcenter_client_mock():
    vcenter_client = Mock()
    vcenter_client.__enter__ = Mock()
    vcenter_client.__exit__ = Mock()
    vcenter_client.get_ip_pool_for_dpg.return_value = None
    return vcenter_client


def create_vnc_client_mock():
    vnc_client = Mock()
    vnc_client.read_or_create_project.return_value = vnc_api.Project()
    vnc_client.read_security_group.return_value = vnc_api.SecurityGroup()
    return vnc_client


def create_property_filter(obj, filters):
    filter_spec = make_filter_spec(obj, filters)
    return vmodl.query.PropertyCollector.Filter(filter_spec)


def create_vm_model(network=None, uuid=None):
    vmware_vm, vm_properties = create_vmware_vm_mock(network=network, uuid=uuid)
    return VirtualMachineModel(vmware_vm, vm_properties)


def create_vn_model(name, key, uuid=None):
    vnc_vn = Mock()
    vnc_vn.name = name
    vnc_vn.uuid = uuid or 'uuid'
    vmware_dpg = create_dpg_mock(name=name, key=key)
    return VirtualNetworkModel(vmware_dpg, vnc_vn)


def create_port_mock(vlan_id):
    port = Mock()
    port.config.setting.vlan.vlanId = vlan_id
    return port
