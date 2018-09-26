#!/usr/bin/env python

import argparse
import logging
import random
import socket
import sys

import gevent
import yaml
from cfgm_common.uve.nodeinfo.ttypes import NodeStatus, NodeStatusUVE
from pysandesh.connection_info import ConnectionState
from pysandesh.sandesh_base import Sandesh
from sandesh_common.vns.constants import (INSTANCE_ID_DEFAULT, Module2NodeType,
                                          ModuleNames, NodeTypeNames,
                                          ServiceHttpPortMap)
from sandesh_common.vns.ttypes import Module

import cvm.constants as const
from cvm.clients import (ESXiAPIClient, VCenterAPIClient, VNCAPIClient,
                         VRouterAPIClient)
from cvm.controllers import (GuestNetHandler, PowerStateHandler, UpdateHandler,
                             VmReconfiguredHandler, VmRemovedHandler,
                             VmRenamedHandler, VmUpdatedHandler, VmRegisteredHandler,
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
    esxi_api_client.wait_for_updates()

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
    vm_registered_handler = VmRegisteredHandler(vm_service, vn_service, vmi_service, vrouter_port_service)
    guest_net_handler = GuestNetHandler(vmi_service, vrouter_port_service)
    vmware_tools_status_handler = VmwareToolsStatusHandler(vm_service)
    power_state_handler = PowerStateHandler(vm_service, vrouter_port_service)
    handlers = [
        vm_updated_handler,
        vm_renamed_handler,
        vm_reconfigured_handler,
        vm_removed_handler,
        vm_registered_handler,
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
    sandesh_config['collectors'] = sandesh_config['collectors'].split()
    random.shuffle(sandesh_config['collectors'])
    sandesh_config.update({
        'id': Module.VCENTER_MANAGER,
        'hostname': socket.gethostname(),
        'table': 'ObjectContrailvCenterManagerNode',
        'instance_id': INSTANCE_ID_DEFAULT,
        'introspect_port': ServiceHttpPortMap['contrail-vcenter-manager'],
    })
    sandesh_config['name'] = ModuleNames[sandesh_config['id']]
    sandesh_config['node_type'] = Module2NodeType[sandesh_config['id']]
    sandesh_config['node_type_name'] = NodeTypeNames[sandesh_config['node_type']]

    sandesh = Sandesh()
    sandesh_handler = SandeshHandler(database, lock)
    sandesh_handler.bind_handlers()
    sandesh.init_generator(
        module='cvm',
        source=sandesh_config['hostname'],
        node_type=sandesh_config['node_type_name'],
        instance_id=sandesh_config['instance_id'],
        collectors=sandesh_config['collectors'],
        client_context='cvm_context',
        http_port=sandesh_config['introspect_port'],
        sandesh_req_uve_pkg_list=['cfgm_common', 'cvm']
    )
    sandesh.sandesh_logger().set_logger_params(
        logger=sandesh.logger(),
        enable_local_log=True,
        level=sandesh_config['logging_level'],
        file=sandesh_config['log_file'],
        enable_syslog=False,
        syslog_facility=None
    )
    ConnectionState.init(
        sandesh=sandesh,
        hostname=sandesh_config['hostname'],
        module_id=sandesh_config['name'],
        instance_id=sandesh_config['instance_id'],
        conn_status_cb=staticmethod(ConnectionState.get_conn_state_cb),
        uve_type_cls=NodeStatusUVE,
        uve_data_type_cls=NodeStatus,
        table=sandesh_config['table']
    )


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
