from builtins import object
import gc
import traceback
import greenlet
from cfgm_common.uve.greenlets.ttypes import (GreenletObjectReq,
                                              GreenletObject,
                                              GreenletObjectListResp)
from cvm.sandesh.vcenter_manager.ttypes import (VirtualMachineData,
                                                VirtualMachineInterfaceData,
                                                VirtualMachineInterfaceRequest,
                                                VirtualMachineInterfaceResponse,
                                                VirtualMachineRequest,
                                                VirtualMachineResponse,
                                                VirtualNetworkData,
                                                VirtualNetworkRequest,
                                                VirtualNetworkResponse)


class SandeshHandler(object):
    def __init__(self, database, lock):
        self._database = database
        self._lock = lock
        self._converter = SandeshConverter(self._database)

    def bind_handlers(self):
        VirtualMachineRequest.handle_request = self.handle_virtual_machine_request
        VirtualNetworkRequest.handle_request = self.handle_virtual_network_request
        VirtualMachineInterfaceRequest.handle_request = self.handle_virtual_machine_interface_request
        GreenletObjectReq.handle_request = self.handle_greenlet_obj_list_request

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
    def handle_greenlet_obj_list_request(cls, request):
        greenlets = []
        for obj in gc.get_objects():
            if not isinstance(obj, greenlet.greenlet):
                continue
            greenlet_stack = "".join(traceback.format_stack(obj.gr_frame))
            greenlet_name = cls._get_greenlet_name(obj)
            greenlets.append(
                GreenletObject(greenlet_traces=greenlet_stack, greenlet_name=greenlet_name)
            )
        if request.greenlet_name is not None:
            greenlets = [obj for obj in greenlets if obj.greenlet_name == request.greenlet_name]
        response = GreenletObjectListResp(greenlets=greenlets)
        response.response(request.context())

    @classmethod
    def _get_greenlet_name(cls, obj):
        if not hasattr(obj, 'greenlet_name'):
            try:
                greenlet_name = obj._run.__name__
            except AttributeError:
                greenlet_name = 'Anonymous'
        else:
            greenlet_name = obj.greenlet_name
        return greenlet_name


class SandeshConverter(object):
    def __init__(self, database):
        self._database = database

    def convert_vm(self, vm_model):
        vmi_models = self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)
        return VirtualMachineData(
            uuid=vm_model.uuid,
            name=vm_model.name,
            host_uuid=vm_model.host_uuid,
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
