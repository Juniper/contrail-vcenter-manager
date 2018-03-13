#!/usr/bin/env python

import sys
import yaml
import gevent
import cvm.constants as const
from cvm.clients import ESXiAPIClient, VNCAPIClient
from cvm.controllers import VmwareController
from cvm.monitors import VCenterMonitor
from cvm.services import VirtualMachineService
from cvm.database import Database


def load_config():
    with open('config.yaml', 'r') as ymlfile:
        cfg = yaml.load(ymlfile)
        esxi_cfg = cfg['esxi']
        vnc_cfg = cfg['vnc']
    return esxi_cfg, vnc_cfg


def main():
    esxi_cfg, vnc_cfg = load_config()

    esxi_api_client = ESXiAPIClient(esxi_cfg)
    event_history_collector = esxi_api_client.create_event_history_collector(const.EVENTS_TO_OBSERVE)
    esxi_api_client.add_filter(event_history_collector, ['latestPage'])
    esxi_api_client.make_wait_options(120)

    vnc_api_client = VNCAPIClient(vnc_cfg)
    database = Database()

    vm_service = VirtualMachineService(esxi_api_client, vnc_api_client, database)
    vmware_controller = VmwareController(vm_service)
    vmware_monitor = VCenterMonitor(esxi_api_client, vmware_controller)

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
