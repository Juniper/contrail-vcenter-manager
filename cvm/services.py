import ipaddress
import logging

from cvm.constants import (VNC_ROOT_DOMAIN, VNC_VCENTER_DEFAULT_SG,
                           VNC_VCENTER_IPAM, VNC_VCENTER_PROJECT)
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)

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
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if vm_model:
            return self._update(vm_model, vmware_vm)
        return self._create(vmware_vm)
        # TODO: vrouter_client.set_active_state(boolean) -- see VirtualMachineInfo.setContrailVmActiveState

    def _update(self, vm_model, vmware_vm):
        vm_model.set_vmware_vm(vmware_vm)
        if vm_model.interfaces:
            self._database.save(vm_model)
        else:
            self._database.delete_vm_model(vm_model.uuid)
            self._vnc_api_client.delete_vm(vm_model.uuid)
        return vm_model

    def _create(self, vmware_vm):
        vm_model = VirtualMachineModel(vmware_vm)
        if vm_model.interfaces:
            self._add_property_filter_for_vm(vmware_vm, ['guest.toolsRunningStatus', 'guest.net'])
            self._vnc_api_client.update_vm(vm_model.vnc_vm)
            self._database.save(vm_model)
        return vm_model

    def _add_property_filter_for_vm(self, vmware_vm, filters):
        self._esxi_api_client.add_filter(vmware_vm, filters)

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
            if vmi_model.mac_address:
                self._create_or_update(vmi_model)

    def _create_or_update(self, vmi_model):
        self._vnc_api_client.update_vmi(vmi_model.to_vnc())
        self._add_or_update_vrouter_port(vmi_model)
        self._database.save(vmi_model)

    def _create_new_vmis(self):
        for vm_model in self._database.get_all_vm_models():
            self._sync_vmis_for_vm_model(vm_model)

    def _sync_vmis_for_vm_model(self, vm_model):
        for portgroup_key in vm_model.interfaces.values():
            vn_model = self._database.get_vn_model_by_key(portgroup_key)
            vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, self._project, self._default_security_group)
            if not self._database.get_vmi_model_by_uuid(vmi_model.uuid):
                self._create_or_update(vmi_model)

    def _delete_unused_vmis(self):
        for vnc_vmi in self._vnc_api_client.get_vmis_by_project(self._project):
            vmi_model = self._database.get_vmi_model_by_uuid(vnc_vmi.get_uuid())
            if not vmi_model:
                logger.info('Deleting %s from VNC.', vnc_vmi.name)
                self._vnc_api_client.delete_vmi(vnc_vmi.get_uuid())

    def _add_or_update_vrouter_port(self, vmi_model):
        if not vmi_model.vrouter_port_added:
            logger.info('Adding new vRouter port for %s...', vmi_model.mac_address)
            # TODO: Uncomment once we have working vRouter
            # vrouter_api = VRouterAPIClient(vmi_model.vm_model.vrouter_ip_address, VROUTER_API_PORT)
            # vrouter_api.add_port(vmi_model)
        else:
            logger.info('vRouter port for %s already exists. Updating...', vmi_model.mac_address)
            # TODO: Uncomment once we have working vRouter
            # vrouter_api = VRouterAPIClient(vmi_model.vm_model.vrouter_ip_address, VROUTER_API_PORT)
            # vrouter_api.delete_port(vmi_model)
            # vrouter_api.add_port(vmi_model)
        vmi_model.vrouter_port_added = True

    def update_nic(self, nic_info):
        vmi_model = self._database.get_vmi_model_by_uuid(VirtualMachineInterfaceModel.get_uuid(nic_info.macAddress))
        try:
            for ip in nic_info.ipAddress:
                if isinstance(ipaddress.ip_address(ip.decode('utf-8')), ipaddress.IPv4Address):
                    vmi_model.ip_address = ip
                    self._vnc_api_client.update_vmi(vmi_model.to_vnc())
                    logger.info('IP address of %s updated to %s', vmi_model.display_name, ip)
        except AttributeError:
            pass

    def update_vmis_for_vm_model(self, vm_model):
        existing_vmi_models = {vmi_model.mac_address: vmi_model
                               for vmi_model in self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)}
        if vm_model.interfaces:
            for mac_address, portgroup_key in vm_model.interfaces.iteritems():
                vmi_model = existing_vmi_models.pop(mac_address, None)
                vn_model = self._database.get_vn_model_by_key(portgroup_key)
                if not vmi_model:
                    vmi_model = VirtualMachineInterfaceModel(
                        vm_model,
                        vn_model,
                        self._project,
                        self._default_security_group
                    )
                else:
                    vmi_model.vn_model = vn_model
                self._create_or_update(vmi_model)

        for unused_vmi_model in existing_vmi_models.values():
            self._delete(unused_vmi_model)

    def _delete(self, vmi_model):
        self._vnc_api_client.delete_vmi(vmi_model.uuid)
        self._database.delete_vmi_model(vmi_model.uuid)
        self._delete_vrouter_port(vmi_model)

    def _delete_vrouter_port(self, vmi_model):
        if vmi_model.vrouter_port_added:
            logger.info('Deleting vRouter port for %s...', vmi_model.display_name)
            # TODO: Uncomment once we have working vRouter
            # vrouter_api = VRouterAPIClient(vmi_model.vm_model.vrouter_ip_address, VROUTER_API_PORT)
            # vrouter_api.delete_port(vmi_model)
            vmi_model.vrouter_port_added = False

    @staticmethod
    def _get_vn_from_vmi(vnc_vmi):
        return vnc_vmi.get_virtual_network_refs()[0]

    @staticmethod
    def _get_vm_from_vmi(vnc_vmi):
        return vnc_vmi.get_virtual_machine_refs()[0]
