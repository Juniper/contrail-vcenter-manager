""" Deleting objects in VNC should also delete it's back-ref objects. """


def test_delete_vmi(vnc_api_client, vnc_lib, vnc_vmi_1):
    vnc_vmi_1.get_instance_ip_back_refs.return_value = [{'uuid': 'instance-ip-uuid'}]
    vnc_lib.virtual_machine_interface_read.return_value = vnc_vmi_1

    vnc_api_client.delete_vmi('vmi-uuid-1')

    vnc_lib.instance_ip_delete.assert_called_once_with(id='instance-ip-uuid')
    vnc_lib.virtual_machine_interface_delete.assert_called_once_with(id='vmi-uuid-1')


def test_vmi_no_back_refs(vnc_api_client, vnc_lib, vnc_vmi_1):
    vnc_vmi_1.get_instance_ip_back_refs.return_value = None
    vnc_lib.virtual_machine_interface_read.return_value = vnc_vmi_1

    vnc_api_client.delete_vmi('vmi-uuid-1')

    vnc_lib.instance_ip_delete.assert_not_called()


def test_delete_vm(vnc_api_client, vnc_lib, vnc_vm, vnc_vmi_1):
    vnc_vm.get_virtual_machine_interface_back_refs.return_value = [{'uuid': 'vmi-uuid-1'}]
    vnc_lib.virtual_machine_read.return_value = vnc_vm
    vnc_vmi_1.get_instance_ip_back_refs.return_value = [{'uuid': 'instance-ip-uuid'}]
    vnc_lib.virtual_machine_interface_read.return_value = vnc_vmi_1

    vnc_api_client.delete_vm('vm-uuid')

    vnc_lib.virtual_machine_interface_delete.assert_called_once_with(id='vmi-uuid-1')
    vnc_lib.virtual_machine_delete.assert_called_once_with(id='vm-uuid')


def test_vm_no_back_refs(vnc_api_client, vnc_lib, vnc_vm):
    vnc_vm.get_virtual_machine_interface_back_refs.return_value = None
    vnc_lib.virtual_machine_read.return_value = vnc_vm

    vnc_api_client.delete_vm('vm-uuid')

    vnc_lib.virtual_machine_interface_delete.assert_not_called()
