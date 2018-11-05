from mock import Mock

from cvm.constants import VM_UPDATE_FILTERS
from cvm.models import VirtualMachineModel
from tests.utils import assert_vm_model_state, create_property_filter


def test_update_new_vm(vm_service, database, vnc_api_client, vmware_vm_1):
    vm_service.update(vmware_vm_1)

    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert_vm_model_state(
        vm_model=vm_model,
        uuid='vmware-vm-uuid-1',
        name='VM1',
        has_ports={'mac-address': 'dvportgroup-1'},
        tools_running=True,
        is_powered_on=True,
    )
    vnc_api_client.update_vm.assert_called_once()


def test_create_property_filter(vm_service, database, esxi_api_client, vmware_vm_1):
    property_filter = create_property_filter(vmware_vm_1, VM_UPDATE_FILTERS)
    esxi_api_client.add_filter.return_value = property_filter

    vm_service.update(vmware_vm_1)

    esxi_api_client.add_filter.assert_called_once_with(vmware_vm_1, VM_UPDATE_FILTERS)
    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert vm_model.property_filter == property_filter


def test_destroy_property_filter(vm_service, database):
    vm_model = Mock(spec=VirtualMachineModel)
    vm_model.configure_mock(name='VM')
    database.save(vm_model)

    vm_service.remove_vm('VM')

    vm_model.destroy_property_filter.assert_called_once()


def test_update_existing_vm(vm_service, database, vnc_api_client, vmware_vm_1, vm_properties_1):
    old_vm_model = Mock(uuid='vmware-vm-uuid-1', vmi_models=[], spec=VirtualMachineModel)
    database.save(old_vm_model)

    vm_service.update(vmware_vm_1)

    new_vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert new_vm_model is old_vm_model
    old_vm_model.update.assert_called_once_with(vmware_vm_1, vm_properties_1)
    vnc_api_client.update_vm.assert_not_called()


def test_sync_vms(vm_service, database, esxi_api_client, vnc_api_client, vmware_vm_1):
    esxi_api_client.get_all_vms.return_value = [vmware_vm_1]

    vm_service.get_vms_from_vmware()

    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert vm_model.devices == vmware_vm_1.config.hardware.device
    assert_vm_model_state(
        vm_model=vm_model,
        uuid='vmware-vm-uuid-1',
        name='VM1',
    )
    vnc_api_client.update_vm.assert_called_once()


def test_sync_no_uuid_vm(vm_service, database, esxi_api_client, vnc_api_client, vmware_vm_1, vmware_vm_no_uuid):
    esxi_api_client.get_all_vms.return_value = [vmware_vm_1, vmware_vm_no_uuid]

    vm_service.get_vms_from_vmware()

    vm_model = database.get_vm_model_by_uuid('vmware-vm-uuid-1')
    assert vm_model.devices == vmware_vm_1.config.hardware.device
    assert_vm_model_state(
        vm_model=vm_model,
        uuid='vmware-vm-uuid-1',
        name='VM1',
    )
    vnc_api_client.update_vm.assert_called_once()


def test_sync_no_vms(vm_service, database, esxi_api_client, vnc_api_client):
    """ Syncing when there's no VMware VMs doesn't update anything. """
    esxi_api_client.get_all_vms.return_value = []
    vnc_api_client.get_all_vms.return_value = []

    vm_service.get_vms_from_vmware()

    assert database.get_all_vm_models() == []
    vnc_api_client.update_vm.assert_not_called()


def test_delete_unused_vms(database, vm_service, vnc_api_client, vcenter_api_client, vnc_vm, vnc_vmi):
    vcenter_api_client.get_all_vms.return_value = []
    vnc_api_client.get_all_vms.side_effect = [[vnc_vm], []]
    vnc_api_client.get_vmis_by_project.side_effect = [[vnc_vmi], []]

    vm_service.delete_unused_vms_in_vnc()
    vm_service.delete_unused_vms_in_vnc()

    vnc_api_client.delete_vm.assert_called_once_with(uuid='vnc-vm-uuid')
    vnc_api_client.delete_vmi.assert_called_once_with(uuid='vnc-vmi-uuid')
    assert 'vnc-vmi-uuid' in database.ports_to_delete


