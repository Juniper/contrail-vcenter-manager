from cvm.services import is_contrail_vm_name


def test_contrail_vm_name():
    contrail_name = 'ContrailVM-datacenter-0.0.0.0'
    regular_name = 'VM1'

    contrail_result = is_contrail_vm_name(contrail_name)
    regular_result = is_contrail_vm_name(regular_name)

    assert contrail_result is True
    assert regular_result is False
