import logging

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, esxi_api_client, vmware_controller):
        self._esxi_api_client = esxi_api_client
        self._controller = vmware_controller

    def sync(self):
        self._controller.sync()

    def start(self, to_supervisor, from_supervisor):
        logger.info('Event handling greenlet start working')
        while True:
            from_supervisor.get()
            logger.info('Get permission for wait for updates')
            update_set = self._esxi_api_client.wait_for_updates()
            to_supervisor.put('AFTER_WAIT_FOR_UPDATES')
            if update_set:
                logger.info('Not empty update set')
                self._controller.handle_update(update_set)
            else:
                logger.info('Empty update set')
