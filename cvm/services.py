import ipaddress
import logging

from cvm.constants import (VNC_ROOT_DOMAIN, VNC_VCENTER_DEFAULT_SG,
                           VNC_VCENTER_IPAM, VNC_VCENTER_PROJECT)
from cvm.models import VirtualMachineModel, VirtualNetworkModel, VirtualMachineInterfaceModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Service(object):
    def __init__(self, vnc_api_client, database):
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._project = self._create_or_read_project()
        self._default_security_group = self._create_or_read_security_group()
        self._ipam = self._create_or_read_ipam()

    def _create_or_read_project(self):
        project = self._vnc_api_client.construct_project()
        self._vnc_api_client.create_project(project)
        return self._vnc_api_client.read_project([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT])

    def _create_or_read_security_group(self):
        security_group = self._vnc_api_client.construct_security_group(self._project)
        self._vnc_api_client.create_security_group(security_group)
        return self._vnc_api_client.read_security_group([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_DEFAULT_SG])

    def _create_or_read_ipam(self):
        ipam = self._vnc_api_client.construct_ipam(self._project)
        self._vnc_api_client.create_ipam(ipam)
        return self._vnc_api_client.read_ipam([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_IPAM])


class VirtualMachineService(Service):
    def __init__(self, esxi_api_client, vnc_api_client, database):
        super(VirtualMachineService, self).__init__(vnc_api_client, database)
        self._esxi_api_client = esxi_api_client

    def update(self, vmware_vm):
        vm_model = self._get_or_create_vm_model(vmware_vm)
        vm_model.set_vmware_vm(vmware_vm)
        vm_model.vn_models = self._get_vn_models_for_vm(vm_model)
        self._vnc_api_client.update_vm(vm_model.to_vnc())
        self._database.save(vm_model)
        # TODO: vrouter_client.set_active_state(boolean) -- see VirtualMachineInfo.setContrailVmActiveState
        return vm_model

    def sync_vms(self):
        self._get_vms_from_vmware()
        self._delete_unused_vms_in_vnc()

    def _get_vms_from_vmware(self):
        vmware_vms = self._esxi_api_client.get_all_vms()
        for vmware_vm in vmware_vms:
            self.update(vmware_vm)

    def _delete_unused_vms_in_vnc(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vnc_vm in vnc_vms:
            vm_model = self._database.get_vm_model_by_uuid(vnc_vm.uuid)
            if not vm_model:
                logger.info('Deleting %s from VNC (Not really)', vnc_vm.name)
                # This will delete all VMs which are
                # not present in ESXi from VNC!
                # TODO: Uncomment once we have our own VNC
                # self._vnc_api_clinet.delete_vm(vm.uuid)

    def _add_property_filter_for_vm(self, vmware_vm, filters):
        self._esxi_api_client.add_filter(vmware_vm, filters)

    def _get_or_create_vm_model(self, vmware_vm):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if not vm_model:
            vm_model = VirtualMachineModel(vmware_vm)
            self._add_property_filter_for_vm(vmware_vm, ['guest.toolsRunningStatus', 'guest.net'])
        return vm_model

    def _get_vn_models_for_vm(self, vm_model):
        return [self._database.get_vn_model_by_key(dpg.key) for dpg in vm_model.get_distributed_portgroups() if
                self._database.get_vn_model_by_key(dpg.key)]


class VirtualNetworkService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, database):
        super(VirtualNetworkService, self).__init__(vnc_api_client, database)
        self._vcenter_api_client = vcenter_api_client

    def sync_vns(self):
        with self._vcenter_api_client:
            for vn in self._vnc_api_client.get_vns_by_project(self._project):
                dpg = self._vcenter_api_client.get_dpg_by_name(vn.name)
                if vn and dpg:
                    vn_model = VirtualNetworkModel(dpg, vn, self._vcenter_api_client.get_ip_pool_for_dpg(dpg))
                    self._database.save(vn_model)


class VirtualMachineInterfaceService(Service):
    def sync_vmis(self):
        self._get_vmis_from_vnc()
        self._create_new_vmis()
        self._delete_unused_vmis()

    def _get_vmis_from_vnc(self):
        for vmi in self._vnc_api_client.get_vmis_by_project(self._project):
            vm_model = self._database.get_vm_model_by_uuid(self._get_vm_from_vmi(vmi)['uuid'])
            vn_model = self._database.get_vn_model_by_uuid(self._get_vn_from_vmi(vmi)['uuid'])
            if not vm_model or not vn_model:
                return

            vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, self._project, self._default_security_group)
            self._create(vmi_model)

    def _create(self, vmi_model):
        self._vnc_api_client.update_vmi(vmi_model.to_vnc())
        self._add_vrouter_port(vmi_model)
        self._database.save(vmi_model)

    def _create_new_vmis(self):
        for vm_model in self._database.get_all_vm_models():
            self._sync_vmis_for_vm_model(vm_model)

    def _sync_vmis_for_vm_model(self, vm_model):
        for vmi_model in vm_model.construct_vmi_models(self._project, self._default_security_group):
            if not self._database.get_vmi_model_by_mac(vmi_model.mac_address):
                self._create(vmi_model)

    def _delete_unused_vmis(self):
        for vnc_vmi in self._vnc_api_client.get_vmis_by_project(self._project):
            vmi_model = self._database.get_vmi_model_by_mac(
                vnc_vmi.get_virtual_machine_interface_mac_addresses().mac_address[0]
            )
            if not vmi_model:
                logger.info('Deleting %s from VNC.', vnc_vmi.name)
                self._vnc_api_client.delete_vmi(vmi_model.uuid)

    def _add_vrouter_port(self, vmi_model):
        if not vmi_model.vrouter_port_added:
            logger.info('Adding new vRouter port for %s', vmi_model.display_name)
            # TODO: Uncomment once we have working vRouter
            # vrouter_api = VRouterAPIClient(vmi_model.vm_model.vrouter_ip_address, VROUTER_API_PORT)
            # vrouter_api.add_port(vmi_model)
            vmi_model.vrouter_port_added = True
        else:
            logger.info('vRouter port for %s already exists.', vmi_model.display_name)

    def update_nic(self, nic_info):
        vmi_model = self._database.get_vmi_model_by_mac(nic_info.macAddress)
        try:
            for ip in nic_info.ipAddress:
                if isinstance(ipaddress.ip_address(ip.decode('utf-8')), ipaddress.IPv4Address):
                    vmi_model.ip_address = ip
                    self._vnc_api_client.update_vmi(vmi_model.to_vnc())
                    logger.info('IP address of %s updated to %s', vmi_model.display_name, ip)
        except AttributeError:
            pass

    @staticmethod
    def _get_vn_from_vmi(vnc_vmi):
        return vnc_vmi.get_virtual_network_refs()[0]

    @staticmethod
    def _get_vm_from_vmi(vnc_vmi):
        return vnc_vmi.get_virtual_machine_refs()[0]
