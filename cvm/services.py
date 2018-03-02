import logging
from models import VirtualMachineModel, VirtualMachineInterfaceModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VNCService:
    def __init__(self, vnc_api_client, database):
        self._vnc_api_client = vnc_api_client
        self._database = database

    def create_vm(self, vmware_vm):
        try:
            vm_model = self._database.get_vm_model(vmware_vm.name) or VirtualMachineModel(vmware_vm)
            self._vnc_api_client.create_vm(vm_model)
            self._database.save(vm_model)
            # _set_contrail_vm_active_state
            # _read_virtual_machine_interfaces
        except Exception, e:
            logger.error(e)

    def update_vm(self, vmware_vm):
        try:
            vm_model = self._database.get_vm_model(vmware_vm.name) or VirtualMachineModel(vmware_vm)
            self._vnc_api_client.update_vm(vm_model)
            self._database.update(vm_model)
        except Exception, e:
            logger.error(e)

    def create_virtual_machine_interface(self, vmware_vm):
        try:
            vmware_network = vmware_vm.network[0]
            vmi_model = self._database.get_vmi_model(vmware_vm, vmware_network) or \
                        VirtualMachineInterfaceModel(vmware_vm, vmware_network)
            self._vnc_api_client.create_vmi(vmi_model.to_vnc_vmi())
            self._database.save(vmi_model)
        except Exception, e:
            logger.error(e)
        pass


class VmwareService:
    def __init__(self, vmware_api_client):
        self._vmware_api_client = vmware_api_client

    def add_property_filter_for_vm(self, vmware_vm, filters):
        self._vmware_api_client.add_filter((vmware_vm, filters))
