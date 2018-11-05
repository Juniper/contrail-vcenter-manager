from tests.utils import reserve_vlan_ids


def test_full_remove_vm(controller, database, vcenter_api_client, vnc_api_client, vrouter_api_client,
                        vm_created_update, vm_removed_update, vn_model_1, vlan_id_pool):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # In this scenario vCenter should return no relocation
    vcenter_api_client.is_vm_removed.return_value = True

    # Some vlan ids should be already reserved
    vcenter_api_client.get_vlan_id.return_value = None
    reserve_vlan_ids(vlan_id_pool, [0, 1, 2, 3])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)
    vrouter_api_client.read_port.return_value = {'uuid': 'port-uuid'}

    # After VmCreatedEvent has been handled
    # proper VM model should exists
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert vm_model is not None
    # And associated VMI model
    vmi_models = vm_model.vmi_models
    assert len(vmi_models) == 1
    vmi_model = vmi_models[0]
    assert vmi_model is not None
    # And proper VLAN ID should be acquired
    assert not vlan_id_pool.is_available(4)

    # The VM is not present on any other ESXi
    vcenter_api_client.can_remove_vm.return_value = True

    # Then VmRemovedEvent is being handled
    controller.handle_update(vm_removed_update)

    # Check that VM Model has been removed from Database:
    assert database.get_vm_model_by_uuid(vm_model.uuid) is None

    # Check that VM has been removed from VNC
    vnc_api_client.delete_vm.assert_called_once_with(vm_model.uuid)

    # Check that VMI Model which was associated with removed VM has been removed
    # from Database
    vmi_models = database.get_vmi_models_by_vm_uuid(vm_model.uuid)
    assert vmi_models == []

    # from VNC
    vnc_api_client.delete_vmi.assert_called_with(vmi_model.uuid)

    # Check that VMI's vRouter Port has been deleted:
    vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)
    vrouter_api_client.add_port.assert_called_once()

    # Check that VLAN ID has been released
    vcenter_api_client.restore_vlan_id.assert_called_once_with(vmi_model.vcenter_port)
    assert vlan_id_pool.is_available(4)


def test_vm_removed_local_remove(controller, database, vcenter_api_client, vnc_api_client, vrouter_api_client,
                                 vm_created_update, vm_removed_update, vn_model_1, vlan_id_pool):
    """
    Same situation as in test_full_remove_vm, but between VmCreatedEvent and VmDeletedEvent VM
    changed its ESXi host. It happens during vMotion. So we have to remove that VM and its associated objects
    from database and vRouter. But cannot remove them from VNC and vCenter
    """
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # In this scenario vCenter should return info about relocation
    vcenter_api_client.is_vm_removed.return_value = False

    # Some vlan ids should be already reserved
    vcenter_api_client.get_vlan_id.return_value = None
    reserve_vlan_ids(vlan_id_pool, [0, 1, 2, 3])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)
    vrouter_api_client.read_port.return_value = {'uuid': 'port-uuid'}


    # After VmCreatedEvent has been handled
    # proper VM model should exists
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert vm_model is not None
    # And associated VMI model
    vmi_models = vm_model.vmi_models
    assert len(vmi_models) == 1
    vmi_model = vmi_models[0]
    assert vmi_model is not None
    # And proper VLAN ID should be acquired
    assert not vlan_id_pool.is_available(4)

    # The VM is present on some other ESXi
    vcenter_api_client.can_remove_vm.return_value = False

    # Then VmRemovedEvent is being handled
    controller.handle_update(vm_removed_update)

    # Check that VM Model has been removed from Database:
    assert database.get_vm_model_by_uuid(vm_model.uuid) is None

    # Cannot remove VM from VNC
    vnc_api_client.delete_vm.assert_not_called()

    # Check that VMI Model which was associated with removed VM has been removed
    # from Database
    vmi_models = database.get_vmi_models_by_vm_uuid(vm_model.uuid)
    assert vmi_models == []

    # Cannot remove VMI from VNC
    vnc_api_client.delete_vmi.assert_not_called()

    # Check that VMI's vRouter Port has been deleted:
    vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)
    vrouter_api_client.add_port.assert_called_once

    # Cannot remove VLAN ID from vCenter
    vcenter_api_client.restore_vlan_id.assert_not_called()

    # Check that VLAN ID has been restored to local pool
    assert vlan_id_pool.is_available(4)
