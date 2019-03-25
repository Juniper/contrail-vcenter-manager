from cvm.models import VirtualMachineInterfaceModel


def test_get_vm_model_by_uuid(database, vm_model):
    database.save(vm_model)

    result = database.get_vm_model_by_uuid('vmware-vm-uuid-1')

    assert result is vm_model
    assert database.get_vm_model_by_uuid('dummy-uuid') is None


def test_get_vm_model_by_old_name(database, vm_model):
    database.save(vm_model)
    old_name = vm_model.name
    new_name = '/vmfs/volumes/23c13506-c7f8ba2b/{0}/{0}.vmx'.format(old_name)
    vm_model.rename(new_name)

    result = database._get_vm_model_by_old_name(old_name)

    assert result is vm_model


def test_delete_vm_model(database, vm_model):
    database.save(vm_model)

    database.delete_vm_model('vmware-vm-uuid-1')
    result = database.get_vm_model_by_uuid('vmware-vm-uuid-1')

    assert result is None


def test_get_vn_model_by_uuid(database, vn_model_1):
    database.save(vn_model_1)

    result = database.get_vn_model_by_uuid('vnc-vn-uuid-1')

    assert result is vn_model_1
    assert database.get_vn_model_by_uuid('dummy-uuid') is None


def test_get_vn_model_by_key(database, vn_model_1):
    database.save(vn_model_1)

    result = database.get_vn_model_by_key('dvportgroup-1')

    assert result is vn_model_1
    assert database.get_vn_model_by_key('dummy-key') is None


def test_delete_vn_model(database, vn_model_1):
    database.save(vn_model_1)

    database.delete_vn_model('dvportgroup-1')

    assert database.get_vn_model_by_key('dvportgroup-1') is None


def test_get_vmi_model_by_uuid(database, vmi_model):
    database.save(vmi_model)

    uuid = VirtualMachineInterfaceModel.get_uuid('mac-address')
    result = database.get_vmi_model_by_uuid(uuid)

    assert result is vmi_model
    assert database.get_vmi_model_by_uuid('dummy-uuid') is None


def test_delete_vmi_model(database, vmi_model):
    database.save(vmi_model)

    uuid = VirtualMachineInterfaceModel.get_uuid('mac-address')
    database.delete_vmi_model(uuid)

    assert database.get_vmi_model_by_uuid(uuid) is None


def test_is_vlan_available_true(database, vmi_model, vmi_model_2):
    database.save(vmi_model)

    result = database.is_vlan_available(vmi_model_2, 2)

    assert result


def test_is_vlan_available_false(database, vmi_model, vmi_model_2):
    vmi_model.vcenter_port.vlan_id = 2
    database.save(vmi_model)

    result = database.is_vlan_available(vmi_model_2, 2)

    assert not result


def test_is_vlan_available_same_vmi(database, vmi_model):
    database.save(vmi_model)

    result = database.is_vlan_available(vmi_model, 1)

    assert result
