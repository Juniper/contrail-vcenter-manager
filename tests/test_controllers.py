import logging
from unittest import TestCase
from mock import patch

from pyVmomi import vmodl  # pylint: disable=no-name-in-module

from cvm.controllers import VmwareController

logging.disable(logging.CRITICAL)


class TestVmwareController(TestCase):
    def setUp(self):
        self.vmware_controller = VmwareController(None, None)

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
