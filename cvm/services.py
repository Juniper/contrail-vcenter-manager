import logging
from models import VirtualMachineModel, VirtualMachineInterfaceModel, VirtualNetworkModel
from pyVmomi import vim

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VNCService:
    def __init__(self, vnc_api_client, database):
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._project = vnc_api_client.vcenter_project

    def create_vm(self, vmware_vm):
        try:
            vm_model = self._database.get_vm_model_by_name(vmware_vm.name) or VirtualMachineModel(vmware_vm)
            for vmware_vn in vmware_vm.network:
                if isinstance(vmware_vn, vim.dvs.DistributedVirtualPortgroup):
                    vn_model = self.create_vn(vmware_vn)
                    vm_model.networks.append(vn_model)
            self._vnc_api_client.create_vm(vm_model)
            self._database.update(vm_model)
            # _set_contrail_vm_active_state
            return vm_model
        except Exception, e:
            logger.error(e)
            raise e

    def update_vm(self, vmware_vm):
        try:
            vm_model = self._database.get_vm_model_by_name(vmware_vm.name) or VirtualMachineModel(vmware_vm)
            self._vnc_api_client.update_vm(vm_model)
            self._database.update(vm_model)
        except Exception, e:
            logger.error(e)

    def create_vn(self, vmware_vn):
        try:
            vn_model = self._database.get_vm_model_by_name(vmware_vn.config.key) or VirtualNetworkModel(vmware_vn,
                                                                                                        self._project)
            self._vnc_api_client.create_vn(vn_model.to_vnc_vn())
            self._database.update(vn_model)
            return vn_model
        except Exception, e:
            logger.error(e)
            raise e

    def create_virtual_machine_interfaces(self, vm_model):
        try:
            for vn_model in vm_model.networks:
                if not self._database.get_vmi_model(vm_model, vn_model):
                    vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, self._project)
                    self._vnc_api_client.create_vmi(vmi_model.to_vnc_vmi())
                    self._database.update(vmi_model)
        except Exception, e:
            logger.error(e)

    def sync_vms(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vm in vnc_vms:
            vm_model = self._database.get_vm_model_by_uuid(vm.uuid)
            if not vm_model:
                self._vnc_api_client.delete_vm(vm.uuid)
            else:
                vm_model.vnc_vm = vm

    def sync_vns(self):
        vnc_vns = self._vnc_api_client.get_all_vms()
        for vn in vnc_vns:
            vn_model = self._database.get_vn_model_by_name(vn.name)
            if not vn_model:
                self._vnc_api_client.delete_vn(vn.uuid)
            else:
                vn_model.vnc_vn = vn

    def sync_vmis(self):
        vnc_vmis = self._vnc_api_client.get_all_vmis()
        for vmi in vnc_vmis:
            vmi_model = self._database.get_vmi_model_by_uuid(vmi.uuid)
            if not vmi_model:
                self._vnc_api_client.delete_vmi(vmi.uuid)
            else:
                vmi_model.vnc_vmi = vmi
            self._database.update(vmi_model)


class VmwareService:
    def __init__(self, vmware_api_client):
        self._vmware_api_client = vmware_api_client

    def add_property_filter_for_vm(self, vmware_vm, filters):
        self._vmware_api_client.add_filter((vmware_vm, filters))

    def get_all_vms(self):
        return self._vmware_api_client.get_all_vms()

    def get_all_vns(self):
        return self._vmware_api_client.get_all_dpgs()
