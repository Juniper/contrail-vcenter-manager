def test_sync(monitor, database, esxi_api_client, vcenter_api_client, vrouter_api_client, vnc_api_client, vmware_vm_1,
              vnc_vn_1, portgroup, vnc_vm):
    esxi_api_client.get_all_vms.return_value = [vmware_vm_1]
    vnc_api_client.read_vn.return_value = vnc_vn_1
    vnc_api_client.get_all_vms.return_value = [vnc_vm]
    vcenter_api_client.get_dpg_by_key.return_value = portgroup
    vrouter_api_client.read_port.return_value = None

    monitor.sync()

    assert len(database.get_all_vm_models()) == 1
    assert len(database.get_all_vn_models()) == 1
    assert len(database.get_all_vmi_models()) == 1

    vnc_api_client.update_vm.assert_called_once()
    vnc_api_client.update_vmi.assert_called_once()
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    vcenter_api_client.get_vlan_id.assert_called_once()

    vrouter_api_client.add_port.assert_called_once()
