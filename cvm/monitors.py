import logging
import time

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, vmware_controller, changes_queue):
        self._controller = vmware_controller
        self._changes_queue = changes_queue

    def monitor(self):
        while True:
            logger.info('changes_queue size: %d', int(self._changes_queue.qsize()))
            obj, change, timestamp = self._changes_queue.get()
            logger.info('Change was read from ESXi at: %s and taken to process at: %s diff: %s', timestamp,
                        time.time(), time.time() - timestamp)
            logger.info('Starting process change')
            self._controller.handle_update(obj, change)
            logger.info('Finished processing change')
