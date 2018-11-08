from mock import Mock
from pyVmomi import vim


def test_vm_created(controller, vcenter_api_client, vnc_api_client, vrouter_api_client,
                    vm_created_update):
    # The VN specified in VMI Model is not present in VNC
    vnc_api_client.read_vn.return_value = None

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # There were no calls to vnc_api
    vnc_api_client.update_vmi.assert_not_called()

    # There were no calls to vCenter
    vcenter_api_client.read_vlan_id.assert_not_called()
    vcenter_api_client.set_vlan_id.assert_not_called()

    # There were no calls to vrouter_api
    vrouter_api_client.add_port.assert_not_called()


def test_vm_reconfigured(controller, vcenter_api_client, vnc_api_client, vrouter_api_client,
                         vm_created_update, vm_reconfigured_update):
    # The VN specified in VMI Model is not present in VNC
    vnc_api_client.read_vn.return_value = None

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    controller.handle_update(vm_reconfigured_update)
    # There were no calls to vnc_api
    vnc_api_client.update_vmi.assert_not_called()

    # There were no calls to vCenter
    vcenter_api_client.read_vlan_id.assert_not_called()
    vcenter_api_client.set_vlan_id.assert_not_called()

    # There were no calls to vrouter_api
    vrouter_api_client.add_port.assert_not_called()


def test_network_change(controller, vcenter_api_client, vnc_api_client, vrouter_api_client,
                        vm_created_update, vm_reconfigured_update, vnc_vn_1, portgroup, vmware_vm_1):
    """
    What happens when we change the VMIs connection from
    Contrail managed network to a non-Contrail one.
    """
    # The first portgroup is present in VNC
    vnc_api_client.read_vn.return_value = vnc_vn_1
    vcenter_api_client.get_dpg_by_key.return_value = portgroup

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    # The second portgroup is not present in VNC
    vnc_api_client.read_vn.return_value = None
    port = Mock(spec=vim.dvs.PortConnection())
    port.portgroupKey = 'dvportgroup-2'
    device = Mock(spec=vim.vm.device.VirtualVmxnet3())
    device.backing.port = port
    device.macAddress = 'mac-address'
    vmware_vm_1.config.hardware.device = [device]

    controller.handle_update(vm_reconfigured_update)

    # The VMI should be deleted
    vnc_api_client.delete_vmi.assert_called_once()

    # VLAN ID should be restored to the default value in vCenter
    vcenter_api_client.restore_vlan_id.assert_called_once()

    # The port should be removed from vRouter
    vrouter_api_client.delete_port.assert_called_once()


def test_vm_powered_on(database, controller, vcenter_api_client, vnc_api_client, vrouter_api_client,
                       vm_created_update, vm_power_on_state_update):
    # The VN specified in VMI Model is not present in VNC
    vnc_api_client.read_vn.return_value = None

    # A new update containing VmCreatedEvent arrives and is being handled by the controller
    controller.handle_update(vm_created_update)

    vm_model = database.get_all_vm_models()[0]
    vm_model.update_power_state('poweredOff')

    controller.handle_update(vm_power_on_state_update)

    # There were no calls to vnc_api
    vnc_api_client.update_vmi.assert_not_called()

    # There were no calls to vCenter
    vcenter_api_client.read_vlan_id.assert_not_called()
    vcenter_api_client.set_vlan_id.assert_not_called()

    # There were no calls to vrouter_api
    vrouter_api_client.add_port.assert_not_called()


def test_sync(controller, database, esxi_api_client, vcenter_api_client, vrouter_api_client, vnc_api_client, vmware_vm_1,
              portgroup, vnc_vm):
    esxi_api_client.get_all_vms.return_value = [vmware_vm_1]
    vnc_api_client.read_vn.return_value = None
    vnc_api_client.get_all_vms.return_value = [vnc_vm]
    vcenter_api_client.get_dpg_by_key.return_value = portgroup
    vrouter_api_client.read_port.return_value = None

    controller.sync()

    assert len(database.get_all_vm_models()) == 1
    assert not database.get_all_vn_models()
    assert not database.get_all_vmi_models()

    vnc_api_client.update_vm.assert_called_once()
    vnc_api_client.update_vmi.assert_not_called()
    vnc_api_client.create_and_read_instance_ip.assert_not_called()

    vcenter_api_client.get_vlan_id.assert_not_called()

    vrouter_api_client.add_port.assert_not_called()
