from cvm.models import VirtualMachineInterfaceModel


def test_get_vm_model_by_uuid(database, vm_model):
    database.save(vm_model)

    result = database.get_vm_model_by_uuid('vmware_vm_uuid_1')

    assert result is vm_model
    assert database.get_vm_model_by_uuid('dummy-uuid') is None


def test_delete_vm_model(database, vm_model):
    database.save(vm_model)

    database.delete_vm_model('vmware_vm_uuid_1')
    result = database.get_vm_model_by_uuid('vmware_vm_uuid_1')

    assert result is None


def test_get_vn_model_by_uuid(database, vn_model_1):
    database.save(vn_model_1)

    result = database.get_vn_model_by_uuid('vnc_vn_uuid_1')

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
