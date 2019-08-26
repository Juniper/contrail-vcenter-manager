from vnc_api.exceptions import NoIdError


def test_update_create_vm(vnc_api_client, vnc_lib, vnc_vm):
    vnc_api_client.update_vm(vnc_vm)

    vnc_lib.virtual_machine_update.assert_called_once_with(vnc_vm)


def test_update_create_new_vm(vnc_api_client, vnc_lib, vnc_vm):
    vnc_lib.virtual_machine_update.side_effect = NoIdError(None)

    vnc_api_client.update_vm(vnc_vm)

    vnc_lib.virtual_machine_create.called_once_with(vnc_vm)


def test_update_vmi(vnc_api_client, vnc_lib, vnc_vmi_1):
    vnc_lib.virtual_machine_interface_read.return_value = vnc_vmi_1
    vnc_vmi_1.get_instance_ip_back_refs.return_value = [{'to': 'instance-ip-fqname'}]

    vnc_api_client.update_vmi(vnc_vmi_1)

    vnc_lib.virtual_machine_interface_update.assert_called_once_with(vnc_vmi_1)


def test_update_create_new_vmi(vnc_api_client, vnc_lib, vnc_vmi_1):
    vnc_lib.virtual_machine_interface_read.side_effect = [NoIdError(None), vnc_vmi_1]
    vnc_vmi_1.get_instance_ip_back_refs.return_value = [{'to': ['instance-ip-fqname']}]

    vnc_api_client.update_vmi(vnc_vmi_1)

    vnc_lib.virtual_machine_interface_create.assert_called_once_with(vnc_vmi_1)


def test_update_vmi_vn(vnc_api_client, vnc_lib, vnc_vmi_1, vnc_vmi_2, vnc_vn_2):
    vnc_lib.virtual_machine_interface_read.return_value = vnc_vmi_1
    vnc_lib.virtual_network_read.return_value = vnc_vn_2
    vnc_vmi_1.get_instance_ip_back_refs.return_value = [{'to': ['instance-ip-fqname'], 'uuid': 'instance-ip-uuid'}]

    vnc_api_client.update_vmi(vnc_vmi_2)

    vnc_lib.virtual_machine_interface_delete.assert_called_once_with(id=vnc_vmi_1.uuid)
    vnc_lib.virtual_machine_interface_create.assert_called_once_with(vnc_vmi_2)
    vnc_lib.instance_ip_delete.assert_called_once()


def test_dont_update_vmi_vn(vnc_api_client, vnc_lib, vnc_vmi_1, vnc_vn_1):
    vnc_lib.virtual_machine_interface_read.return_value = vnc_vmi_1
    vnc_lib.virtual_network_read.return_value = vnc_vn_1
    vnc_vmi_1.get_instance_ip_back_refs.return_value = [{'to': ['instance-ip-fqname']}]

    vnc_api_client.update_vmi(vnc_vmi_1)

    vnc_vmi_1.set_virtual_network.assert_not_called()
    vnc_lib.virtual_machine_interface_update.assert_called_once_with(vnc_vmi_1)
    vnc_vmi_1.instance_ip_delete.assert_not_called()


def test_get_all_vms(vnc_api_client, vnc_lib, vnc_vm):
    vnc_lib.virtual_machines_list.return_value = {
        u'virtual-machines': [{
            u'fq_name': [u'vm-uuid'],
            u'href': u'http://10.100.0.84:8082/virtual-machine/vm-uuid',
            u'uuid': u'vm-uuid',
        }]
    }
    vnc_lib.virtual_machine_read.return_value = vnc_vm

    all_vms = vnc_api_client.get_all_vms()

    vnc_lib.virtual_machine_read.assert_called_once_with(id=u'vm-uuid')
    assert all_vms == [vnc_vm]


def test_get_vmi_uuids_by_vm_uuid(vnc_api_client, vnc_lib, vnc_vm):
    vnc_lib.virtual_machine_read.return_value = vnc_vm

    vmi_uuids = vnc_api_client.get_vmi_uuids_by_vm_uuid(vnc_vm.uuid)

    assert vmi_uuids == ['vmi-uuid']


def test_read_instance_ip(vnc_api_client, vnc_lib, vmi_model, vnc_vmi_1, instance_ip, vnf_instance_ip):
    vnc_lib.virtual_machine_interface_read.return_value = vnc_vmi_1
    vnc_lib.instance_ip_read.side_effect = [vnf_instance_ip, instance_ip]

    read_instance_ip = vnc_api_client._read_instance_ip(vmi_model)

    assert read_instance_ip == instance_ip
