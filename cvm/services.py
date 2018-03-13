import logging

from cvm.constants import (VNC_ROOT_DOMAIN, VNC_VCENTER_DEFAULT_SG,
                           VNC_VCENTER_PROJECT)
from cvm.models import VirtualMachineModel, VirtualNetworkModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VirtualMachineService(object):
    def __init__(self, esxi_api_client, vnc_api_client, database):
        self._esxi_api_client = esxi_api_client
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._project = self._create_or_read_project()
        self._default_security_group = self._create_or_read_security_group()

    def update(self, vmware_vm):
        vm_model = self._get_or_create_vm_model(vmware_vm)
        self._vnc_api_client.update_vm(vm_model.to_vnc())

        # VNC VNs already exist in VNC, so we have to look them up
        # each time we update VM, since we don't track VNC VN changes.
        vm_model.vn_models = self._get_vnc_vns_for_vm(vm_model)
        self._database.save(vm_model)
        # TODO: vrouter_client.set_active_state(boolean) -- see VirtualMachineInfo.setContrailVmActiveState
        self._sync_vmis_for_vm_model(vm_model)
        return vm_model

    def sync_vms(self):
        self._get_vms_from_vmware()
        self._delete_unused_vms_in_vnc()

    def _add_property_filter_for_vm(self, vmware_vm, filters):
        self._esxi_api_client.add_filter(vmware_vm, filters)

    def _get_or_create_vm_model(self, vmware_vm):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if not vm_model:
            vm_model = VirtualMachineModel(vmware_vm)
            self._add_property_filter_for_vm(vmware_vm, ['guest.toolsRunningStatus', 'guest.net'])
        return vm_model

    def _get_vnc_vns_for_vm(self, vm_model):
        distributed_portgroups = vm_model.get_distributed_portgroups()
        search_results = [self._vnc_api_client.read_vn(VirtualNetworkModel.get_fq_name(dpg.name))
                          for dpg in distributed_portgroups]
        if None in search_results:
            logger.fatal("One or more VMware Distributed Portgroups are not synchronized with VNC.")
        return [VirtualNetworkModel(vmware_vn, vnc_vn)
                for vmware_vn, vnc_vn in zip(distributed_portgroups, search_results) if vnc_vn]

    def _get_vms_from_vmware(self):
        vmware_vms = self._esxi_api_client.get_all_vms()
        for vmware_vm in vmware_vms:
            self.update(vmware_vm)

    def _sync_vmis_for_vm_model(self, vm_model):
        """ TODO: Unit test this. """
        existing_vnc_vmis = {self._get_vn_from_vmi(vnc_vmi)['uuid']: vnc_vmi
                             for vnc_vmi in self._vnc_api_client.get_vmis_for_vm(vm_model)}

        for vmi_model in vm_model.construct_vmi_models(self._project, self._default_security_group):
            vnc_vmi = existing_vnc_vmis.pop(vmi_model.vn_model.vnc_vn.uuid, None)
            if vnc_vmi:
                vmi_model.uuid = vnc_vmi.uuid
            self._vnc_api_client.update_vmi(vmi_model.to_vnc())

        for vnc_vmi in existing_vnc_vmis.values():
            self._vnc_api_client.delete_vmi(vnc_vmi.uuid)

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

    def _create_or_read_project(self):
        project = self._vnc_api_client.construct_project()
        self._vnc_api_client.create_project(project)
        return self._vnc_api_client.read_project([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT])

    def _create_or_read_security_group(self):
        security_group = self._vnc_api_client.construct_security_group(self._project)
        self._vnc_api_client.create_security_group(security_group)
        return self._vnc_api_client.read_security_group([VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, VNC_VCENTER_DEFAULT_SG])

    @staticmethod
    def _get_vn_from_vmi(vnc_vmi):
        return vnc_vmi.get_virtual_network_refs()[0]
