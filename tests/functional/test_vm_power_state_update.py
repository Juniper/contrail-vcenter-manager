from mock import patch, Mock

from tests.utils import assert_vm_model_state


def test_vm_power_state_update(controller, database, vrouter_api_client, vm_created_update, vm_power_on_state_update,
                               vm_power_off_state_update, vn_model_1):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    # Assumption that VM is in powerOn state
    assert_vm_model_state(vm_model, is_powered_on=True)

    # Then VM power state change is being handled
    controller.handle_update(vm_power_off_state_update)

    # Check that VM is in powerOff state
    assert_vm_model_state(vm_model, is_powered_on=False)

    vmi_models = database.get_vmi_models_by_vm_uuid('vmware-vm-uuid-1')
    assert len(vmi_models) == 1
    vmi_model = vmi_models[0]

    # Check that vRouter Port was disabled
    vrouter_api_client.disable_port.assert_called_once_with(vmi_model.uuid)

    controller.handle_update(vm_power_on_state_update)

    # Check that VM is in powerOn state
    assert_vm_model_state(vm_model, is_powered_on=True)

    # Check that vRouter Port was enabled
    vrouter_api_client.enable_port.assert_called_with(vmi_model.uuid)


@patch('cvm.services.wait_for_port', return_value=True)
def test_set_vlan_id_on_power_on(_, controller, database, vcenter_api_client, esxi_api_client, vrouter_api_client,
                                 vm_registered_update, vm_power_on_state_update, vn_model_1, vm_properties_1_off):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # CVM sets VLAN ID in vCenter only when current VLAN conflicts with VLAN of another VM
    database.is_vlan_available = Mock()
    database.is_vlan_available.return_value = False
    vcenter_api_client.set_vlan_id.return_value = 'success', None

    # VM is powered off when the VM Registered event comes
    esxi_api_client.read_vm_properties.return_value = vm_properties_1_off

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_registered_update)

    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    # Assumption that VM is in powerOn state
    assert_vm_model_state(vm_model, is_powered_on=False)

    # Then VM power state change is being handled
    controller.handle_update(vm_power_on_state_update)

    # Check that VM is in powerOn state
    assert_vm_model_state(vm_model, is_powered_on=True)

    vmi_models = database.get_vmi_models_by_vm_uuid('vmware-vm-uuid-1')
    assert len(vmi_models) == 1
    vmi_model = vmi_models[0]

    vcenter_api_client.set_vlan_id.assert_called_once_with(vmi_model.vcenter_port)

    # Check that vRouter Port was disabled
    vrouter_api_client.enable_port.assert_called_once_with(vmi_model.uuid)
