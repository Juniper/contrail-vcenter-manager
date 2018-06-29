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

VLAN_ID_RANGE_START = 0
VLAN_ID_RANGE_END = 4095

LOG_FILE = '/var/log/contrail/contrail-vcenter-manager.log'
