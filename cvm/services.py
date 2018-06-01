import ipaddress
import logging

from cvm.constants import VLAN_ID_RANGE_END, VLAN_ID_RANGE_START
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel, VlanIdPool)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Service(object):
    def __init__(self, vnc_api_client, database):
        self._vnc_api_client = vnc_api_client
        self._database = database
        self._project = self._vnc_api_client.read_or_create_project()
        self._default_security_group = self._vnc_api_client.read_or_create_security_group()
        self._ipam = self._vnc_api_client.read_or_create_ipam()


class VirtualMachineService(Service):
    def __init__(self, esxi_api_client, vnc_api_client, database):
        super(VirtualMachineService, self).__init__(vnc_api_client, database)
        self._esxi_api_client = esxi_api_client

    def update(self, vmware_vm):
        vm_properties = self._esxi_api_client.read_vm_properties(vmware_vm)
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if vm_model:
            return self._update(vm_model, vmware_vm, vm_properties)
        return self._create(vmware_vm, vm_properties)

    def _update(self, vm_model, vmware_vm, vm_properties):
        vm_model.update(vmware_vm, vm_properties)
        self._database.save(vm_model)
        return vm_model

    def _create(self, vmware_vm, vm_properties):
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        self._add_property_filter_for_vm(vm_model, ['guest.toolsRunningStatus', 'guest.net'])
        self._vnc_api_client.update_or_create_vm(vm_model.vnc_vm)
        self._database.save(vm_model)
        return vm_model

    def _add_property_filter_for_vm(self, vm_model, filters):
        property_filter = self._esxi_api_client.add_filter(vm_model.vmware_vm, filters)
        vm_model.property_filter = property_filter

    def sync_vms(self):
        self._get_vms_from_vmware()
        # TODO: Find a way to determine which VMs are safe to delete
        # self._delete_unused_vms_in_vnc()

    def _get_vms_from_vmware(self):
        vmware_vms = self._esxi_api_client.get_all_vms()
        for vmware_vm in vmware_vms:
            self.update(vmware_vm)

    def _delete_unused_vms_in_vnc(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vnc_vm in vnc_vms:
            vm_model = self._database.get_vm_model_by_uuid(vnc_vm.uuid)
            if not vm_model:
                logger.info('Deleting %s from VNC', vnc_vm.name)
                self._vnc_api_client.delete_vm(vnc_vm)

    def remove_vm(self, name):
        vm_model = self._database.get_vm_model_by_name(name)
        if not vm_model:
            return None
        if self._can_delete_from_vnc(vm_model):
            self._vnc_api_client.delete_vm(vm_model.vnc_vm)
        self._database.delete_vm_model(vm_model.uuid)
        vm_model.destroy_property_filter()
        return vm_model

    def _can_delete_from_vnc(self, vm_model):
        existing_vm = self._vnc_api_client.read_vm(vm_model.uuid)
        vrouter_uuid = next(pair.value
                            for pair in vm_model.vnc_vm.get_annotations().key_value_pair
                            if pair.key == 'vrouter-uuid')
        if any([pair.key == 'vrouter-uuid' and pair.value == vrouter_uuid
                for pair in existing_vm.get_annotations().key_value_pair]):
            return True
        logger.error('Virtual Machine %s is managed by vRouter %s and cannot be deleted from VNC.' %
                     (vm_model.name, vrouter_uuid))
        return False

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

    def update_vm_models_interface(self, vmware_vm, mac_address, portgroup_key):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        vm_model.update_interface_portgroup_key(mac_address, portgroup_key)


class VirtualNetworkService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, database):
        super(VirtualNetworkService, self).__init__(vnc_api_client, database)
        self._vcenter_api_client = vcenter_api_client

    def sync_vns(self):
        with self._vcenter_api_client:
            for vn in self._vnc_api_client.get_vns_by_project(self._project):
                dpg = self._vcenter_api_client.get_dpg_by_name(vn.name)
                if vn and dpg:
                    vn_model = VirtualNetworkModel(dpg, vn, VlanIdPool(VLAN_ID_RANGE_START, VLAN_ID_RANGE_END))
                    self._vcenter_api_client.enable_vlan_override(vn_model.vmware_vn)
                    self._database.save(vn_model)


