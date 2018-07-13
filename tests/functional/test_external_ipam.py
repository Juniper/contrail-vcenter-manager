from tests.utils import dont_assign_ip_to_instance_ip


def test_external_ipam(controller, database, vnc_api_client, vrouter_api_client, vm_created_update, nic_info_update,
                       vn_model_1):
    """ We don't need ContrailVM model for CVM to operate properly. """

    # The network we use uses external IPAM
    vn_model_1.vnc_vn.external_ipam = True
    database.save(vn_model_1)

    # We use external IPAM, so there's no assignment of IP addresses
    vnc_api_client.create_and_read_instance_ip.side_effect = dont_assign_ip_to_instance_ip

    controller.handle_update(vm_created_update)

    # The IP address was not assigned by Contrail Controller
    vmi_model = database.get_all_vmi_models()[0]
    assert vmi_model.ip_address is None
    assert vmi_model.vnc_instance_ip is None

    controller.handle_update(nic_info_update)

    # IP address is updated
    assert vmi_model.ip_address == '192.168.100.5'
    assert vmi_model.vnc_instance_ip.instance_ip_address == '192.168.100.5'
    assert vnc_api_client.create_and_read_instance_ip.call_args[0][0] is vmi_model.vnc_instance_ip

    # vRouter port should not be updated - it will gather IP info from the Controller
    vrouter_api_client.add_port.assert_called_once()
    vrouter_api_client.delete_port.assert_called_once()

    # The VMI itself should not be updated, since there's no new info
    vnc_api_client.update_vmi.assert_called_once()
