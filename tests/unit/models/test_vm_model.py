from cvm.models import VirtualMachineModel


def test_init(vmware_vm_1, vm_properties_1):
    vm_model = VirtualMachineModel(vmware_vm_1, vm_properties_1)

    assert vmware_vm_1.config.hardware.device is vm_model.devices
    assert vm_model.uuid == 'vmware-vm-uuid-1'
    assert vm_model.name == 'VM1'
    assert vm_model.is_powered_on
    assert vm_model.tools_running


def test_to_vnc(vm_model):
    vm_model.vrouter_uuid = 'vrouter_uuid'

    vnc_vm = vm_model.vnc_vm

    assert vnc_vm.name == vm_model.uuid
    assert vnc_vm.uuid == vm_model.uuid
    assert vnc_vm.fq_name == [vm_model.uuid]


def test_update(vm_model, vmware_vm_1_updated, vm_properties_1_updated):
    vm_model.update(vmware_vm_1_updated, vm_properties_1_updated)

    assert vm_model.devices == []
    assert vm_model.uuid == 'vmware-vm-uuid-1'
    assert vm_model.name == 'VM1-renamed'
    assert vm_model.is_powered_on is False
    assert vm_model.tools_running is False


def test_update_power_state(vm_model):
    check_1 = vm_model.is_power_state_changed('poweredOff')
    vm_model.update_power_state('poweredOff')
    check_2 = vm_model.is_power_state_changed('poweredOff')

    assert check_1 is True
    assert check_2 is False
    assert vm_model.is_powered_on is False


def test_update_tools_running(vm_model):
    check_1 = vm_model.is_tools_running_status_changed('guestToolsNotRunning')
    vm_model.update_tools_running_status('guestToolsNotRunning')
    check_2 = vm_model.is_tools_running_status_changed('guestToolsNotRunning')

    assert check_1 is True
    assert check_2 is False
    assert vm_model.tools_running is False
