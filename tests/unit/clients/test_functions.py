from cvm.clients import make_dv_port_spec


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
