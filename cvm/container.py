import dependency_injector.containers as containers
import dependency_injector.providers as providers
import gevent

import cvm.constants as const
from cvm.clients import (ESXiAPIClient, VCenterAPIClient, VNCAPIClient,
                         VRouterAPIClient)
from cvm.controllers import (GuestNetHandler, PowerStateHandler, UpdateHandler,
                             VmReconfiguredHandler, VmRemovedHandler,
                             VmRenamedHandler, VmUpdatedHandler, VmRegisteredHandler,
                             VmwareController, VmwareToolsStatusHandler)
from cvm.database import Database
from cvm.logger import CVMLogger
from cvm.models import VlanIdPool
from cvm.monitors import VMwareMonitor
from cvm.services import (VirtualMachineInterfaceService,
                          VirtualMachineService, VirtualNetworkService,
                          VRouterPortService)


class CVMContainer(containers.DeclarativeContainer):
    """CVM IoC Container"""

    config = providers.Configuration('config')
    database = providers.Singleton(Database)
    vlan_id_pool = providers.Singleton(VlanIdPool, const.VLAN_ID_RANGE_START, const.VLAN_ID_RANGE_END)
    lock = providers.Singleton(gevent.lock.BoundedSemaphore)
    logger = providers.Singleton(CVMLogger, config.sandesh, database, lock)

    esxi_api_client = providers.Singleton(ESXiAPIClient, config.esxi)
    vcenter_api_client = providers.Singleton(VCenterAPIClient, config.vcenter)
    vnc_api_client = providers.Singleton(VNCAPIClient, config.vnc)
    vrouter_api_client = providers.Singleton(VRouterAPIClient)

    vm_service = providers.Factory(VirtualMachineService,
                                   esxi_api_client=esxi_api_client,
                                   vnc_api_client=vnc_api_client,
                                   database=database)
    vn_service = providers.Factory(VirtualNetworkService,
                                   vcenter_api_client=vcenter_api_client,
                                   vnc_api_client=vnc_api_client,
                                   database=database)
    vmi_service = providers.Factory(VirtualMachineInterfaceService,
                                    vcenter_api_client=vcenter_api_client,
                                    vnc_api_client=vnc_api_client,
                                    database=database,
                                    esxi_api_client=esxi_api_client,
                                    vlan_id_pool=vlan_id_pool)
    vrouter_port_service = providers.Factory(VRouterPortService,
                                             vrouter_api_client=vrouter_api_client,
                                             database=database)

    vm_updated_handler = providers.Factory(
        VmUpdatedHandler, vm_service, vn_service, vmi_service, vrouter_port_service
    )
    vm_renamed_handler = providers.Factory(
        VmRenamedHandler, vm_service, vmi_service, vrouter_port_service
    )
    vm_reconfigured_handler = providers.Factory(
        VmReconfiguredHandler, vm_service, vn_service, vmi_service, vrouter_port_service
    )
    vm_removed_handler = providers.Factory(
        VmRemovedHandler, vm_service, vmi_service, vrouter_port_service
    )
    vm_registered_handler = providers.Factory(
        VmRegisteredHandler, vm_service, vn_service, vmi_service, vrouter_port_service
    )
    guest_net_handler = providers.Factory(
        GuestNetHandler, vmi_service, vrouter_port_service
    )
    vmware_tools_status_handler = providers.Factory(
        VmwareToolsStatusHandler, vm_service
    )
    power_state_handler = providers.Factory(PowerStateHandler,
                                            vm_service,
                                            vrouter_port_service)

    update_handler = providers.Factory(UpdateHandler,
                                       vm_updated_handler,
                                       vm_renamed_handler,
                                       vm_reconfigured_handler,
                                       vm_removed_handler,
                                       vm_registered_handler,
                                       guest_net_handler,
                                       vmware_tools_status_handler,
                                       power_state_handler)

    vmware_controller = providers.Factory(VmwareController, vm_service, vn_service,
                                          vmi_service, vrouter_port_service, update_handler, lock)

    vmware_monitor = providers.Factory(VMwareMonitor, esxi_api_client, vmware_controller)
