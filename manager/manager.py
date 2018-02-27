import sys
import yaml
import gevent
import constants as const
from clients import VCenterAPIClient, VNCAPIClient
from handlers import VCenterEventHandler
from monitors import VCenterMonitor


class Manager(object):
    def __init__(self, monitor, handler):
        self.monitor = monitor
        self.handler = handler

    def start(self):
        while True:
            update = self.monitor.wait_for_changes()
            self.handler.handle_update(update)


def load_config():
    with open("../config.yaml", 'r') as ymlfile:
        cfg = yaml.load(ymlfile)
        esxi_cfg = cfg['esxi']
        vnc_cfg = cfg['vnc']
    return esxi_cfg, vnc_cfg


def main():
    esxi_cfg, vnc_cfg = load_config()

    vcenter_api_client = VCenterAPIClient(esxi_cfg)
    vnc_api_client = VNCAPIClient(vnc_cfg)

    vcenter_monitor = VCenterMonitor(vcenter_api_client)
    event_history_collector = vcenter_monitor.create_event_history_collector(const.EVENTS_TO_OBSERVE)
    vcenter_monitor.add_filter((event_history_collector, ['latestPage']))
    vcenter_monitor.make_wait_options(120)

    vcenter_event_handler = VCenterEventHandler(vnc_api_client, vcenter_api_client, vcenter_monitor)

    vcenter_manager = Manager(monitor=vcenter_monitor, handler=vcenter_event_handler)

    greenlets = [
        gevent.spawn(vcenter_manager.start()),
    ]
    gevent.joinall(greenlets)


if __name__ == '__main__':
    try:
        main()
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(0)
