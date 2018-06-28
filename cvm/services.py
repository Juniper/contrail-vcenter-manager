import ipaddress
import logging

from cvm.constants import (CONTRAIL_VM_NAME, VLAN_ID_RANGE_END,
                           VLAN_ID_RANGE_START, VNC_ROOT_DOMAIN,
                           VNC_VCENTER_PROJECT)
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel, VlanIdPool)

logger = logging.getLogger(__name__)


def is_contrail_vm_name(name):
    return CONTRAIL_VM_NAME in name


class Service(object):
    def __init__(self, vnc_api_client, database, esxi_api_client=None, vcenter_api_client=None):
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._esxi_api_client = esxi_api_client
        self._vcenter_api_client = vcenter_api_client
        self._project = self._vnc_api_client.read_or_create_project()
        self._default_security_group = self._vnc_api_client.read_or_create_security_group()
        self._ipam = self._vnc_api_client.read_or_create_ipam()
        if self._esxi_api_client:
            self._vrouter_uuid = esxi_api_client.read_vrouter_uuid()

    def _can_delete_from_vnc(self, vnc_obj):
        if vnc_obj.get_type() == 'virtual-machine':
            existing_obj = self._vnc_api_client.read_vm(vnc_obj.uuid)
        if vnc_obj.get_type() == 'virtual-machine-interface':
            existing_obj = self._vnc_api_client.read_vmi(vnc_obj.uuid)
        try:
            existing_obj_vrouter_uuid = next(pair.value
                                             for pair in existing_obj.get_annotations().key_value_pair
                                             if pair.key == 'vrouter-uuid')
        except (AttributeError, StopIteration):
            logger.error('Cannot read vrouter-uuid annotation for %s %s.', vnc_obj.get_type(), vnc_obj.name)
            return False

        if existing_obj_vrouter_uuid == self._vrouter_uuid:
            return True
        logger.error('%s %s is managed by vRouter %s and cannot be deleted from VNC.',
                     vnc_obj.get_type(), vnc_obj.name, existing_obj_vrouter_uuid)
        return False


class VirtualMachineService(Service):
    def __init__(self, esxi_api_client, vnc_api_client, database):
        super(VirtualMachineService, self).__init__(vnc_api_client, database, esxi_api_client=esxi_api_client)

    def update(self, vmware_vm):
        vm_properties = self._esxi_api_client.read_vm_properties(vmware_vm)
        if is_contrail_vm_name(vm_properties['name']):
            return
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if vm_model:
            self._update(vm_model, vmware_vm, vm_properties)
            return
        self._create(vmware_vm, vm_properties)

    def _update(self, vm_model, vmware_vm, vm_properties):
        vm_model.update(vmware_vm, vm_properties)
        for vmi_model in vm_model.vmi_models:
            self._database.vmis_to_update.append(vmi_model)
        self._database.save(vm_model)

    def _create(self, vmware_vm, vm_properties):
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        for vmi_model in vm_model.vmi_models:
            self._database.vmis_to_update.append(vmi_model)
        self._add_property_filter_for_vm(vm_model, ['guest.toolsRunningStatus', 'guest.net'])
        self._vnc_api_client.update_or_create_vm(vm_model.vnc_vm)
        self._database.save(vm_model)

    def _add_property_filter_for_vm(self, vm_model, filters):
        property_filter = self._esxi_api_client.add_filter(vm_model.vmware_vm, filters)
        vm_model.property_filter = property_filter

    def get_vms_from_vmware(self):
        vmware_vms = self._esxi_api_client.get_all_vms()
        for vmware_vm in vmware_vms:
            self.update(vmware_vm)

    def delete_unused_vms_in_vnc(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vnc_vm in vnc_vms:
            vm_model = self._database.get_vm_model_by_uuid(vnc_vm.uuid)
            if vm_model:
                continue
            if self._can_delete_from_vnc(vnc_vm):
                logger.info('Deleting %s from VNC', vnc_vm.name)
                self._vnc_api_client.delete_vm(vnc_vm.uuid)

    def remove_vm(self, name):
        vm_model = self._database.get_vm_model_by_name(name)
        if not vm_model:
            return None
        if self._can_delete_from_vnc(vm_model.vnc_vm):
            self._vnc_api_client.delete_vm(vm_model.vnc_vm.uuid)
        self._database.delete_vm_model(vm_model.uuid)
        vm_model.destroy_property_filter()
        return vm_model

    def set_tools_running_status(self, vmware_vm, value):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if not vm_model:
            return
        vm_model.tools_running_status = value
        logger.info('Tools running status of %s set to %s', vm_model.name, value)
        self._database.save(vm_model)

    def rename_vm(self, old_name, new_name):
        vm_model = self._database.get_vm_model_by_name(old_name)
        vm_model.rename(new_name)
        self._vnc_api_client.update_or_create_vm(vm_model.vnc_vm)
        self._database.save(vm_model)

    def update_vm_models_interfaces(self, vmware_vm):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        old_vmi_models = {vmi_model.uuid: vmi_model for vmi_model in vm_model.vmi_models}
        vm_model.update_ports()
        vm_model.update_vmis()
        new_vmi_models = {vmi_model.uuid: vmi_model for vmi_model in vm_model.vmi_models}

        for uuid, new_vmi_model in new_vmi_models.items():
            old_vmi_models.pop(uuid, None)
            self._database.vmis_to_update.append(new_vmi_model)

        self._database.vmis_to_delete += old_vmi_models.values()


class VirtualNetworkService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, database):
        super(VirtualNetworkService, self).__init__(vnc_api_client, database)
        self._vcenter_api_client = vcenter_api_client

    def update_vns(self):
        for vmi_model in self._database.vmis_to_update:
            portgroup_key = vmi_model.vcenter_port.portgroup_key
            if self._database.get_vn_model_by_key(portgroup_key) is not None:
                continue
            logger.info('Fetching new portgroup for key: %s', portgroup_key)
            with self._vcenter_api_client:
                dpg = self._vcenter_api_client.get_dpg_by_key(portgroup_key)
                fq_name = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, dpg.name]
                vnc_vn = self._vnc_api_client.read_vn(fq_name)
                if dpg and vnc_vn:
                    logger.info('Fetched new portgroup key: %s name: %s', dpg.key, vnc_vn.name)
                    vn_model = VirtualNetworkModel(dpg, vnc_vn,
                                                   VlanIdPool(VLAN_ID_RANGE_START, VLAN_ID_RANGE_END))
                    self._vcenter_api_client.enable_vlan_override(vn_model.vmware_vn)
                    self._database.save(vn_model)
                    logger.info('Successfully saved new portgroup key: %s name: %s', dpg.key, vnc_vn.name)
                else:
                    logger.error('Unable to fetch new portgroup for key: %s', portgroup_key)


