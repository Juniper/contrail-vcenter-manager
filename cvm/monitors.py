import logging

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, esxi_api_client, vmware_controller):
        self._esxi_api_client = esxi_api_client
        self._controller = vmware_controller

    def sync(self):
        self._controller.sync()

    def start(self, update_set_queue):
        while True:
            update_set = update_set_queue.get()
            # logger.info('Starting process update set')
            self._controller.handle_update(update_set)
            # logger.info('Finished procesing update set')
