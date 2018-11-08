import logging

logger = logging.getLogger(__name__)


class VMwareMonitor(object):
    def __init__(self, esxi_api_client, vmware_controller):
        self._esxi_api_client = esxi_api_client
        self._controller = vmware_controller

    def sync(self):
        self._controller.sync()

    def start(self, queue):
        while True:
            update_set = self._esxi_api_client.wait_for_updates()
            queue.put('GOT_EVENTS')
            if update_set:
                self._controller.handle_update(update_set)
            else:
                logger.info('Empty update test')
