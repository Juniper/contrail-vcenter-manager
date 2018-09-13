from cvm.clients import construct_security_group, make_dv_port_spec
from cvm.constants import VNC_VCENTER_DEFAULT_SG, VNC_VCENTER_DEFAULT_SG_FQN


def test_make_dv_port_spec(dv_port):
    spec = make_dv_port_spec(dv_port, 10)

    assert spec.key == '8'
    assert spec.operation == 'edit'
    assert spec.setting.vlan.vlanId == 10
    assert spec.setting.vlan.inherited is False
    assert spec.configVersion == '1'


def test_make_port_spec_restore(dv_port):
    spec = make_dv_port_spec(dv_port)

    assert spec.key == '8'
    assert spec.operation == 'edit'
    assert spec.setting.vlan.inherited is True
    assert spec.configVersion == '1'


def test_construct_security_group(project):
    sg = construct_security_group(project)

    assert sg.name == VNC_VCENTER_DEFAULT_SG

    sg_fqn = ':'.join(VNC_VCENTER_DEFAULT_SG_FQN)
    assert sg.security_group_entries.policy_rule[0].src_addresses[0].security_group == sg_fqn
    assert sg.security_group_entries.policy_rule[0].dst_addresses[0].security_group == 'local'

    assert sg.security_group_entries.policy_rule[1].src_addresses[0].security_group == 'local'
    assert sg.security_group_entries.policy_rule[1].dst_addresses[0].subnet.ip_prefix == '0.0.0.0'
