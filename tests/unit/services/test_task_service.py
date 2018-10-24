def test_wait_for_task(task_service, esxi_api_client, vm_register_task_info, vm_registered_event, vmware_vm_1):

    task_is_finished = task_service.wait_for_task(vm_registered_event, 'vim.Folder.registerVm')

    assert task_is_finished
    esxi_api_client.find_task.assert_called_once_with(vmware_vm_1, 'vim.Folder.registerVm')
    esxi_api_client.is_task_finished.assert_called_once_with(vm_register_task_info)
