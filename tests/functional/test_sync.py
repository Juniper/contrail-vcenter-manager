def test_sync(monitor, database, esxi_api_client, vcenter_api_client, vrouter_api_client, vnc_api_client, vmware_vm_1,
              vmware_vm_2, vnc_vn_1, portgroup, vnc_vm, vnc_vm_2, vm_properties_1):
    vmware_vm_1.config.instanceUuid = 'vnc-vm-uuid'
    esxi_api_client.get_all_vms.return_value = [vmware_vm_1]
    vcenter_api_client.get_all_vms.return_value = [vmware_vm_1]
    esxi_api_client.read_vm_properties.side_effect = [vm_properties_1]
    vnc_api_client.read_vn.return_value = vnc_vn_1
    vnc_api_client.get_all_vm_uuids.return_value = [vnc_vm.uuid, vnc_vm_2.uuid]
    vnc_api_client.get_vmi_uuids_by_vm_uuid.return_value = ['vmi-uuid-2']
    vcenter_api_client.get_dpg_by_key.return_value = portgroup
    vrouter_api_client.read_port.side_effect = [None, {'id': 'vmi-uuid-2'}]
    vmware_vm_2.config.hardware.device[0].backing.port.portgroupKey = 'dvportgroup-1'

    monitor.sync()

    assert len(database.get_all_vm_models()) == 1
    assert len(database.get_all_vn_models()) == 1
    assert len(database.get_all_vmi_models()) == 1

    vnc_api_client.update_vm.assert_called_once()
    vnc_api_client.update_vmi.assert_called_once()
    vnc_api_client.create_and_read_instance_ip.assert_called_once()

    vnc_api_client.delete_vm.assert_called_once()

    vcenter_api_client.get_vlan_id.assert_called_once()

    vrouter_api_client.add_port.assert_called_once()
    vrouter_api_client.delete_port.assert_called_once_with('vmi-uuid-2')
