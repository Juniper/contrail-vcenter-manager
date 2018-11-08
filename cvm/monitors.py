import logging

from cvm.constants import EVENTS_TO_OBSERVE, WAIT_FOR_UPDATE_TIMEOUT

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, esxi_api_client, database, vmware_controller):
        self._esxi_api_client = esxi_api_client
        self._database = database
        self._controller = vmware_controller

    def start(self, to_supervisor):
        logger.info('Event handling greenlet start working')
        event_history_collector = self._esxi_api_client.create_event_history_collector(EVENTS_TO_OBSERVE)
        self._esxi_api_client.add_filter(event_history_collector, ['latestPage'])
        self._esxi_api_client.make_wait_options(WAIT_FOR_UPDATE_TIMEOUT)
        self._safe_wait_for_update(to_supervisor)
        self._sync()
        while True:
            logger.info('Pre wait for update')
            update_set = self._safe_wait_for_update(to_supervisor)
            logger.info('After wait for update')
            if update_set:
                self._controller.handle_update(update_set)

    def _sync(self):
        self._database.clear_database()
        self._controller.sync()

    def _safe_wait_for_update(self, to_supervisor):
        to_supervisor.put('START_WAIT_FOR_UPDATES')
        update_set = self._esxi_api_client.wait_for_updates()
        to_supervisor.put('AFTER_WAIT_FOR_UPDATES')
        return update_set
