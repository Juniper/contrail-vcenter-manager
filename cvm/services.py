import logging
from models import VirtualMachineModel, VirtualMachineInterfaceModel, VirtualNetworkModel
from pyVmomi import vim

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VNCService(object):
    def __init__(self, vnc_api_client, database):
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._project = vnc_api_client.vcenter_project

    def create_vm(self, vmware_vm):
        try:
            vm_model = VirtualMachineModel(vmware_vm)
            for vmware_vn in vmware_vm.network:
                if isinstance(vmware_vn, vim.dvs.DistributedVirtualPortgroup):
                    vn_model = self.create_vn(vmware_vn)
                    vm_model.networks.append(vn_model)
            self._vnc_api_client.create_vm(vm_model)
            self._database.save(vm_model)
            # _set_contrail_vm_active_state
            return vm_model
        except Exception, e:
            logger.error(e)

    def update_vm(self, vmware_vm):
        try:
            vm_model = VirtualMachineModel(vmware_vm)
            self._vnc_api_client.update_vm(vm_model)
            self._database.save(vm_model)
        except Exception, e:
            logger.error(e)

    def create_vn(self, vmware_vn):
        try:
            vn_model = VirtualNetworkModel(vmware_vn, self._project)
            self._vnc_api_client.create_vn(vn_model.to_vnc_vn())
            self._database.save(vn_model)
            return vn_model
        except Exception, e:
            logger.error(e)
            raise e

    def create_vmis_for_vm_model(self, vm_model):
        try:
            for vn_model in vm_model.networks:
                vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, self._project)
                self._vnc_api_client.create_vmi(vmi_model.to_vnc_vmi())
                self._database.save(vmi_model)
        except Exception, e:
            logger.error(e)

    def sync_vms(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vm in vnc_vms:
            vm_model = self._database.get_vm_model_by_uuid(vm.uuid)
            if not vm_model:
                # A typo in project name could delete all VMs
                # TODO: Uncomment once we have our own VNC
                # self._vnc_api_client.delete_vm(vm.uuid)
                pass
            else:
                vm_model.vnc_vm = vm

    def sync_vns(self):
        vnc_vns = self._vnc_api_client.get_all_vms()
        for vn in vnc_vns:
            vn_model = self._database.get_vn_model_by_name(vn.name)
            if not vn_model:
                # A typo in project name could delete all VNs
                # TODO: Uncomment once we have our own VNC
                # self._vnc_api_client.delete_vn(vn.uuid)
                pass
            else:
                vn_model.vnc_vn = vn

    def sync_vmis(self):
        vnc_vmis = self._vnc_api_client.get_all_vmis()
        for vmi in vnc_vmis:
            vmi_model = self._database.get_vmi_model_by_uuid(vmi.uuid)
            if not vmi_model:
                # A typo in project name could delete all VMIs
                # TODO: Uncomment once we have our own VNC
                # self._vnc_api_client.delete_vmi(vmi.uuid)
                pass
            else:
                vmi_model.vnc_vmi = vmi
            self._database.save(vmi_model)


class VmwareService(object):
    def __init__(self, vmware_api_client):
        self._vmware_api_client = vmware_api_client

    def add_property_filter_for_vm(self, vmware_vm, filters):
        self._vmware_api_client.add_filter((vmware_vm, filters))

    def get_all_vms(self):
        return self._vmware_api_client.get_all_vms()

    def get_all_vns(self):
        return self._vmware_api_client.get_all_dpgs()
