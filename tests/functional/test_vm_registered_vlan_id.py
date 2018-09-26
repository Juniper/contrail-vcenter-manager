from mock import patch

from tests.utils import assert_vmi_model_state, reserve_vlan_ids


@patch('cvm.services.time.sleep', return_value=None)
def test_vmotion_vlan_unavailable(_, controller, database, vcenter_api_client, vm_registered_update, vn_model_1,
                                  vlan_id_pool):
    """ When the VLAN ID is unavailable on a host, we should change it to a new value"""
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    reserve_vlan_ids(vlan_id_pool, [0, 1, 5])

    # When we ask vCenter for the VLAN ID it turns out that the VLAN ID has already been overridden
    vcenter_api_client.get_vlan_id.return_value = 5

    # A new update containing VmRegisteredEvent arrives and is being handled by the controller
    controller.handle_update(vm_registered_update)

    # Check if VLAN ID has been changed
    vmi_model = database.get_all_vmi_models()[0]
    vcenter_api_client.set_vlan_id.assert_called_once_with(vmi_model.vcenter_port)

    # Check inner VMI model state
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert_vmi_model_state(
        vmi_model,
        mac_address='mac-address',
        ip_address='192.168.100.5',
        vlan_id=2,
        display_name='vmi-DPG1-VM1',
        vn_model=vn_model_1,
        vm_model=vm_model
    )


def test_vmotion_vlan_available(controller, database, vcenter_api_client, vm_registered_update, vn_model_1,
                                vlan_id_pool):
    """ When the VLAN ID is available on a host, we should not change it"""
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    reserve_vlan_ids(vlan_id_pool, [0, 1])

    # When we ask vCenter for the VLAN ID it turns out that the VLAN ID has already been overridden
    vcenter_api_client.get_vlan_id.return_value = 5

    # A new update containing VmRegisteredEvent arrives and is being handled by the controller
    controller.handle_update(vm_registered_update)

    # Check if VLAN ID has been changed
    vmi_model = database.get_all_vmi_models()[0]
    vcenter_api_client.set_vlan_id.assert_not_called()

    # Check inner VMI model state
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert_vmi_model_state(
        vmi_model,
        mac_address='mac-address',
        ip_address='192.168.100.5',
        vlan_id=5,
        display_name='vmi-DPG1-VM1',
        vn_model=vn_model_1,
        vm_model=vm_model
    )


def test_registered_existing_vmi(controller, database, vnc_api_client,
                                 vm_registered_update, vn_model_1, vnc_vmi, instance_ip):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # VMI already exists in VNC
    vnc_api_client.read_vmi.return_value = vnc_vmi
    vnc_api_client.get_instance_ip_for_vmi.return_value = instance_ip

    # A new update containing VmRegisteredEvent arrives and is being handled by the controller
    controller.handle_update(vm_registered_update)

    vnc_api_client.delete_vmi.assert_not_called()
    vnc_api_client.delete_instance_ip.assert_not_called()

    vnc_api_client.update_vmi_vrouter_uuid.assert_called_once()
    assert vnc_api_client.update_vmi_vrouter_uuid.call_args[0][0] == vnc_vmi

    vnc_api_client.update_instance_ip_vrouter_uuid.assert_called_once()
    print type(instance_ip)
    print type(vnc_api_client.update_instance_ip_vrouter_uuid.call_args[0][0])
    assert vnc_api_client.update_instance_ip_vrouter_uuid.call_args[0][0] == instance_ip

    assert len(database.get_all_vmi_models()) == 1