class VirtualMachineInterfaceService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, database, esxi_api_client=None):
        super(VirtualMachineInterfaceService, self).__init__(vnc_api_client, database,
                                                             esxi_api_client=esxi_api_client,
                                                             vcenter_api_client=vcenter_api_client)

    def sync_vmis(self):
        self.update_vmis()
        self._delete_unused_vmis()

    def update_vmis(self):
        vmis_to_update = [vmi_model for vmi_model in self._database.vmis_to_update]
        for vmi_model in vmis_to_update:
            self.update_vmis_vn(vmi_model)
            self._database.vmis_to_update.remove(vmi_model)

        for vmi_model in self._database.vmis_to_delete:
            self._delete(vmi_model)

    def update_vmis_vn(self, new_vmi_model):
        old_vmi_model = self._database.get_vmi_model_by_uuid(new_vmi_model.uuid)
        new_vmi_model.vn_model = self._database.get_vn_model_by_key(new_vmi_model.vcenter_port.portgroup_key)
        if old_vmi_model and old_vmi_model.vn_model != new_vmi_model.vn_model:
            self._delete(old_vmi_model)
        self._create_or_update(new_vmi_model)

    def _create_or_update(self, vmi_model):
        with self._vcenter_api_client:
            current_vlan_id = self._vcenter_api_client.get_vlan_id(vmi_model.vcenter_port)
            vmi_model.acquire_vlan_id(current_vlan_id)
            if not current_vlan_id:
                self._vcenter_api_client.set_vlan_id(vmi_model.vcenter_port)
        vmi_model.parent = self._project
        vmi_model.security_group = self._default_security_group
        self._vnc_api_client.update_or_create_vmi(vmi_model.to_vnc())
        vmi_model.construct_instance_ip()
        if vmi_model.vnc_instance_ip:
            instance_ip = self._vnc_api_client.create_and_read_instance_ip(vmi_model.vnc_instance_ip)
            vmi_model.vnc_instance_ip = instance_ip
        self._add_or_update_vrouter_port(vmi_model)
        self._database.save(vmi_model)

    def _delete_unused_vmis(self):
        for vnc_vmi in self._vnc_api_client.get_vmis_by_project(self._project):
            vmi_model = self._database.get_vmi_model_by_uuid(vnc_vmi.get_uuid())
            if vmi_model:
                continue
            if self._can_delete_from_vnc(vnc_vmi):
                logger.info('Deleting %s from VNC.', vnc_vmi.name)
                self._vnc_api_client.delete_vmi(vnc_vmi.get_uuid())

    def _add_or_update_vrouter_port(self, vmi_model):
        self._database.ports_to_update.append(vmi_model)

    def update_nic(self, nic_info):
        vmi_model = self._database.get_vmi_model_by_uuid(VirtualMachineInterfaceModel.get_uuid(nic_info.macAddress))
        try:
            for ip in nic_info.ipAddress:
                if isinstance(ipaddress.ip_address(ip.decode('utf-8')), ipaddress.IPv4Address):
                    vmi_model.ip_address = ip
                    self._vnc_api_client.update_or_create_vmi(vmi_model.to_vnc())
                    logger.info('IP address of %s updated to %s', vmi_model.display_name, ip)
                    self._add_or_update_vrouter_port(vmi_model)
        except AttributeError:
            pass

    def _delete(self, vmi_model):
        with self._vcenter_api_client:
            self._vcenter_api_client.restore_vlan_id(vmi_model.vcenter_port)
            vmi_model.clear_vlan_id()
        self._delete_from_vnc(vmi_model)
        self._restore_vlan_id(vmi_model)
        self._database.delete_vmi_model(vmi_model.uuid)
        self._delete_vrouter_port(vmi_model)

    def _delete_from_vnc(self, vmi_model):
        self._vnc_api_client.delete_vmi(vmi_model.uuid)
        vmi_model.vnc_vmi = None

    def _restore_vlan_id(self, vmi_model):
        with self._vcenter_api_client:
            self._vcenter_api_client.restore_vlan_id(vmi_model.vcenter_port)
        vmi_model.clear_vlan_id()

    def _delete_vrouter_port(self, vmi_model):
        self._database.ports_to_delete.append(vmi_model.uuid)

    def remove_vmis_for_vm_model(self, vm_name):
        vm_model = self._database.get_vm_model_by_name(vm_name)
        if not vm_model:
            return
        vmi_models = self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)
        for vmi_model in vmi_models:
            if self._can_delete_from_vnc(vmi_model.vnc_vmi):
                self._delete_from_vnc(vmi_model)
                self._restore_vlan_id(vmi_model)
            self._database.delete_vmi_model(vmi_model.uuid)
            self._delete_vrouter_port(vmi_model)

    def rename_vmis(self, new_name):
        vm_model = self._database.get_vm_model_by_name(new_name)
        vmi_models = self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)
        for vmi_model in vmi_models:
            vmi_model.vm_model = vm_model
            self._vnc_api_client.update_or_create_vmi(vmi_model.to_vnc())
            self._add_or_update_vrouter_port(vmi_model)

    @staticmethod
    def _get_vn_from_vmi(vnc_vmi):
        return vnc_vmi.get_virtual_network_refs()[0]

    @staticmethod
    def _get_vm_from_vmi(vnc_vmi):
        return vnc_vmi.get_virtual_machine_refs()[0]


