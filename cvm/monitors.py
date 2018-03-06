class VCenterMonitor:
    def __init__(self, api_client, vmware_controller):
        self.api_client = api_client
        self.vmware_controller = vmware_controller

    def start(self):
        self.vmware_controller.initialize_database()
        while True:
            update_set = self.api_client.wait_for_updates()
            if update_set:
                self.vmware_controller.handle_update(update_set)
