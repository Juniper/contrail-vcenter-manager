from mock import patch


def test_handle_vm_removed(controller, vm_service, vmi_service, vm_removed_update):
    with patch('cvm.controllers.time.sleep'):
        controller.handle_update(vm_removed_update)

    vm_service.remove_vm.assert_called_once_with('VM1')
    vmi_service.remove_vmis_for_vm_model.assert_called_once_with('VM1')
