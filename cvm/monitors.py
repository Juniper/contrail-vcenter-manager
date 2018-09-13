from cvm.constants import EVENTS_TO_OBSERVE


class VMwareMonitor(object):
    def __init__(self, esxi_api_client, vmware_controller):
        self._esxi_api_client = esxi_api_client
        self._controller = vmware_controller
        self._configure_esxi_client()

    def sync(self):
        self._controller.initialize_database()

    def start(self):
        while True:
            update_set = self._esxi_api_client.wait_for_updates()
            if update_set:
                self._controller.handle_update(update_set)

    def _configure_esxi_client(self):
        ehc = self._esxi_api_client.create_event_history_collector(EVENTS_TO_OBSERVE)
        self._esxi_api_client.add_filter(ehc, ['latestPage'])
        self._esxi_api_client.make_wait_options(120)
