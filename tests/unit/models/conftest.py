import pytest
from mock import Mock
from pyVmomi import vim  # pylint: disable=no-name-in-module


@pytest.fixture()
def vmware_vm_1_updated():
    vmware_vm = Mock(spec=vim.VirtualMachine)
    vmware_vm.summary.runtime.host.vm = []
    vmware_vm.config.instanceUuid = 'vmware-vm-uuid-1'
    vmware_vm.config.hardware.device = []
    return vmware_vm


@pytest.fixture()
def vm_properties_1_updated(host_1):
    return {
        'config.instanceUuid': 'vmware-vm-uuid-1',
        'name': 'VM1-renamed',
        'runtime.powerState': 'poweredOff',
        'guest.toolsRunningStatus': 'guestToolsNotRunning',
        'summary.runtime.host': host_1,
    }
