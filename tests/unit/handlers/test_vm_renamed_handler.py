def test_vm_renamed(controller, vm_service, vmi_service, vm_renamed_update):
    controller.handle_update(vm_renamed_update)

    vm_service.rename_vm.assert_called_once_with('VM1', 'VM1-renamed')
    vmi_service.rename_vmis.assert_called_once_with('VM1-renamed')
