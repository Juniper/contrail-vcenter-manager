import logging
import time

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, esxi_api_client, vmware_controller):
        self._esxi_api_client = esxi_api_client
        self._controller = vmware_controller

    def sync(self):
        self._controller.sync()

    def start(self, update_set_queue):
        while True:
            logger.info('update_set_queue size: %d', int(update_set_queue.qsize()))
            update_set, put_time = update_set_queue.get()
            logger.info('Starting process update set')
            logger.info('Update set was put on queue to process on: %s and taken from queue on: %s diff: %s', put_time, time.time(), time.time() - put_time)
            self._controller.handle_update(update_set)
            logger.info('Finished procesing update set')
