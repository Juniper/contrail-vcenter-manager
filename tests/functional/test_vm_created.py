from tests.utils import (assert_vm_model_state, assert_vmi_model_state,
                         assert_vnc_vm_state, assert_vnc_vmi_state,
                         reserve_vlan_ids)


def test_vm_created(controller, database, vcenter_api_client, vnc_api_client, vrouter_api_client, vlan_id_pool,
                    vm_created_update, vnc_vn_1, vn_model_1):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # Some vlan ids should be already reserved
    vcenter_api_client.get_vlan_id.return_value = None
    reserve_vlan_ids(vlan_id_pool, [0, 1])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # Check if VM Model has been saved properly:
    # - in VNC:
    vnc_api_client.update_vm.assert_called_once()
    vnc_vm = vnc_api_client.update_vm.call_args[0][0]
    assert_vnc_vm_state(vnc_vm, uuid='vmware-vm-uuid-1',
                        name='vmware-vm-uuid-1', owner='project-uuid')

    # - in Database:
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert_vm_model_state(vm_model, uuid='vmware-vm-uuid-1', name='VM1')

    # Check if VMI Model has been saved properly:
    # - in VNC
    vnc_api_client.update_vmi.assert_called_once()
    vnc_vmi = vnc_api_client.update_vmi.call_args[0][0]
    assert_vnc_vmi_state(vnc_vmi, mac_address='mac-address',
                         vnc_vm_uuid=vnc_vm.uuid, vnc_vn_uuid=vnc_vn_1.uuid)

    # - in Database
    vmi_model = database.get_all_vmi_models()[0]

    # Check if VMI Model's Instance IP has been created in VNC:
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    # Check if VMI's vRouter Port has been added:
    vrouter_api_client.read_port.assert_called_once()
    vrouter_api_client.delete_port.assert_not_called()
    vrouter_api_client.add_port.assert_called_once_with(vmi_model)
    vrouter_api_client.disable_port.assert_not_called()

    # Check if VLAN ID has been set using VLAN Override
    vcenter_port = vcenter_api_client.set_vlan_id.call_args[0][0]
    assert vcenter_port.port_key == '10'
    assert vcenter_port.vlan_id == 2

    # Check inner VMI model state
    assert_vmi_model_state(
        vmi_model,
        mac_address='mac-address',
        ip_address='192.168.100.5',
        vlan_id=2,
        display_name='vmi-DPG1-VM1',
        vn_model=vn_model_1,
        vm_model=vm_model
    )
