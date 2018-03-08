import logging
from models import VirtualMachineModel, VirtualMachineInterfaceModel, VirtualNetworkModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VirtualMachineService(object):
    def __init__(self, vmware_api_client, vnc_api_client, database):
        self._vmware_api_client = vmware_api_client
        self._vnc_api_client = vnc_api_client
        self._database = database

    def update(self, vmware_vm):
        vm_model = VirtualMachineModel(vmware_vm)
        self._vnc_api_client.create_vm(vm_model)
        self._database.save(vm_model)

        for vmware_vn in vmware_vm.network:
            vn_model = self._database.get_vn_model_by_key(vmware_vn.key)
            if vn_model:
                vm_model.networks.append(vn_model)
        # _set_contrail_vm_active_state
        return vm_model

    def sync_vms(self):
        self.get_vms_from_vmware()
        self.delete_unused_vms_in_vnc()

    def get_vms_from_vmware(self):
        vmware_vms = self._vmware_api_client.get_all_vms()
        for vmware_vm in vmware_vms:
            vm_model = self.update(vmware_vm)
            # perhaps a better idea would be to
            # put it in a separate method
            # self._vnc_service.create_vmis_for_vm_model(vm_model)

    def delete_unused_vms_in_vnc(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vnc_vm in vnc_vms:
            vm_model = self._database.get_vm_model_by_uuid(vnc_vm.uuid)
            if not vm_model:
                logger.info('Deleting %s from VNC (Not really)', vnc_vm.name)
                # This will delete all VMs whichare
                # not present in ESXi from VNC!
                # TODO: Uncomment once we have our own VNC
                # self._vnc_api_clinet.delete_vm(vm.uuid)


class VirtualNetworkService(object):
    def __init__(self, vmware_api_client, vnc_api_client, database):
        self._vmware_api_client = vmware_api_client
        self._vnc_api_client = vnc_api_client
        self._database = database
        
    def update(self, vmware_vn):
        vn_model = VirtualNetworkModel(vmware_vn)
        self._vnc_api_client.create_vn(vn_model.to_vnc())
        self._database.save(vn_model)
        return vn_model


class VNCService(object):
    def __init__(self, vnc_api_client, database):
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._project = vnc_api_client.vcenter_project

    def create_vn(self, vmware_vn):
        vn_model = VirtualNetworkModel(vmware_vn, self._project)
        self._vnc_api_client.create_vn(vn_model.to_vnc())
        self._database.save(vn_model)
        return vn_model


    def create_vmis_for_vm_model(self, vm_model):
        try:
            for vn_model in vm_model.networks:
                vmi_model = VirtualMachineInterfaceModel(vm_model, vn_model, self._project)
                self._vnc_api_client.create_vmi(vmi_model.to_vnc())
                self._database.save(vmi_model)
        except Exception, e:
            logger.error(e)

    def sync_vns(self):
        vnc_vns = self._vnc_api_client.get_all_vns()
        for vn in vnc_vns:
            vn_model = self._database.get_vn_model_by_uuid(vn.uuid)
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
