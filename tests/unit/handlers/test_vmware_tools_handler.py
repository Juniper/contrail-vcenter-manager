from pyVmomi import vmodl  # pylint: disable=no-name-in-module


def test_vmware_tools_running(controller, vm_service, vmware_vm_1, vmware_tools_running_update):
    controller.handle_update(vmware_tools_running_update)

    vm_service.update_vmware_tools_status.assert_called_once_with(
        vmware_vm_1, 'guestToolsRunning'
    )


def test_vmware_tools_not_running(controller, vm_service, vmware_vm_1, vmware_tools_not_running_update):
    controller.handle_update(vmware_tools_not_running_update)

    vm_service.update_vmware_tools_status.assert_called_once_with(
        vmware_vm_1, 'guestToolsNotRunning'
    )


def test_handle_tools_deleted_vm(controller, database, vm_service, vmware_tools_running_update):
    """
    When 'guest.toolsRunningStatus' change for an already deleted VM is received,
    the controller should do nothing.
    """
    vm_service.update_vmware_tools_status.side_effect = vmodl.fault.ManagedObjectNotFound

    controller.handle_update(vmware_tools_running_update)

    assert not database.get_all_vm_models()
