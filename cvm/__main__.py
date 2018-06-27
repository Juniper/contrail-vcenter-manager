#!/usr/bin/env python

import argparse
import logging
import socket
import sys

import gevent
import yaml

import cvm.constants as const
from cvm.clients import (ESXiAPIClient, VCenterAPIClient, VNCAPIClient,
                         VRouterAPIClient)
from cvm.controllers import (VmReconfiguredHandler, VmRemovedHandler,
                             VmRenamedHandler, VmwareController)
from cvm.database import Database
from cvm.monitors import VMwareMonitor
from cvm.sandesh_handler import SandeshHandler
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService,
                          VRouterPortService)
from pysandesh.sandesh_base import Sandesh

gevent.monkey.patch_all()


def load_config(config_file):
    with open(config_file, 'r') as ymlfile:
        cfg = yaml.load(ymlfile)
        esxi_cfg = cfg['esxi']
        vcenter_cfg = cfg['vcenter']
        vnc_cfg = cfg['vnc']
    return esxi_cfg, vcenter_cfg, vnc_cfg


def build_monitor(config_file, database):
    esxi_cfg, vcenter_cfg, vnc_cfg = load_config(config_file)

    esxi_api_client = ESXiAPIClient(esxi_cfg)
    event_history_collector = esxi_api_client.create_event_history_collector(const.EVENTS_TO_OBSERVE)
    esxi_api_client.add_filter(event_history_collector, ['latestPage'])
    esxi_api_client.make_wait_options(120)

    vcenter_api_client = VCenterAPIClient(vcenter_cfg)

    vnc_api_client = VNCAPIClient(vnc_cfg)

    vm_service = VirtualMachineService(
        esxi_api_client=esxi_api_client,
        vnc_api_client=vnc_api_client,
        database=database
    )

    vn_service = VirtualNetworkService(
        vcenter_api_client=vcenter_api_client,
        vnc_api_client=vnc_api_client,
        database=database
    )

    vmi_service = VirtualMachineInterfaceService(
        vcenter_api_client=vcenter_api_client,
        vnc_api_client=vnc_api_client,
        database=database,
        esxi_api_client=esxi_api_client
    )
    vrouter_port_service = VRouterPortService(
        vrouter_api_client=VRouterAPIClient(),
        database=database
    )
    vm_renamed_handler = VmRenamedHandler(vm_service, vmi_service, vrouter_port_service)
    vm_reconfigured_handler = VmReconfiguredHandler(vm_service, vn_service,
                                                    vmi_service, vrouter_port_service)
    vm_removed_handler = VmRemovedHandler(vm_service, vmi_service, vrouter_port_service)
    handlers = [vm_renamed_handler, vm_reconfigured_handler, vm_removed_handler]
    vmware_controller = VmwareController(vm_service, vn_service,
                                         vmi_service, vrouter_port_service, handlers)
    return VMwareMonitor(esxi_api_client, vmware_controller)


def run_introspect(args, database):
    sandesh = Sandesh()
    sandesh_handler = SandeshHandler(database)
    sandesh_handler.bind_handlers()
    sandesh.init_generator('cvm', socket.gethostname(),
                           'contrail-vcenter-manager', '0', [],
                           'cvm_context', args.introspect_port, ['cvm'])
    sandesh.sandesh_logger().set_logger_params(
        sandesh.logger(), True, 'SYS_INFO', const.LOG_FILE, False, None
    )


def main(args):
    database = Database()
    vmware_monitor = build_monitor(args.config_file, database)
    run_introspect(args, database)
    greenlets = [
        gevent.spawn(vmware_monitor.start()),
    ]
    gevent.joinall(greenlets)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", action="store", dest="config_file",
                        default='/etc/contrail/contrail-vcenter-manager/config.yaml')
    parser.add_argument("-p", type=int, action="store", dest="introspect_port",
                        default=9090)
    parsed_args = parser.parse_args()
    try:
        main(parsed_args)
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        logger = logging.getLogger('cvm')
        logger.critical('', exc_info=True)
        raise
