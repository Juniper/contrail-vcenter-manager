class VCenterMonitor:
    def __init__(self, api_client, vcenter_controller):
        self.api_client = api_client
        self.vcenter_controller = vcenter_controller

    def start(self):
        while True:
            update_set = self.api_client.wait_for_updates()
            if update_set:
                self.vcenter_controller.handle_update(update_set)
