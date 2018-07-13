from pyVmomi import vmodl  # pylint: disable=no-name-in-module


def test_handle_update_deleted_vm(controller, database, vm_service, vmi_service, vm_created_update):
    """
    When an event for an already deleted VM is received,
    the controller should do nothing.
    """
    vm_service.update.side_effect = vmodl.fault.ManagedObjectNotFound

    controller.handle_update(vm_created_update)

    assert not database.get_all_vm_models()
    vmi_service.update_vmis_for_vm_model.assert_not_called()
