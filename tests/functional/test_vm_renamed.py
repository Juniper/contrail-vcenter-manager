from mock import patch

from tests.utils import (assert_vm_model_state, assert_vmi_model_state,
                         assert_vnc_vm_state)


@patch('cvm.services.wait_for_port')
def test_vm_renamed(_, controller, database, esxi_api_client, vcenter_api_client, vnc_api_client, vrouter_api_client,
                    vm_created_update, vm_renamed_update, vm_properties_renamed, vn_model_1):
    # Virtual Networks are already created for us and after synchronization,
    # their models are stored in our database
    database.save(vn_model_1)

    # The port has no vlan id set in vcenter
    vcenter_api_client.get_vlan_id.return_value = None

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # A user renames the VM in vSphere and VmRenamedEvent arrives
    esxi_api_client.read_vm_properties.return_value = vm_properties_renamed
    controller.handle_update(vm_renamed_update)

    # Check if VM Model has been saved properly:
    # - in VNC:
    assert vnc_api_client.update_vmi.call_count == 2
    vnc_vm = vnc_api_client.update_vm.call_args[0][0]
    assert_vnc_vm_state(vnc_vm, uuid='vmware-vm-uuid-1',
                        name='vmware-vm-uuid-1', display_name='VM1-renamed')

    # - in Database:
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert_vm_model_state(vm_model, uuid='vmware-vm-uuid-1', name='VM1-renamed')

    # Check if VMI Model has been saved properly:
    # - in VNC
    assert vnc_api_client.update_vmi.call_count == 2

    # - in Database
    vmi_model = database.get_all_vmi_models()[0]

    # Check if VMI Model's Instance IP has been created in VNC:
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    # Check if VMI's vRouter Port has been added:
    vrouter_api_client.add_port.called_with(vmi_model)
    assert vrouter_api_client.add_port.call_count == 2

    # Check if VLAN ID has been set using VLAN Override
    vcenter_port = vcenter_api_client.set_vlan_id.call_args[0][0]
    assert vcenter_port.port_key == '10'
    assert vcenter_port.vlan_id == 0

    # Check inner VMI model state
    assert_vmi_model_state(
        vmi_model,
        mac_address='mac-address',
        ip_address='192.168.100.5',
        vlan_id=0,
        display_name='vmi-DPG1-VM1-renamed',
        vn_model=vn_model_1,
        vm_model=vm_model
    )
