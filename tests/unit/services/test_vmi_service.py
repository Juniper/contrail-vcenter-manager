def test_create_vmis_proper_dpg(vmi_service, database, vnc_api_client, vm_model, vmi_model, vn_model_1, vn_model_2):
    """ A new VMI is being created with proper DPG. """
    vmi_model.vcenter_port.portgroup_key = 'dvportgroup-1'
    database.vmis_to_update.append(vmi_model)
    database.save(vn_model_1)
    database.save(vn_model_2)

    vmi_service.update_vmis()

    assert database.get_all_vmi_models() == [vmi_model]
    assert vmi_model.vm_model == vm_model
    assert vmi_model.vn_model == vn_model_1
    assert vmi_model in database.ports_to_update
    assert vmi_model in database.vlans_to_update
    assert 'vnc-vn-uuid-1' in [ref['uuid'] for ref in vmi_model.vnc_vmi.get_virtual_network_refs()]
    vnc_api_client.update_vmi.assert_called_once()


def test_no_update_for_no_dpgs(vmi_service, database, vnc_api_client, vm_model):
    """ No new VMIs are created for VM not connected to any DPG. """
    database.save(vm_model)

    vmi_service.update_vmis()

    assert database.get_all_vmi_models() == []
    assert database.ports_to_update == []
    vnc_api_client.update_vmi.assert_not_called()


def test_update_existing_vmi(vmi_service, database, vnc_api_client, vmi_model, vm_model,
                             vn_model_1, vn_model_2, vmware_vm_1_updated):
    """ Existing VMI is updated when VM changes the DPG to which it is connected. """
    database.save(vm_model)
    database.save(vn_model_1)
    database.save(vn_model_2)
    database.save(vmi_model)
    vm_model.update_interfaces(vmware_vm_1_updated)
    new_vmi_model = vm_model.vmi_models[0]
    database.vmis_to_update.append(new_vmi_model)

    vmi_service.update_vmis()

    assert database.get_all_vmi_models() == [new_vmi_model]
    assert new_vmi_model.vm_model == vm_model
    assert new_vmi_model.vn_model == vn_model_2
    assert 'vnc-vn-uuid-2' in [ref['uuid'] for ref in new_vmi_model.vnc_vmi.get_virtual_network_refs()]
    assert 'vnc-vn-uuid-1' not in [ref['uuid'] for ref in new_vmi_model.vnc_vmi.get_virtual_network_refs()]
    assert new_vmi_model in database.ports_to_update
    vnc_api_client.update_vmi.assert_called_once()


def test_sync_vmis(vmi_service, database, vnc_api_client, vm_model, vn_model_1):
    database.save(vm_model)
    database.save(vn_model_1)
    vmi_model = vm_model.vmi_models[0]
    database.vmis_to_update.append(vmi_model)
    vnc_api_client.get_vmis_by_project.return_value = []

    vmi_service.sync_vmis()

    assert database.get_all_vmi_models() == [vmi_model]
    vnc_api_client.update_vmi.assert_called_once()


def test_syncs_one_vmi_once(vmi_service, database, vnc_api_client, vm_model, vn_model_1):
    database.save(vm_model)
    database.save(vn_model_1)
    database.vmis_to_update.append(vm_model.vmi_models[0])
    vnc_api_client.get_vmis_by_project.return_value = []

    vmi_service.sync_vmis()

    vnc_api_client.update_vmi.assert_called_once()


def test_sync_no_vmis(vmi_service, database, vnc_api_client):
    vnc_api_client.get_vmis_by_project.return_value = []

    vmi_service.sync_vmis()

    assert database.get_all_vmi_models() == []


def test_sync_deletes_unused_vmis(vmi_service, database, vnc_api_client, vcenter_api_client, vnc_vmi):
    vnc_api_client.get_vmis_by_project.return_value = [vnc_vmi]
    vcenter_api_client.can_remove_vmi.side_effect = [True, False]

    vmi_service.sync_vmis()
    vmi_service.sync_vmis()

    vnc_api_client.delete_vmi.assert_called_once()
    assert vnc_vmi.uuid in database.ports_to_delete


def test_remove_vmis_for_vm_model(vmi_service, database, vcenter_api_client, vnc_api_client, vmi_model, vm_model,
                                  vlan_id_pool):
    database.save(vm_model)
    database.save(vmi_model)
    vcenter_api_client.is_vm_removed.return_value = True

    vmi_service.remove_vmis_for_vm_model(vm_model.name)

    assert vmi_model not in database.get_all_vmi_models()
    assert vmi_model.uuid in database.ports_to_delete
    assert vmi_model in database.vlans_to_restore
    vnc_api_client.delete_vmi.assert_called_once_with(vmi_model.uuid)
    assert vlan_id_pool.is_available(vmi_model.vcenter_port.vlan_id)


def test_remove_vmis_other_host(vmi_service, database, vcenter_api_client, vnc_api_client, vmi_model, vm_model,
                                vlan_id_pool):
    """ We can't delete VMIs for VM on other hosts"""
    database.save(vm_model)
    database.save(vmi_model)
    vcenter_api_client.is_vm_removed.return_value = False

    vmi_service.remove_vmis_for_vm_model(vm_model.name)

    assert vmi_model not in database.get_all_vmi_models()
    assert vmi_model.uuid in database.ports_to_delete
    vnc_api_client.delete_vmi.assert_not_called()
    vcenter_api_client.restore_vlan_id.assert_not_called()
    assert vlan_id_pool.is_available(vmi_model.vcenter_port.vlan_id)


def test_remove_vmis_no_vm_model(vmi_service, vnc_api_client):
    """
    When the passed VM Model is None, we can't retrieve its interfaces
    and therefore remove them.
    """
    vmi_service.remove_vmis_for_vm_model('non-existent-VM')

    vnc_api_client.delete_vmi.assert_not_called()


def test_rename_vmis(vmi_service, database, vnc_api_client, vcenter_api_client, vmi_model, vm_model):
    database.save(vmi_model)
    vm_model.rename('VM1-renamed')
    database.save(vm_model)
    vcenter_api_client.can_rename_vmi.side_effect = [True, False]

    vmi_service.rename_vmis('VM1-renamed')
    vmi_service.rename_vmis('VM1-renamed')

    assert vmi_model.display_name == 'vmi-DPG1-VM1-renamed'
    assert vmi_model in database.ports_to_update
    vnc_api_client.update_vmi.assert_called_once()
    vnc_api_client.create_and_read_instance_ip.assert_not_called()


def test_update_nic(vmi_service, database, vmi_model, nic_info):
    vmi_model.vn_model.vnc_vn.external_ipam = True
    database.save(vmi_model)

    vmi_service.update_nic(nic_info)

    assert vmi_model.ip_address == '192.168.100.5'


def test_update_instance_ip(vmi_service, database, vnc_api_client, vmi_model):
    database.save(vmi_model)
    database.save(vmi_model.vm_model)
    database.save(vmi_model.vn_model)
    database.vmis_to_update.append(vmi_model)

    vmi_service.update_vmis()

    assert vmi_model.vnc_instance_ip is not None
    vnc_api_client.create_and_read_instance_ip.assert_called_once_with(vmi_model)
