from vnc_api.exceptions import NoIdError


def test_update_create_vm(vnc_api_client, vnc_lib, vnc_vm):
    vnc_api_client.update_or_create_vm(vnc_vm)

    vnc_lib.virtual_machine_update.assert_called_once_with(vnc_vm)


def test_update_create_new_vm(vnc_api_client, vnc_lib, vnc_vm):
    vnc_lib.virtual_machine_update.side_effect = NoIdError(None)

    vnc_api_client.update_or_create_vm(vnc_vm)

    vnc_lib.virtual_machine_create.called_once_with(vnc_vm)


def test_update_create_vmi(vnc_api_client, vnc_lib, vnc_vmi):
    vnc_lib.virtual_machine_interface_read.side_effect = NoIdError(None)

    vnc_api_client.update_vmi(vnc_vmi)

    vnc_lib.virtual_machine_interface_create.assert_called_once()


def test_update_create_new_vmi(vnc_api_client, vnc_lib, vnc_vmi):
    vnc_lib.virtual_machine_interface_read.side_effect = NoIdError(None)

    vnc_api_client.update_vmi(vnc_vmi)

    vnc_lib.virtual_machine_interface_create.assert_called_once_with(vnc_vmi)


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
