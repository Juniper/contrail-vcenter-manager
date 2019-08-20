from __future__ import division
from past.utils import old_div
from vnc_api.vnc_api import IdPermsType

EVENTS_TO_OBSERVE = [
    'VmCreatedEvent',
    'VmClonedEvent',
    'VmDeployedEvent',
    'VmPoweredOnEvent',
    'VmPoweredOffEvent',
    'VmSuspendedEvent',
    'VmRenamedEvent',
    'VmMacChangedEvent',
    'VmMacAssignedEvent',
    'VmReconfiguredEvent',
    'VmMigratedEvent',
    'VmRegisteredEvent',
    'VmRemovedEvent',
]

VM_PROPERTY_FILTERS = [
    'config.instanceUuid',
    'name',
    'runtime.powerState',
    'guest.toolsRunningStatus',
    'summary.runtime.host',
]
VM_UPDATE_FILTERS = [
    'guest.toolsRunningStatus',
    'guest.net',
    'runtime.powerState',
]
VNC_ROOT_DOMAIN = 'default-domain'
VNC_VCENTER_PROJECT = 'vCenter'
VNC_VCENTER_IPAM = 'vCenter-ipam'
VNC_VCENTER_IPAM_FQN = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_IPAM]
VNC_VCENTER_DEFAULT_SG = 'default'
VNC_VCENTER_DEFAULT_SG_FQN = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_DEFAULT_SG]

CONTRAIL_VM_NAME = 'ContrailVM'
CONTRAIL_NETWORK = 'VM-PG'

VLAN_ID_RANGE_START = 1
VLAN_ID_RANGE_END = 4095

ID_PERMS_CREATOR = 'vcenter-manager'
ID_PERMS = IdPermsType(creator=ID_PERMS_CREATOR, enable=True)

SET_VLAN_ID_RETRY_LIMIT = 2
WAIT_FOR_PORT_RETRY_TIME = 1  # 1s
WAIT_FOR_PORT_RETRY_LIMIT = int(old_div(30,WAIT_FOR_PORT_RETRY_TIME))  # Timeout after 30s

WAIT_FOR_UPDATE_TIMEOUT = 60
SUPERVISOR_TIMEOUT = 80

HISTORY_COLLECTOR_PAGE_SIZE = 1000

VMFS = 'vmfs'
