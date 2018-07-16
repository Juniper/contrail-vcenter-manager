def test_guest_net(controller, vmi_service, vrouter_port_service, nic_info_update):
    controller.handle_update(nic_info_update)

    vmi_service.update_nic.assert_called_once()
    vrouter_port_service.sync_ports.assert_called_once()
