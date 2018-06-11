from cvm.sandesh.vcenter_manager.ttypes import (
    VirtualMachineRequest, VirtualMachineData, VirtualMachineResponse
)


class SandeshHandler(object):
    def __init__(self, database):
        self._database = database

    def bind_handlers(self):
        VirtualMachineRequest.handle_request = self.handle_virtual_machine_request

    def handle_virtual_machine_request(self, request):
        if request.uuid is None:
            vm_models = self._database.get_all_vm_models()
        else:
            vm_models = [self._database.get_vm_model_by_uuid(request.uuid)]
        virtual_machines_data = [
            VirtualMachineData(vm.uuid, vm.name) for vm in vm_models
        ]
        response = VirtualMachineResponse(virtual_machines_data)
        response.response(request.context())
