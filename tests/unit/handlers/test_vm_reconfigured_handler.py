def test_vm_reconfigured(controller, vm_service, vn_service, vmi_service, vrouter_port_service,
                         vm_reconfigured_update):
    controller.handle_update(vm_reconfigured_update)

    vm_service.update_vm_models_interfaces.assert_called_once()
    vn_service.update_vns.assert_called_once()
    vmi_service.update_vmis.assert_called_once()
    vrouter_port_service.sync_ports.assert_called_once()
