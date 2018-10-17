from cvm.constants import ID_PERMS
from cvm.models import VirtualMachineInterfaceModel


def test_to_vnc(vmi_model, project, security_group):
    vmi_model.parent = project
    vmi_model.security_group = security_group

    vnc_vmi = vmi_model.vnc_vmi

    assert vnc_vmi.name == vmi_model.uuid
    assert vnc_vmi.parent_name == project.name
    assert vnc_vmi.display_name == vmi_model.display_name
    assert vnc_vmi.uuid == vmi_model.uuid
    vnc_mac_address = vnc_vmi.virtual_machine_interface_mac_addresses.mac_address
    assert vnc_mac_address == [vmi_model.vcenter_port.mac_address]
    assert vnc_vmi.get_id_perms() == ID_PERMS


def test_construct_instance_ip(vmi_model, project, security_group):
    vmi_model.parent = project
    vmi_model.security_group = security_group
    vmi_model.vn_model.vnc_vn.external_ipam = None

    vmi_model.construct_instance_ip()
    instance_ip = vmi_model.vnc_instance_ip

    assert instance_ip.instance_ip_address is None
    assert instance_ip.virtual_machine_interface_refs[0]['uuid'] == vmi_model.uuid
    expected_uuid = VirtualMachineInterfaceModel.construct_instance_ip_uuid(instance_ip.display_name)
    assert instance_ip.uuid == expected_uuid


def test_update_ip_address(vmi_model):
    check1 = vmi_model.update_ip_address('192.168.100.5')
    vmi_model.update_ip_address('192.168.100.5')
    check2 = vmi_model.update_ip_address('192.168.100.5')

    assert check1 is True
    assert check2 is False
    assert vmi_model.ip_address == '192.168.100.5'
