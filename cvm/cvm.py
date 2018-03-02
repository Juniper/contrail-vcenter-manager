import sys
import yaml
import gevent
import constants as const
from clients import VmwareAPIClient, VNCAPIClient
from controllers import VmwareController
from monitors import VCenterMonitor
from services import VmwareService, VNCService
from database import Database


def load_config():
    with open("../config.yaml", 'r') as ymlfile:
        cfg = yaml.load(ymlfile)
        esxi_cfg = cfg['esxi']
        vnc_cfg = cfg['vnc']
    return esxi_cfg, vnc_cfg


def main():
    esxi_cfg, vnc_cfg = load_config()

    vmware_api_client = VmwareAPIClient(esxi_cfg)
    event_history_collector = vmware_api_client.create_event_history_collector(const.EVENTS_TO_OBSERVE)
    vmware_api_client.add_filter((event_history_collector, ['latestPage']))
    vmware_api_client.make_wait_options(120)

    vnc_api_client = VNCAPIClient(vnc_cfg)

    vnc_service = VNCService(vnc_api_client, Database())
    vmware_service = VmwareService(vmware_api_client)

    vmware_controller = VmwareController(vmware_service, vnc_service)
    vmware_monitor = VCenterMonitor(vmware_api_client, vmware_controller)

    greenlets = [
        gevent.spawn(vmware_monitor.start()),
    ]
    gevent.joinall(greenlets)


if __name__ == '__main__':
    try:
        main()
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(0)
