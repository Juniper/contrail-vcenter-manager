import logging

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, esxi_api_client, vmware_controller):
        self._esxi_api_client = esxi_api_client
        self._controller = vmware_controller

    def sync(self):
        self._controller.sync()

    def start(self, changes_queue):
        while True:
            obj, change = changes_queue.get()
            logger.info('Starting process change')
            self._controller.handle_update(obj, change)
            logger.info('Finished procesing change')
