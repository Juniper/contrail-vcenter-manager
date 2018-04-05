import logging
from unittest import TestCase
from mock import patch, Mock

from pyVmomi import vim, vmodl  # pylint: disable=no-name-in-module

from cvm.controllers import VmwareController

logging.disable(logging.CRITICAL)


def construct_update_set_for_event(event):
    property_change = Mock(name='latestPage', val=event)
    object_update = Mock(changeSet=[property_change])
    property_filter_update = Mock(objectSet=[object_update])
    update_set = Mock(filterSet=[property_filter_update])
    return update_set


class TestVmwareController(TestCase):
    def setUp(self):
        self.database = Mock()
        self.vm_service = Mock(database=self.database)
        self.vmi_service = Mock()
        self.vmware_controller = VmwareController(self.vm_service, None, self.vmi_service)

    @patch.object(VmwareController, '_handle_change')
    def test_handle_update_no_fltr_set(self, mocked_handle_change):
        """ Test handle_update for UpdateSet with no FilterSet. """
        update_set = vmodl.query.PropertyCollector.UpdateSet()

        self.vmware_controller.handle_update(update_set)

        self.assertFalse(mocked_handle_change.called)

    @patch.object(VmwareController, '_handle_change')
    def test_handle_update_no_obj_set(self, mocked_handle_change):
        """ Test handle_update for FilterSet with no ObjectSet. """
        update_set = vmodl.query.PropertyCollector.UpdateSet()
        update_set.filterSet = [vmodl.query.PropertyCollector.FilterUpdate()]

        self.vmware_controller.handle_update(update_set)

        self.assertFalse(mocked_handle_change.called)

    @patch.object(VmwareController, '_handle_change')
    def test_handle_update_no_chng_set(self, mocked_handle_change):
        """ Test handle_update for ObjectSet with no ChangeSet. """
        update_set = vmodl.query.PropertyCollector.UpdateSet()
        filter_update = vmodl.query.PropertyCollector.FilterUpdate()
        filter_update.objectSet = [vmodl.query.PropertyCollector.ObjectUpdate()]
        update_set.filterSet = [filter_update]

        self.vmware_controller.handle_update(update_set)

        self.assertFalse(mocked_handle_change.called)

    def test_handle_update_deleted_vm(self):
        """
        When an event for an already deleted VM is received,
        the controller should do nothing.
        """
        update_set = construct_update_set_for_event(Mock(spec=vim.event.VmCreatedEvent()))
        self.vm_service.update.side_effect = vmodl.fault.ManagedObjectNotFound

        self.vmware_controller.handle_update(update_set)

        self.database.save.assert_not_called()
        self.vmi_service.update_vmis_for_vm_model.assert_not_called()
