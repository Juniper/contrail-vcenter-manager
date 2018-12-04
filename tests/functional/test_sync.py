def test_sync(monitor, database, esxi_api_client, vcenter_api_client, vrouter_api_client, vnc_api_client, vmware_vm_1,
              vmware_vm_2, vnc_vn_1, portgroup, vnc_vm, vnc_vm_2, vm_properties_1, vm_properties_2):
    esxi_api_client.get_all_vms.return_value = [vmware_vm_1, vmware_vm_2]
    esxi_api_client.read_vm_properties.side_effect = [vm_properties_1, vm_properties_2]
    vnc_api_client.read_vn.return_value = vnc_vn_1
    vnc_api_client.get_all_vms.return_value = [vnc_vm, vnc_vm_2]
    vcenter_api_client.get_dpg_by_key.return_value = portgroup
    vrouter_api_client.read_port.return_value = None
    vmware_vm_2.config.hardware.device[0].backing.port.portgroupKey = 'dvportgroup-1'

    monitor.sync()

    assert len(database.get_all_vm_models()) == 2
    assert len(database.get_all_vn_models()) == 1
    assert len(database.get_all_vmi_models()) == 2

    assert vnc_api_client.update_vm.call_count == 2
    assert vnc_api_client.update_vmi.call_count == 2
    assert vnc_api_client.create_and_read_instance_ip.call_count == 2

    assert vcenter_api_client.get_vlan_id.call_count == 2

    assert vrouter_api_client.add_port.call_count == 2
