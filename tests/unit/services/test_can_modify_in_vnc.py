from vnc_api.vnc_api import KeyValuePairs, KeyValuePair


def test_vnc_vm_true(vm_service, database, vnc_api_client, vm_model, vnc_vm):
    database.save(vm_model)
    vnc_api_client.read_vm.return_value = vnc_vm

    vm_service.remove_vm(vm_model.name)

    vnc_api_client.delete_vm.assert_called_once()


def test_vnc_vm_false(vm_service, database, vnc_api_client, vm_model, vnc_vm):
    database.save(vm_model)
    vnc_vm.get_annotations().get_key_value_pair()[0].value = 'vrouter-uuid-2'
    vnc_api_client.read_vm.return_value = vnc_vm

    vm_service.remove_vm(vm_model.name)

    vnc_api_client.delete_vm.assert_not_called()


def test_vnc_vmi_true(vmi_service, database, vnc_api_client, vm_model, vmi_model, vnc_vmi):
    database.save(vm_model)
    database.save(vmi_model)
    vnc_api_client.read_vmi.return_value = vnc_vmi

    vmi_service.rename_vmis('VM1')

    vnc_api_client.update_vmi.assert_called_once()


def test_vnc_vmi_false(vmi_service, database, vnc_api_client, vm_model, vmi_model, vnc_vmi):
    database.save(vm_model)
    database.save(vmi_model)
    vnc_vmi.get_annotations().get_key_value_pair()[0].value = 'vrouter-uuid-2'
    vnc_api_client.read_vmi.return_value = vnc_vmi

    vmi_service.rename_vmis('VM1')

    vnc_api_client.update_vmi.assert_not_called()


def test_no_annotations(vm_service, database, vnc_api_client, vm_model, vnc_vm):
    database.save(vm_model)
    vnc_vm.annotations = None
    vnc_api_client.read_vm.return_value = vnc_vm

    vm_service.remove_vm('VM1')

    vnc_api_client.delete_vm.assert_not_called()


def test_no_vrouter_uuid(vm_service, database, vnc_api_client, vm_model, vnc_vm):
    database.save(vm_model)
    vnc_vm.annotations = None
    vnc_vm.set_annotations(KeyValuePairs(
        [KeyValuePair('key', 'value')]))
    vnc_api_client.read_vm.return_value = vnc_vm

    vm_service.remove_vm('VM1')

    vnc_api_client.delete_vm.assert_not_called()
