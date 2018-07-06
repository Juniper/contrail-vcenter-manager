#!/usr/bin/env python

import argparse
import logging
import socket
import sys

import gevent
import yaml

from cfgm_common.uve.nodeinfo.ttypes import NodeStatusUVE, NodeStatus
from pysandesh.connection_info import ConnectionState
from pysandesh.sandesh_base import Sandesh
from sandesh_common.vns.constants import (
        ModuleNames, Module2NodeType, NodeTypeNames, INSTANCE_ID_DEFAULT,
        ServiceHttpPortMap)
from sandesh_common.vns.ttypes import Module



import cvm.constants as const
from cvm.clients import (ESXiAPIClient, VCenterAPIClient, VNCAPIClient,
                         VRouterAPIClient)
from cvm.controllers import (GuestNetHandler, PowerStateHandler, UpdateHandler,
                             VmReconfiguredHandler, VmRemovedHandler,
                             VmRenamedHandler, VmUpdatedHandler,
                             VmwareController, VmwareToolsStatusHandler)
from cvm.database import Database
from cvm.models import VlanIdPool
from cvm.monitors import VMwareMonitor
from cvm.sandesh_handler import SandeshHandler
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService,
                          VRouterPortService)

gevent.monkey.patch_all()


def load_config(config_file):
    with open(config_file, 'r') as ymlfile:
        return yaml.load(ymlfile)


def build_monitor(config, lock, database):
    esxi_cfg, vcenter_cfg, vnc_cfg = config['esxi'], config['vcenter'], config['vnc']

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
        esxi_api_client=esxi_api_client,
        vlan_id_pool=VlanIdPool(const.VLAN_ID_RANGE_START, const.VLAN_ID_RANGE_END)
    )
    vrouter_port_service = VRouterPortService(
        vrouter_api_client=VRouterAPIClient(),
        database=database
    )
    vm_updated_handler = VmUpdatedHandler(vm_service, vn_service, vmi_service, vrouter_port_service)
    vm_renamed_handler = VmRenamedHandler(vm_service, vmi_service, vrouter_port_service)
    vm_reconfigured_handler = VmReconfiguredHandler(vm_service, vn_service,
                                                    vmi_service, vrouter_port_service)
    vm_removed_handler = VmRemovedHandler(vm_service, vmi_service, vrouter_port_service)
    guest_net_handler = GuestNetHandler(vmi_service, vrouter_port_service)
    vmware_tools_status_handler = VmwareToolsStatusHandler(vm_service)
    power_state_handler = PowerStateHandler(vm_service, vrouter_port_service)
    handlers = [
        vm_updated_handler,
        vm_renamed_handler,
        vm_reconfigured_handler,
        vm_removed_handler,
        guest_net_handler,
        vmware_tools_status_handler,
        power_state_handler,
    ]
    update_handler = UpdateHandler(handlers)
    vmware_controller = VmwareController(vm_service, vn_service,
                                         vmi_service, vrouter_port_service, update_handler, lock)
    return VMwareMonitor(esxi_api_client, vmware_controller)


def run_introspect(cfg, database, lock):
    sandesh_config = cfg['sandesh']
    sandesh_config.update({
        'id': Module.VCENTER_MANAGER,
        'hostname': socket.gethostname(),
        'table': 'ObjectContrailvCenterManagerNode',
        'instance_id': INSTANCE_ID_DEFAULT,
    })
    sandesh_config['name'] = ModuleNames[sandesh_config['id']]
    sandesh_config['node_type'] = Module2NodeType[sandesh_config['id']]
    sandesh_config['node_type_name'] = NodeTypeNames[sandesh_config['node_type']]
    sandesh_config['introspect_port'] = ServiceHttpPortMap[sandesh_config['name']]

    sandesh = Sandesh()
    sandesh_handler = SandeshHandler(database, lock)
    sandesh_handler.bind_handlers()
    sandesh.init_generator('cvm', sandesh_config['hostname'],
                           sandesh_config['node_type_name'], sandesh_config['instance_id'],
                           sandesh_config['collectors'], 'cvm_context',
                           sandesh_config['introspect_port'], ['cfgm_common', sandesh_config['name']])
    sandesh.sandesh_logger().set_logger_params(
        sandesh.logger(), True, sandesh_config['logging_level'], sandesh_config['log_file'], False, None
    )
    ConnectionState.init(
        sandesh, sandesh_config['hostname'], sandesh_config['name'],
        sandesh_config['instance_id'], staticmethod(ConnectionState.get_conn_state_cb),
        NodeStatusUVE, NodeStatus, sandesh_config['table'])


def main(args):
    database = Database()
    lock = gevent.lock.BoundedSemaphore()
    cfg = load_config(args.config_file)
    vmware_monitor = build_monitor(cfg, lock, database)
    run_introspect(cfg, database, lock)
    vmware_monitor.sync()
    greenlets = [
        gevent.spawn(vmware_monitor.start()),
    ]
    gevent.joinall(greenlets)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", action="store", dest="config_file",
                        default='/etc/contrail/contrail-vcenter-manager/config.yaml')
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