class VirtualMachineInterfaceService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, vrouter_api_client, database):
        super(VirtualMachineInterfaceService, self).__init__(vnc_api_client, database)
        self.vrouter_api_client = vrouter_api_client
        self._vcenter_api_client = vcenter_api_client

    def sync_vmis(self):
        self._create_new_vmis()
        # TODO: Find a way to determine which VMIs are safe to delete.
        # self._delete_unused_vmis()

    def _create_new_vmis(self):
        for vm_model in self._database.get_all_vm_models():
            self.update_vmis_for_vm_model(vm_model)

    def update_vmis_for_vm_model(self, vm_model):
        if vm_model.is_contrail_vm:
            return

        existing_vmi_models = {vmi_model.mac_address: vmi_model
                               for vmi_model in self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)}
        for mac_address, portgroup_key in vm_model.interfaces.iteritems():
            existing_vmi_models.pop(mac_address, None)
            self.update_vmis_vn(vm_model.vmware_vm, mac_address, portgroup_key)

        for unused_vmi_model in existing_vmi_models.values():
            self._delete(unused_vmi_model)

    def update_vmis_vn(self, vmware_vm, mac_address, portgroup_key):
        vmi_model = self._database.get_vmi_model_by_uuid(VirtualMachineInterfaceModel.get_uuid(mac_address))
        vn_model = self._database.get_vn_model_by_key(portgroup_key)
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if not vmi_model:
            vmi_model = VirtualMachineInterfaceModel(
                vm_model,
                vn_model,
                self._project,
                self._default_security_group
            )
        if vmi_model.vn_model != vn_model:
            with self._vcenter_api_client:
                self._vcenter_api_client.restore_vlan_id(vmi_model.vn_model.dvs_name, vmi_model.port_key)
            vmi_model.clear_vlan_id()
            vmi_model.vn_model = vn_model
            self._delete(vmi_model)
        self._create_or_update(vmi_model)

    def _create_or_update(self, vmi_model):
        with self._vcenter_api_client:
            vmi_model.refresh_port_key()
            vmi_model.acquire_vlan_id()
            self._vcenter_api_client.set_vlan_id(vmi_model.vn_model.dvs_name, vmi_model.port_key, vmi_model.vlan_id)
        self._vnc_api_client.update_or_create_vmi(vmi_model.to_vnc())
        vmi_model.construct_instance_ip()
        if vmi_model.vnc_instance_ip:
            self._vnc_api_client.delete_instance_ip(uuid=vmi_model.vnc_instance_ip.uuid)
            instance_ip = self._vnc_api_client.create_and_read_instance_ip(vmi_model.vnc_instance_ip)
            vmi_model.vnc_instance_ip = instance_ip
        self._add_or_update_vrouter_port(vmi_model)
        self._database.save(vmi_model)

    def _delete_unused_vmis(self):
        for vnc_vmi in self._vnc_api_client.get_vmis_by_project(self._project):
            vmi_model = self._database.get_vmi_model_by_uuid(vnc_vmi.get_uuid())
            if not vmi_model:
                logger.info('Deleting %s from VNC.', vnc_vmi.name)
                self._vnc_api_client.delete_vmi(vnc_vmi.get_uuid())

    def _add_or_update_vrouter_port(self, vmi_model):
        if vmi_model.vrouter_port_added:
            logger.info('vRouter port for %s already exists. Updating...', vmi_model.mac_address)
            self.vrouter_api_client.delete_port(vmi_model.uuid)
        else:
            logger.info('Adding new vRouter port for %s...', vmi_model.mac_address)
        self.vrouter_api_client.add_port(vmi_model)
        self.vrouter_api_client.enable_port(vmi_model.uuid)
        vmi_model.vrouter_port_added = True

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
        self._delete_from_vnc(vmi_model)
        self._restore_vlan_id(vmi_model)
        self._database.delete_vmi_model(vmi_model.uuid)
        self._delete_vrouter_port(vmi_model)

    def _delete_from_vnc(self, vmi_model):
        if vmi_model.vnc_instance_ip:
            self._vnc_api_client.delete_instance_ip(vmi_model.vnc_instance_ip.uuid)
        self._vnc_api_client.delete_vmi(vmi_model.uuid)

    def _restore_vlan_id(self, vmi_model):
        with self._vcenter_api_client:
            self._vcenter_api_client.restore_vlan_id(vmi_model.vn_model.dvs_name, vmi_model.port_key)
        vmi_model.clear_vlan_id()

    def _can_delete_from_vnc(self, vmi_model):
        existing_vmi = self._vnc_api_client.read_vmi(vmi_model.uuid)
        vrouter_uuid = next(pair.value
                            for pair in vmi_model.vnc_vmi.get_annotations().key_value_pair
                            if pair.key == 'vrouter-uuid')
        if any([pair.key == 'vrouter-uuid' and pair.value == vrouter_uuid
                for pair in existing_vmi.get_annotations().key_value_pair]):
            return True
        logger.error('Virtual Machine Interface %s is managed by vRouter %s and cannot be deleted from VNC.' %
                     (vmi_model.vnc_vmi.display_name, vrouter_uuid))
        return False

    def _delete_vrouter_port(self, vmi_model):
        if vmi_model.vrouter_port_added:
            logger.info('Deleting vRouter port for %s...', vmi_model.display_name)
            self.vrouter_api_client.delete_port(vmi_model.uuid)
            vmi_model.vrouter_port_added = False

    def remove_vmis_for_vm_model(self, vm_name):
        vm_model = self._database.get_vm_model_by_name(vm_name)
        if not vm_model:
            return
        vmi_models = self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)
        for vmi_model in vmi_models:
            if self._can_delete_from_vnc(vmi_model):
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
