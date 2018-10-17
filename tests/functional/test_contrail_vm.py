def test_contrail_vm(controller, database, esxi_api_client, vnc_api_client, vrouter_api_client, vm_created_update,
                     contrail_vm_properties):
    """ We don't need ContrailVM model for CVM to operate properly. """
    esxi_api_client.read_vm_properties.return_value = contrail_vm_properties
    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # VM model has not been saved in the database
    assert not database.get_all_vm_models()

    # There were no calls to vnc_api
    vnc_api_client.update_vm.assert_not_called()
    vnc_api_client.update_vmi.assert_not_called()

    # There were no calls to vrouter_api
    vrouter_api_client.add_port.assert_not_called()
