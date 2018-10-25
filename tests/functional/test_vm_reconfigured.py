from mock import patch

from tests.utils import (assert_vm_model_state, assert_vmi_model_state,
                         reserve_vlan_ids)


@patch('cvm.services.wait_for_port')
def test_vm_reconfigured(_, controller, database, vcenter_api_client, vnc_api_client, vrouter_api_client,
                         vm_created_update, vm_reconfigured_update, vmware_vm_1, vn_model_1, vnc_vn_2, vn_model_2,
                         vlan_id_pool):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)
    database.save(vn_model_2)

    # Some vlan ids should be already reserved
    vcenter_api_client.get_vlan_id.return_value = None
    reserve_vlan_ids(vlan_id_pool, [0, 1, 2, 3])

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # After a portgroup is changed, the port key is also changed
    vmware_vm_1.config.hardware.device[0].backing.port.portgroupKey = 'dvportgroup-2'
    vmware_vm_1.config.hardware.device[0].backing.port.portKey = '11'

    # Then VmReconfiguredEvent is being handled
    controller.handle_update(vm_reconfigured_update)

    # Check if VM Model has been saved properly in Database:
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert_vm_model_state(vm_model, has_ports={'mac-address': 'dvportgroup-2'})

    # Check that VM was not updated in VNC except VM create event
    vnc_api_client.update_vm.assert_called_once()

    # Check if VMI Model has been saved properly:

    # - in Database
    vmi_models = database.get_vmi_models_by_vm_uuid('vmware-vm-uuid-1')
    assert len(vmi_models) == 1
    vmi_model = vmi_models[0]

    # - in VNC
    assert vnc_api_client.update_vmi.call_count == 2
    vnc_vmi = vnc_api_client.update_vmi.call_args[0][0]
    assert vnc_vmi.get_virtual_network_refs()[0]['uuid'] == vnc_vn_2.uuid

    # Check if VMI Model's Instance IP has been updated in VNC:
    assert vnc_api_client.create_and_read_instance_ip.call_count == 2
    new_instance_ip = vmi_model.vnc_instance_ip
    assert vnc_api_client.create_and_read_instance_ip.call_args[0][0] == vmi_model
    assert vnc_vn_2.uuid in [ref['uuid'] for ref in new_instance_ip.get_virtual_network_refs()]

    # Check if VMI's vRouter Port has been updated:
    assert vrouter_api_client.delete_port.call_count == 2
    assert vrouter_api_client.delete_port.call_args[0][0] == vmi_model.uuid
    assert vrouter_api_client.add_port.call_count == 2
    assert vrouter_api_client.add_port.call_args[0][0] == vmi_model

    # Check if VLAN ID has been set using VLAN Override
    assert vcenter_api_client.set_vlan_id.call_count == 2
    vcenter_port = vcenter_api_client.set_vlan_id.call_args[0][0]
    assert vcenter_port.port_key == '11'
    assert vcenter_port.vlan_id == 5

    # Check inner VMI model state
    assert_vmi_model_state(
        vmi_model,
        mac_address='mac-address',
        ip_address='192.168.100.5',
        vlan_id=5,
        display_name='vmi-DPG2-VM1',
        vn_model=vn_model_2
    )
