from mock import Mock
from vnc_api import vnc_api


def test_vmi_vrouter_uuid(vnc_api_client, vnc_lib, vnc_vmi):
    vnc_api_client.update_vmi_vrouter_uuid(vnc_vmi, 'vrouter-uuid-2')

    updated_vmi = vnc_lib.virtual_machine_interface_update.call_args[0][0]

    assert 'vrouter-uuid-2' == next(pair.value
                                    for pair in updated_vmi.get_annotations().key_value_pair
                                    if pair.key == 'vrouter-uuid')


def test_vmi_no_vrouter_uuid(vnc_api_client, vnc_lib, vnc_vmi):
    vnc_vmi.annotations = None
    vnc_vmi.get_annotations.side_effect = [None, vnc_api.KeyValuePairs()]
    vnc_api_client.update_vmi_vrouter_uuid(vnc_vmi, 'vrouter-uuid-2')

    updated_vmi = vnc_lib.virtual_machine_interface_update.call_args[0][0]

    assert 'vrouter-uuid-2' == next(pair.value
                                    for pair in updated_vmi.annotations.key_value_pair
                                    if pair.key == 'vrouter-uuid')


def test_inst_ip_vrouter_uuid(vnc_api_client, vnc_lib, instance_ip):
    vnc_api_client.update_instance_ip_vrouter_uuid(instance_ip, 'vrouter-uuid-2')

    updated_instance_ip = vnc_lib.instance_ip_update.call_args[0][0]

    assert 'vrouter-uuid-2' == next(pair.value
                                    for pair in updated_instance_ip.get_annotations().key_value_pair
                                    if pair.key == 'vrouter-uuid')


def test_inst_ip_no_vrouter_uuid(vnc_api_client, vnc_lib):
    instance_ip = Mock(annotations=None)
    instance_ip.get_annotations.side_effect = [None, vnc_api.KeyValuePairs()]
    vnc_api_client.update_vmi_vrouter_uuid(instance_ip, 'vrouter-uuid-2')

    updated_instance_ip = vnc_lib.virtual_machine_interface_update.call_args[0][0]

    assert 'vrouter-uuid-2' == next(pair.value
                                    for pair in updated_instance_ip.annotations.key_value_pair
                                    if pair.key == 'vrouter-uuid')
