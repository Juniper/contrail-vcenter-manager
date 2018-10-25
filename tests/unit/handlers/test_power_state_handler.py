def test_power_on_state(controller, vm_service, vrouter_port_service,
                        vlan_id_service, vmware_vm_1, vm_power_on_state_update):
    controller.handle_update(vm_power_on_state_update)

    vm_service.update_power_state.assert_called_once_with(vmware_vm_1, 'poweredOn')

    vrouter_port_service.sync_port_states.assert_called_once()
    vlan_id_service.update_vcenter_vlans.assert_called_once()


def test_power_off_state(controller, vm_service, vrouter_port_service,
                         vlan_id_service, vmware_vm_1, vm_power_off_state_update):
    controller.handle_update(vm_power_off_state_update)

    vm_service.update_power_state.assert_called_once_with(vmware_vm_1, 'poweredOff')
    vrouter_port_service.sync_port_states.assert_called_once()
    vlan_id_service.update_vcenter_vlans.assert_called_once()