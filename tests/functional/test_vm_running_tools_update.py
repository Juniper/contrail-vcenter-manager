from tests.utils import assert_vm_model_state


def test_vm_running_tools_update(controller, database, vm_created_update, vm_disable_running_tools_update,
                                 vm_enable_running_tools_update, vn_model_1):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    vm_model = database.get_vm_model_by_uuid('12345678-1234-1234-1234-123456789012')

    # Assumption that VM tools running
    assert_vm_model_state(vm_model, tools_running=True)

    # Then VM disable vmware tools event is being handled
    controller.handle_update(vm_disable_running_tools_update)

    # Check that VM  vmware tools is not running
    assert_vm_model_state(vm_model, tools_running=False)

    # Then VM enable vmware tools event is being handled
    controller.handle_update(vm_enable_running_tools_update)

    # Check that VM  vmware tools is running
    assert_vm_model_state(vm_model, tools_running=True)
