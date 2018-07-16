from mock import Mock, patch


@patch('cvm.services.VRouterPortService._port_needs_an_update', Mock(return_value=True))
def test_create_port(vrouter_port_service, database, vrouter_api_client, vmi_model):
    database.ports_to_update.append(vmi_model)

    vrouter_port_service.sync_ports()

    vrouter_api_client.delete_port.assert_called_once_with(vmi_model.uuid)
    vrouter_api_client.add_port.assert_called_once_with(vmi_model)
    vrouter_api_client.enable_port.assert_called_once_with(vmi_model.uuid)


@patch('cvm.services.VRouterPortService._port_needs_an_update', Mock(return_value=False))
def test_no_update(vrouter_port_service, database, vrouter_api_client, vmi_model):
    database.ports_to_update.append(vmi_model)

    vrouter_port_service.sync_ports()

    vrouter_api_client.delete_port.assert_not_called()
    vrouter_api_client.add_port.assert_not_called()
    assert database.ports_to_update == []


def test_delete_port(vrouter_port_service, database, vrouter_api_client):
    database.ports_to_delete.append('port-uuid')

    vrouter_port_service.sync_ports()

    vrouter_api_client.delete_port.assert_called_once_with('port-uuid')


@patch('cvm.services.VRouterPortService._port_needs_an_update', Mock(return_value=False))
def test_enable_port(vrouter_port_service, database, vrouter_api_client, vmi_model):
    vmi_model.vm_model.update_power_state = True
    database.ports_to_update.append(vmi_model)

    vrouter_port_service.sync_ports()

    vrouter_api_client.enable_port.assert_called_once_with(vmi_model.uuid)
    vrouter_api_client.disable_port.assert_not_called()


@patch('cvm.services.VRouterPortService._port_needs_an_update', Mock(return_value=False))
def test_disable_port(vrouter_port_service, database, vrouter_api_client, vmi_model):
    vmi_model.vm_model.update_power_state = False
    database.ports_to_update.append(vmi_model)

    vrouter_port_service.sync_ports()

    vrouter_api_client.enable_port.assert_called_once_with(vmi_model.uuid)
    vrouter_api_client.disable_port.assert_not_called()
