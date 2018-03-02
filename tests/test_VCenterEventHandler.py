from unittest import TestCase
from mock import patch
from cvm.controllers import VmwareController
from pyVmomi import vmodl


class TestVCenterEventHandler(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vcenter_event_handler = VmwareController(None)

    @patch.object(VmwareController, '_handle_change')
    def test_handle_update_no_filterSet(self, mocked_handle_change):
        update_set = vmodl.query.PropertyCollector.UpdateSet()
        self.vcenter_event_handler.handle_update(update_set)
        self.assertFalse(mocked_handle_change.called)

    @patch.object(VmwareController, '_handle_change')
    def test_handle_update_no_objectSet(self, mocked_handle_change):
        update_set = vmodl.query.PropertyCollector.UpdateSet()
        update_set.filterSet = [vmodl.query.PropertyCollector.FilterUpdate()]
        self.vcenter_event_handler.handle_update(update_set)
        self.assertFalse(mocked_handle_change.called)

    @patch.object(VmwareController, '_handle_change')
    def test_handle_update_no_changeSet(self, mocked_handle_change):
        update_set = vmodl.query.PropertyCollector.UpdateSet()
        filter_update = vmodl.query.PropertyCollector.FilterUpdate()
        filter_update.objectSet = [vmodl.query.PropertyCollector.ObjectUpdate()]
        update_set.filterSet = [filter_update]
        self.vcenter_event_handler.handle_update(update_set)
        self.assertFalse(mocked_handle_change.called)


if __name__ == '__main__':
    TestCase.main()