def test_remove_vm(vm_service, database, vcenter_api_client, vnc_api_client, vm_model):
    database.save(vm_model)
    vcenter_api_client.is_vm_removed.return_value = True

    vm_service.remove_vm('VM1')

    assert vm_model not in database.get_all_vm_models()
    vnc_api_client.delete_vm.assert_called_once_with('vmware-vm-uuid-1')


def test_remove_no_vm(vm_service, vnc_api_client):
    """ Remove VM should do nothing when VM doesn't exist in database. """
    vm_service.remove_vm('VM')

    vnc_api_client.delete_vm.assert_not_called()


def test_remove_other_host(vm_service, database, vcenter_api_client, vnc_api_client, vm_model):
    """ We can't remove VMs from VNC if they exist on other host. """
    database.save(vm_model)
    vcenter_api_client.is_vm_removed.return_value = False

    vm_service.remove_vm('VM1')

    vnc_api_client.delete_vm.assert_not_called()


def test_set_tools_running_status(vm_service, database, vm_model, vmware_vm_1):
    database.save(vm_model)

    vm_service.update_vmware_tools_status(vmware_vm_1, 'guestToolsNotRunning')

    assert vm_model.tools_running is False


def test_set_same_tools_status(vm_service, database, vm_model, vmware_vm_1):
    database.save(vm_model)

    vm_service.update_vmware_tools_status(vmware_vm_1, 'guestToolsRunning')

    assert vm_model.tools_running is True


def test_rename_vm(vm_service, database, vcenter_api_client, vnc_api_client, vm_model):
    database.save(vm_model)
    vcenter_api_client.can_rename_vm.return_value = True

    vm_service.rename_vm('VM1', 'VM1-renamed')

    assert vm_model.name == 'VM1-renamed'
    vnc_api_client.update_vm.assert_called_once()


def test_rename_other_host(vm_service, database, vcenter_api_client, vnc_api_client, vm_model):
    database.save(vm_model)
    vcenter_api_client.can_rename_vm.return_value = False

    vm_service.rename_vm('VM1', 'VM1-renamed')

    assert vm_model.name == 'VM1-renamed'
    vnc_api_client.update_vm.assert_not_called()


def test_update_power_state(vm_service, database, vm_model, vmi_model, vmware_vm_1):
    vm_model.vmi_models = [vmi_model]
    database.save(vm_model)

    vm_service.update_power_state(vmware_vm_1, 'poweredOff')

    assert vm_model.is_powered_on is False
    assert vmi_model in database.ports_to_update


def test_update_vlan_on_power_on(vm_service, database, vm_model, vmi_model, vmware_vm_1):
    vm_model.vmi_models = [vmi_model]
    vm_model.update_power_state('poweredOff')
    database.save(vm_model)

    vm_service.update_power_state(vmware_vm_1, 'poweredOn')

    assert vm_model.is_powered_on is True
    assert vmi_model in database.vlans_to_update


def test_update_same_power_state(vm_service, database, vm_model, vmi_model, vmware_vm_1):
    vm_model.vmi_models = [vmi_model]
    database.save(vm_model)

    vm_service.update_power_state(vmware_vm_1, 'poweredOn')

    assert vm_model.is_powered_on is True
    assert vmi_model not in database.ports_to_update
    assert vmi_model not in database.vlans_to_update


def test_set_vm_owner(vm_service, vnc_api_client, vmware_vm_1):
    vm_service.update(vmware_vm_1)

    vnc_vm = vnc_api_client.update_vm.call_args[0][0]
    assert vnc_vm.get_perms2().get_owner() == 'project-uuid'
