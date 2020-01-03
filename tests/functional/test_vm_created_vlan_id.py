from tests.utils import assert_vmi_model_state, reserve_vlan_ids


def test_vm_created_vlan_id(controller, database, vcenter_api_client,
                            vm_created_update, vn_model_1, vlan_id_pool):
    """
    What happens when the created interface is already using an overriden VLAN ID?
    We should keep it (if it's available on the host), not removing old/adding new VLAN ID,
    since it breaks the connectivity for a moment.
    """
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    reserve_vlan_ids(vlan_id_pool, [0, 1])

    # When we ask vCenter for the VLAN ID it turns out that the VLAN ID has already been overridden
    vcenter_api_client.get_vlan_id.return_value = 5

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # Check if VLAN ID has not been changed
    vcenter_api_client.set_vlan_id.assert_not_called()

    # Check inner VMI model state
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    vmi_model = database.get_all_vmi_models()[0]
    assert_vmi_model_state(
        vmi_model,
        mac_address='mac-address',
        ip_address='192.168.100.5',
        vlan_id=5,
        display_name='vmi-DPG1-VM1',
        vn_model=vn_model_1,
        vm_model=vm_model
    )


def test_vm_created_vlan_id_collision(controller, database, vcenter_api_client,
                                      vm_created_update, vn_model_1, vmi_model_2, vlan_id_pool):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)
    vmi_model_2.vcenter_port.vlan_id = 1
    database.save(vmi_model_2)

    # Some vlan ids should be already reserved
    reserve_vlan_ids(vlan_id_pool, [0, 1])

    # When we ask vCenter for the VLAN ID it turns out that the VLAN ID has already been overridden
    vcenter_api_client.get_vlan_id.return_value = 1

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # Check if VLAN ID has been set
    vcenter_api_client.set_vlan_id.assert_called_once()

    # Check inner VMI model state
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    vmi_model = next(model for model in database.get_all_vmi_models()
                 if model.display_name == 'vmi-DPG1-VM1')
    assert_vmi_model_state(
        vmi_model,
        mac_address='mac-address',
        ip_address='192.168.100.5',
        vlan_id=2,
        display_name='vmi-DPG1-VM1',
        vn_model=vn_model_1,
        vm_model=vm_model
    )
