import random
import socket

from cfgm_common.uve.nodeinfo.ttypes import NodeStatus, NodeStatusUVE
from pysandesh.connection_info import ConnectionState
from pysandesh.sandesh_base import Sandesh
from sandesh_common.vns.constants import (INSTANCE_ID_DEFAULT, Module2NodeType,
                                          ModuleNames, NodeTypeNames,
                                          ServiceHttpPortMap)
from sandesh_common.vns.ttypes import Module

from cvm.sandesh_handler import SandeshHandler


class CVMLogger(object):
    def __init__(self, sandesh_config, database, lock):
        self._sandesh = Sandesh()
        self._sandesh_config = sandesh_config
        self._configure_sandesh(sandesh_config)
        self._init_sandesh_handler(database, lock)

    def init_sandesh(self):
        self._sandesh.init_generator(
            module='cvm',
            source=self._sandesh_config['hostname'],
            node_type=self._sandesh_config['node_type_name'],
            instance_id=self._sandesh_config['instance_id'],
            collectors=self._sandesh_config['collectors'],
            client_context='cvm_context',
            http_port=self._sandesh_config['introspect_port'],
            sandesh_req_uve_pkg_list=['cfgm_common', 'cvm']
        )
        ConnectionState.init(
            sandesh=self._sandesh,
            hostname=self._sandesh_config['hostname'],
            module_id=self._sandesh_config['name'],
            instance_id=self._sandesh_config['instance_id'],
            conn_status_cb=staticmethod(ConnectionState.get_conn_state_cb),
            uve_type_cls=NodeStatusUVE,
            uve_data_type_cls=NodeStatus,
            table=self._sandesh_config['table']
        )

    def configure_logger(self):
        self._sandesh.sandesh_logger().set_logger_params(
            logger=self._sandesh.logger(),
            enable_local_log=True,
            level=self._sandesh_config['logging_level'],
            file=self._sandesh_config['log_file'],
            enable_syslog=False,
            syslog_facility=None
        )

    def _configure_sandesh(self, sandesh_config):
        self._sandesh_config['collectors'] = sandesh_config['collectors'].split()
        random.shuffle(self._sandesh_config['collectors'])
        self._sandesh_config.update({
            'id': Module.VCENTER_MANAGER,
            'hostname': socket.gethostname(),
            'table': 'ObjectContrailvCenterManagerNode',
            'instance_id': INSTANCE_ID_DEFAULT,
            'introspect_port': ServiceHttpPortMap['contrail-vcenter-manager'],
        })
        self._sandesh_config['name'] = ModuleNames[self._sandesh_config['id']]
        self._sandesh_config['node_type'] = Module2NodeType[self._sandesh_config['id']]
        self._sandesh_config['node_type_name'] = NodeTypeNames[self._sandesh_config['node_type']]

    def _init_sandesh_handler(self, database, lock):
        sandesh_handler = SandeshHandler(database, lock)
        sandesh_handler.bind_handlers()
