import logging

from cvm.constants import EVENTS_TO_OBSERVE, WAIT_FOR_UPDATE_TIMEOUT

logger = logging.getLogger(__name__)


class EventListener(object):
    def __init__(self, controller, update_set_queue, esxi_api_client, database):
        self._controller = controller
        self._esxi_api_client = esxi_api_client
        self._database = database
        self._update_set_queue = update_set_queue

    def listen(self):
        logger.info('Event listener greenlet start working')
        event_history_collector = self._esxi_api_client.create_event_history_collector(EVENTS_TO_OBSERVE)
        self._esxi_api_client.add_filter(event_history_collector, ['latestPage'])
        self._esxi_api_client.make_wait_options(WAIT_FOR_UPDATE_TIMEOUT)
        self._esxi_api_client.wait_for_updates()
        self._sync()
        while True:
            update_set = self._esxi_api_client.wait_for_updates()
            if update_set:
                self._update_set_queue.put(update_set)

    def _sync(self):
        self._database.clear_database()
        self._controller.sync()
