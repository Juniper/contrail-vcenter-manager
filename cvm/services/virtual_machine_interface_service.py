import ipaddress
import logging
import time

from cvm.models import VirtualMachineInterfaceModel
from cvm.services.service import Service

logger = logging.getLogger(__name__)


class VirtualMachineInterfaceService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, database,
                 esxi_api_client=None, vlan_id_pool=None):
        super(VirtualMachineInterfaceService, self).__init__(vnc_api_client, database,
                                                             esxi_api_client=esxi_api_client,
                                                             vcenter_api_client=vcenter_api_client)
        self._vlan_id_pool = vlan_id_pool

    def sync_vmis(self):
        self.update_vmis()
        with self._vcenter_api_client:
            self._delete_unused_vmis()

    def sync_vlan_ids(self):
        vrouter_uuid = self._esxi_api_client.read_vrouter_uuid()
        with self._vcenter_api_client:
            reserved_vlan_ids = self._vcenter_api_client.get_reserved_vlan_ids(vrouter_uuid)
            for vlan_id in reserved_vlan_ids:
                self._vlan_id_pool.reserve(vlan_id)

    def update_vmis(self, vm_registered=False):
        for vmi_model in list(self._database.vmis_to_update):
            logger.info('Updating %s', vmi_model)
            self._update_vmi(vmi_model, vm_registered=vm_registered)
            self._database.vmis_to_update.remove(vmi_model)
            logger.info('Updated %s', vmi_model)

        for vmi_model in list(self._database.vmis_to_delete):
            self._delete(vmi_model)
            self._database.vmis_to_delete.remove(vmi_model)

    def _update_vmis_vn(self, vmi_model):
        new_vn_model = self._database.get_vn_model_by_key(vmi_model.vcenter_port.portgroup_key)
        if new_vn_model is None:
            with self._vcenter_api_client:
                dpg = self._vcenter_api_client.get_dpg_by_key(vmi_model.vcenter_port.portgroup_key)
                logger.info('Interface of VM: %s is connected to portgroup: %s, which is not handled by Contrail',
                            vmi_model.vm_model.name, dpg.name)
            return

        if vmi_model.vn_model != new_vn_model:
            vmi_model.vn_model = new_vn_model

    def _update_vmi(self, vmi_model, vm_registered=False):
        self._add_default_vnc_info_to(vmi_model)
        self._update_vmis_vn(vmi_model)
        self._assign_vlan_id(vmi_model, vm_registered=vm_registered)
        self._update_in_vnc(vmi_model)
        self._add_instance_ip_to(vmi_model)
        self._update_vrouter_port(vmi_model)
        self._database.save(vmi_model)

    def _assign_vlan_id(self, vmi_model, vm_registered=False):
        with self._vcenter_api_client:
            current_vlan_id = self._vcenter_api_client.get_vlan_id(vmi_model.vcenter_port)
            if vm_registered:
                if current_vlan_id and self._vlan_id_pool.is_available(current_vlan_id):
                    self._preserve_old_vlan_id(current_vlan_id, vmi_model)
                else:
                    self._assign_new_vlan_id(vmi_model)
                return
            if current_vlan_id:
                self._preserve_old_vlan_id(current_vlan_id, vmi_model)
            else:
                self._assign_new_vlan_id(vmi_model)

    def _preserve_old_vlan_id(self, current_vlan_id, vmi_model):
        vmi_model.vcenter_port.vlan_id = current_vlan_id
        self._vlan_id_pool.reserve(current_vlan_id)

    def _assign_new_vlan_id(self, vmi_model):
        vmi_model.vcenter_port.vlan_id = self._vlan_id_pool.get_available()
        # Purpose of this sleep is avoid to race in vmware code
        time.sleep(3)
        self._vcenter_api_client.set_vlan_id(vmi_model.vcenter_port)

    def _add_default_vnc_info_to(self, vmi_model):
        vmi_model.parent = self._project
        vmi_model.security_group = self._default_security_group

    def _update_in_vnc(self, vmi_model):
        self._vnc_api_client.update_vmi(vmi_model.vnc_vmi)

    def _add_instance_ip_to(self, vmi_model):
        vmi_model.construct_instance_ip()
        if vmi_model.vnc_instance_ip:
            instance_ip = self._vnc_api_client.create_and_read_instance_ip(vmi_model.vnc_instance_ip)
            vmi_model.vnc_instance_ip = instance_ip
            vmi_model.update_ip_address(instance_ip.instance_ip_address)

    def _update_vrouter_port(self, vmi_model):
        self._database.ports_to_update.append(vmi_model)

    def _delete_unused_vmis(self):
        for vnc_vmi in self._vnc_api_client.get_vmis_by_project(self._project):
            vmi_model = self._database.get_vmi_model_by_uuid(vnc_vmi.get_uuid())
            if vmi_model:
                continue
            if self._vcenter_api_client.can_remove_vmi(vnc_vmi):
                logger.info('Deleting %s from VNC.', vnc_vmi.name)
                self._vnc_api_client.delete_vmi(vnc_vmi.get_uuid())
            self._delete_vrouter_port(vnc_vmi.get_uuid())

    def update_nic(self, nic_info):
        vmi_model = self._database.get_vmi_model_by_uuid(VirtualMachineInterfaceModel.get_uuid(nic_info.macAddress))
        try:
            for ip_address in nic_info.ipAddress:
                self._update_ip_address(vmi_model, ip_address)
        except AttributeError:
            pass

    def _update_ip_address(self, vmi_model, ip_address):
        if not isinstance(ipaddress.ip_address(ip_address.decode('utf-8')), ipaddress.IPv4Address):
            return
        if vmi_model.is_ip_address_changed(ip_address):
            vmi_model.update_ip_address(ip_address)
            self._add_instance_ip_to(vmi_model)
            logger.info('IP address of %s updated to %s',
                        vmi_model.display_name, vmi_model.vnc_instance_ip.instance_ip_address)

    def _delete(self, vmi_model):
        self._delete_from_vnc(vmi_model)
        self._restore_vlan_id(vmi_model)
        self._database.delete_vmi_model(vmi_model.uuid)
        self._delete_vrouter_port(vmi_model.uuid)

    def _delete_from_vnc(self, vmi_model):
        self._vnc_api_client.delete_vmi(vmi_model.uuid)

    def _restore_vlan_id(self, vmi_model):
        self._restore_vcenter_vlan_id(vmi_model)
        self._vlan_id_pool.free(vmi_model.vcenter_port.vlan_id)

    def _restore_vcenter_vlan_id(self, vmi_model):
        with self._vcenter_api_client:
            self._vcenter_api_client.restore_vlan_id(vmi_model.vcenter_port)

    def _delete_vrouter_port(self, uuid):
        self._database.ports_to_delete.append(uuid)

    def remove_vmis_for_vm_model(self, vm_name):
        vm_model = self._database.get_vm_model_by_name(vm_name)
        if not vm_model:
            return

        with self._vcenter_api_client:
            full_remove = self._vcenter_api_client.can_remove_vm(name=vm_model.name)
        vmi_models = self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)

        for vmi_model in vmi_models:
            if full_remove:
                self._full_remove(vmi_model)
            else:
                self._local_remove(vmi_model)

    def _local_remove(self, vmi_model):
        self._vlan_id_pool.free(vmi_model.vcenter_port.vlan_id)
        self._database.delete_vmi_model(vmi_model.uuid)
        self._delete_vrouter_port(vmi_model.uuid)

    def _full_remove(self, vmi_model):
        self._local_remove(vmi_model)
        self._delete_from_vnc(vmi_model)
        self._restore_vcenter_vlan_id(vmi_model)

    def rename_vmis(self, new_name):
        vm_model = self._database.get_vm_model_by_name(new_name)
        vmi_models = self._database.get_vmi_models_by_vm_uuid(vm_model.uuid)
        with self._vcenter_api_client:
            for vmi_model in vmi_models:
                if self._vcenter_api_client.can_rename_vmi(vmi_model, new_name):
                    self._update_in_vnc(vmi_model)
                self._update_vrouter_port(vmi_model)

    def register_vmis(self):
        for vmi_model in list(self._database.vmis_to_update):
            logger.info('Updating %s', vmi_model)
            self._update_vmi(vmi_model, vm_registered=True)
            self._database.vmis_to_update.remove(vmi_model)
            logger.info('Updated %s', vmi_model)