class VRouterPortService(object):
    def __init__(self, vrouter_api_client, database):
        self._vrouter_api_client = vrouter_api_client
        self._database = database

    def sync_ports(self):
        self._delete_ports()
        self._update_ports()

    def _delete_ports(self):
        for uuid in self._database.ports_to_delete:
            self._delete_port(uuid)
            self._database.ports_to_delete.remove(uuid)

    def _delete_port(self, uuid):
        self._vrouter_api_client.delete_port(uuid)

    def _update_ports(self):
        ports = [vmi_model for vmi_model in self._database.ports_to_update]
        for vmi_model in ports:
            if self._port_needs_an_update(vmi_model):
                self._update_port(vmi_model)
            self._set_port_state(vmi_model)
            self._database.ports_to_update.remove(vmi_model)

    def _port_needs_an_update(self, vmi_model):
        vrouter_port = self._vrouter_api_client.read_port(vmi_model.uuid)
        if not vrouter_port:
            return True
        return (vrouter_port.get('instance-id') != vmi_model.vm_model.uuid or
                vrouter_port.get('vn-id') != vmi_model.vn_model.uuid or
                vrouter_port.get('rx-vlan-id') != vmi_model.vcenter_port.vlan_id or
                vrouter_port.get('tx-vlan-id') != vmi_model.vcenter_port.vlan_id or
                vrouter_port.get('ip-address') != vmi_model.vnc_instance_ip.instance_ip_address)

    def _update_port(self, vmi_model):
        self._vrouter_api_client.delete_port(vmi_model.uuid)
        self._vrouter_api_client.add_port(vmi_model)

    def _set_port_state(self, vmi_model):
        if vmi_model.vm_model.is_powered_on:
            self._vrouter_api_client.enable_port(vmi_model.uuid)
        else:
            self._vrouter_api_client.disable_port(vmi_model.uuid)
