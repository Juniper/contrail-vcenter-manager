import gc
import traceback
import greenlet
from cvm.sandesh.vcenter_manager.ttypes import (VirtualMachineData,
                                                VirtualMachineInterfaceData,
                                                VirtualMachineInterfaceRequest,
                                                VirtualMachineInterfaceResponse,
                                                VirtualMachineRequest,
                                                VirtualMachineResponse,
                                                VirtualNetworkData,
                                                VirtualNetworkRequest,
                                                VirtualNetworkResponse,
                                                GreenletStack,
                                                GreenletStackListRequest,
                                                GreenletStackListResponse)


class SandeshHandler(object):
    def __init__(self, database, lock):
        self._database = database
        self._lock = lock
        self._converter = SandeshConverter(self._database)

    def bind_handlers(self):
        VirtualMachineRequest.handle_request = self.handle_virtual_machine_request
        VirtualNetworkRequest.handle_request = self.handle_virtual_network_request
        VirtualMachineInterfaceRequest.handle_request = self.handle_virtual_machine_interface_request
        GreenletStackListRequest.handle_request = self.handle_greenlet_stack_list_request

    def handle_virtual_machine_request(self, request):
        with self._lock:
            if request.uuid is not None:
                vm_models = [self._database.get_vm_model_by_uuid(request.uuid)]
            elif request.name is not None:
                vm_models = [self._database.get_vm_model_by_name(request.name)]
            else:
                vm_models = self._database.get_all_vm_models()
            virtual_machines_data = [
                self._converter.convert_vm(vm_model) for vm_model in vm_models if vm_model is not None
            ]
        response = VirtualMachineResponse(virtual_machines_data)
        response.response(request.context())

    def handle_virtual_network_request(self, request):
        with self._lock:
            if request.uuid is not None:
                vn_models = [self._database.get_vn_model_by_uuid(request.uuid)]
            elif request.key is not None:
                vn_models = [self._database.get_vn_model_by_key(request.key)]
            else:
                vn_models = self._database.get_all_vn_models()
            virtual_networks_data = [
                self._converter.convert_vn(vn_model) for vn_model in vn_models if vn_model is not None
            ]
        response = VirtualNetworkResponse(virtual_networks_data)
        response.response(request.context())

    def handle_virtual_machine_interface_request(self, request):
        with self._lock:
            if request.uuid is not None:
                vmi_models = [self._database.get_vmi_model_by_uuid(request.uuid)]
            else:
                vmi_models = self._database.get_all_vmi_models()
            virtual_interfaces_data = [
                self._converter.convert_vmi(vmi_model) for vmi_model in vmi_models if vmi_model is not None
            ]
        response = VirtualMachineInterfaceResponse(virtual_interfaces_data)
        response.response(request.context())

    @classmethod
    def handle_greenlet_stack_list_request(cls, request):
        tracebacks = [
            traceback.format_stack(ob.gr_frame)
            for ob in gc.get_objects() if isinstance(ob, greenlet.greenlet)
        ]
        greenlets = [
            GreenletStack(stack=stack) for stack in tracebacks
        ]
        response = GreenletStackListResponse(greenlets=greenlets)
        response.response(request.context())


class SandeshConverter(object):
    def __init__(self, database):
        self._database = database

    def convert_vm(self, vm_model):
        vmi_models = self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)
        return VirtualMachineData(
            uuid=vm_model.uuid,
            name=vm_model.name,
            hostname=vm_model.host_name,
            interfaces=[self.convert_vmi(vmi_model) for vmi_model in vmi_models]
        )

    def convert_vn(self, vn_model):
        vmi_models = self._database.get_vmi_models_by_vn_uuid(vn_model.uuid)
        return VirtualNetworkData(
            uuid=vn_model.uuid,
            key=vn_model.key,
            name=vn_model.name,
            interfaces=[self.convert_vmi(vmi_model) for vmi_model in vmi_models]
        )

    def convert_vmi(self, vmi_model):
        if vmi_model.vnc_instance_ip is not None:
            ip_address = vmi_model.vnc_instance_ip.instance_ip_address
        if ip_address is None:
            ip_address = '-'
        return VirtualMachineInterfaceData(
            uuid=vmi_model.uuid,
            display_name=vmi_model.display_name,
            mac_address=vmi_model.vcenter_port.mac_address,
            port_key=vmi_model.vcenter_port.port_key,
            ip_address=ip_address,
            vm_uuid=vmi_model.vm_model.uuid,
            vn_uuid=vmi_model.vn_model.uuid,
            vlan_id=vmi_model.vcenter_port.vlan_id,
        )
