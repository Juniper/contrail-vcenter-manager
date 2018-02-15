import abc
from pyVmomi import vim, vmodl


class Monitor(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, api_client):
        self.api_client = api_client

    @abc.abstractmethod
    def wait_for_changes(self):
        pass


class VCenterMonitor(Monitor):
    _version = ''

    def __init__(self, api_client):
        super(VCenterMonitor, self).__init__(api_client)
        self._property_collector = self.api_client.si.content.propertyCollector
        self._wait_options = vmodl.query.PropertyCollector.WaitOptions()

    def wait_for_changes(self):
        while True:
            update_set = self._property_collector.WaitForUpdatesEx(self._version, self._wait_options)
            if update_set is None:
                continue

            self._version = update_set.version
            return update_set

    def create_event_history_collector(self, events_to_observe):
        event_manager = self.api_client.si.content.eventManager
        event_filter_spec = vim.event.EventFilterSpec()
        event_types = [getattr(vim.event, et) for et in events_to_observe]
        event_filter_spec.type = event_types
        entity_spec = vim.event.EventFilterSpec.ByEntity()
        # TODO: find a way to search for this entity
        entity_spec.entity = self.api_client.si.content.rootFolder.childEntity[0]
        entity_spec.recursion = vim.event.EventFilterSpec.RecursionOption.children
        event_filter_spec.entity = entity_spec
        return event_manager.CreateCollectorForEvents(filter=event_filter_spec)

    def configure_property_collector(self, objects_to_observe):
        filter_spec = vmodl.query.PropertyCollector.FilterSpec()
        filter_spec.objectSet = self._make_object_set(objects_to_observe)
        filter_spec.propSet = self._make_prop_set(objects_to_observe)
        self._property_collector.CreateFilter(filter_spec, True)

    def make_wait_options(self, max_wait_seconds=None, max_object_updates=None):
        if max_object_updates is not None:
            self._wait_options.maxObjectUpdates = max_object_updates
        if max_wait_seconds is not None:
            self._wait_options.maxWaitSeconds = max_wait_seconds

    @staticmethod
    def _make_object_set(objects_to_observe):
        object_set = []
        for obj, _ in objects_to_observe:
            object_set.append(vmodl.query.PropertyCollector.ObjectSpec(obj=obj))
        return object_set

    @staticmethod
    def _make_prop_set(objects_to_observe):
        prop_set = []
        for obj, properties in objects_to_observe:
            property_spec = vmodl.query.PropertyCollector.PropertySpec(
                type=type(obj),
                all=False)
            property_spec.pathSet.extend(properties)
            prop_set.append(property_spec)
        return prop_set
