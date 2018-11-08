import logging

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, vmware_controller, update_set_queue):
        self._controller = vmware_controller
        self._update_set_queue = update_set_queue

    def monitor(self):
        while True:
            update_set = self._update_set_queue.get()
            logger.info('Starting process update set')
            self._controller.handle_update(update_set)
            logger.info('Finished processing update set')
