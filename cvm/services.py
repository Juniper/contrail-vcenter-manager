import ipaddress
import logging
import time

from pyVmomi import vmodl  # pylint: disable=no-name-in-module
from vnc_api.gen.resource_xsd import PermType2
from cvm.constants import (CONTRAIL_VM_NAME, VM_UPDATE_FILTERS,
                           VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT,
                           WAIT_FOR_PORT_RETRY_TIME, WAIT_FOR_PORT_RETRY_LIMIT,
                           DVS_UNSTABLE_CLUSTER_ERROR)
from cvm.models import (VirtualMachineInterfaceModel, VirtualMachineModel,
                        VirtualNetworkModel)

logger = logging.getLogger(__name__)


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


def wait_for_port(vmi_model):
    logger.info('Waiting for port %s to be ready...', vmi_model.vcenter_port.port_key)
    for _ in xrange(WAIT_FOR_PORT_RETRY_LIMIT):
        try:
            device = next(device for device
                          in vmi_model.vm_model.vmware_vm.config.hardware.device
                          if device.key == vmi_model.vcenter_port.device.key)
            if device.connectable.connected:
                logger.info('DVPort %s is ready.', vmi_model.vcenter_port.port_key)
                return True
        except StopIteration:
            logger.error('No device detected')
            return False
        time.sleep(WAIT_FOR_PORT_RETRY_TIME)
    logger.info('Waiting for port timed out')
    return False


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

    def update_vmis(self):
        for vmi_model in list(self._database.vmis_to_update):
            logger.info('Updating %s', vmi_model)
            self._update_vmi(vmi_model)
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

    def _update_vmi(self, vmi_model):
        self._add_default_vnc_info_to(vmi_model)
        self._update_vmis_vn(vmi_model)
        self._assign_vlan_id(vmi_model)
        self._update_in_vnc(vmi_model)
        self._add_instance_ip_to(vmi_model)
        self._update_vrouter_port(vmi_model)
        self._database.save(vmi_model)

    def _assign_vlan_id(self, vmi_model):
        self._database.vlans_to_update.append(vmi_model)

    def _add_default_vnc_info_to(self, vmi_model):
        vmi_model.parent = self._project
        vmi_model.security_group = self._default_security_group

    def _update_in_vnc(self, vmi_model):
        self._vnc_api_client.update_vmi(vmi_model.vnc_vmi)

    def _add_instance_ip_to(self, vmi_model):
        vmi_model.construct_instance_ip()
        if vmi_model.vnc_instance_ip:
            logger.info('Try to read and create instance_ip for: VMI %s', vmi_model)
            instance_ip = self._vnc_api_client.create_and_read_instance_ip(vmi_model)
            if not instance_ip:
                return
            logger.info('Read instance ip: %s with IP: %s', str(instance_ip), instance_ip.instance_ip_address)
            vmi_model.vnc_instance_ip = instance_ip
            vmi_model.update_ip_address(instance_ip.instance_ip_address)

    def _update_vrouter_port(self, vmi_model):
        self._database.ports_to_update.append(vmi_model)

    def _delete_unused_vmis(self):
        with self._vcenter_api_client:
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
        if not vmi_model:
            return
        if not vmi_model.vn_model.vnc_vn.external_ipam:
            return

        try:
            for ip_address in nic_info.ipAddress:
                self._update_ip_address(vmi_model, ip_address)
        except AttributeError:
            pass

    def _update_ip_address(self, vmi_model, ip_address):
        if not isinstance(ipaddress.ip_address(ip_address.decode('utf-8')), ipaddress.IPv4Address):
            return
        if vmi_model.is_ip_address_changed(ip_address):
            logger.info('Attempting to update %s IP address to: %s', vmi_model, ip_address)
            vmi_model.update_ip_address(ip_address)
            self._add_instance_ip_to(vmi_model)
            logger.info('IP address of %s updated to %s',
                        vmi_model.display_name, vmi_model.vnc_instance_ip.instance_ip_address)
            logger.info('VMI %s after IP update from guest.net', vmi_model)

    def _delete(self, vmi_model):
        self._delete_from_vnc(vmi_model)
        self._restore_vlan_id(vmi_model)
        self._database.delete_vmi_model(vmi_model.uuid)
        self._delete_vrouter_port(vmi_model.uuid)

    def _delete_from_vnc(self, vmi_model):
        self._vnc_api_client.delete_vmi(vmi_model.uuid)

    def _restore_vlan_id(self, vmi_model):
        self._database.vlans_to_restore.append(vmi_model)

    def _delete_vrouter_port(self, uuid):
        self._database.ports_to_delete.append(uuid)

    def remove_vmis_for_vm_model(self, vm_name):
        vm_model = self._database.get_vm_model_by_name(vm_name)
        if not vm_model:
            return

        with self._vcenter_api_client:
            full_remove = self._vcenter_api_client.is_vm_removed(vm_model.name)
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
        self._restore_vlan_id(vmi_model)

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
            self._update_vmi(vmi_model)
            self._database.vmis_to_update.remove(vmi_model)
            logger.info('Updated %s', vmi_model)


class VirtualMachineService(Service):
    def __init__(self, esxi_api_client, vcenter_api_client, vnc_api_client, database):
        super(VirtualMachineService, self).__init__(vnc_api_client, database,
                                                    esxi_api_client=esxi_api_client,
                                                    vcenter_api_client=vcenter_api_client)

    def update(self, vmware_vm):
        vm_properties = self.get_vm_vmware_properties(vmware_vm)
        if is_contrail_vm_name(vm_properties['name']):
            return
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if vm_model:
            self._update(vm_model, vmware_vm, vm_properties)
            return
        self._create(vmware_vm, vm_properties)

    def get_vm_vmware_properties(self, vmware_vm):
        return self._esxi_api_client.read_vm_properties(vmware_vm)

    def get_vm_model_by_uuid(self, vm_uuid):
        return self._database.get_vm_model_by_uuid(vm_uuid)

    def get_vm_model_by_name(self, vm_name):
        return self._database.get_vm_model_by_name(vm_name)

    def _update(self, vm_model, vmware_vm, vm_properties):
        logger.info('Updating %s', vm_model)
        vm_model.update(vmware_vm, vm_properties)
        logger.info('Updated %s', vm_model)
        for vmi_model in vm_model.vmi_models:
            self._database.vmis_to_update.append(vmi_model)
        self._database.save(vm_model)

    def _create(self, vmware_vm, vm_properties):
        vm_model = VirtualMachineModel(vmware_vm, vm_properties)
        self._database.vmis_to_update += vm_model.vmi_models
        self._add_property_filter_for_vm(vm_model, vmware_vm, VM_UPDATE_FILTERS)
        self._update_in_vnc(vm_model.vnc_vm)
        logger.info('Created %s', vm_model)
        self._database.save(vm_model)

    def _add_property_filter_for_vm(self, vm_model, vmware_vm, filters):
        property_filter = self._esxi_api_client.add_filter(vmware_vm, filters)
        vm_model.property_filter = property_filter

    def _update_in_vnc(self, vnc_vm):
        self._add_owner_to(vnc_vm)
        self._vnc_api_client.update_vm(vnc_vm)

    def _add_owner_to(self, vnc_vm):
        perms2 = PermType2()
        perms2.set_owner(self._project.get_uuid())
        vnc_vm.set_perms2(perms2)

    def get_vms_from_vmware(self):
        vmware_vms = self._esxi_api_client.get_all_vms()
        for vmware_vm in vmware_vms:
            try:
                self.update(vmware_vm)
            except vmodl.fault.ManagedObjectNotFound:
                logger.error('One VM was moved out of ESXi during CVM sync')

    def delete_unused_vms_in_vnc(self):
        vnc_vms = self._vnc_api_client.get_all_vms()
        for vnc_vm in vnc_vms:
            if self._database.get_vm_model_by_uuid(vnc_vm.uuid):
                continue
            with self._vcenter_api_client:
                if self._vcenter_api_client.can_remove_vm(uuid=vnc_vm.uuid):
                    logger.info('Deleting %s from VNC', vnc_vm.name)
                    self._vnc_api_client.delete_vm(vnc_vm.uuid)

    def remove_vm(self, name):
        vm_model = self._database.get_vm_model_by_name(name)
        logger.info('Deleting %s', vm_model)
        if not vm_model:
            return
        with self._vcenter_api_client:
            if self._vcenter_api_client.is_vm_removed(vm_model.name):
                self._vnc_api_client.delete_vm(vm_model.uuid)
            else:
                logger.info('VM %s still exists on another host and can\'t be deleted from VNC', name)
        self._database.delete_vm_model(vm_model.uuid)
        vm_model.destroy_property_filter()

    def update_vmware_tools_status(self, vmware_vm, tools_running_status):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if not vm_model:
            return
        if vm_model.is_tools_running_status_changed(tools_running_status):
            vm_model.update_tools_running_status(tools_running_status)
            logger.info('VMware tools on VM %s are %s', vm_model.name,
                        'running' if vm_model.tools_running else 'not running')
            self._database.save(vm_model)

    def rename_vm(self, old_name, new_name):
        logger.info('Renaming %s to %s', old_name, new_name)
        vm_model = self._database.get_vm_model_by_name(old_name)
        vm_model.rename(new_name)
        with self._vcenter_api_client:
            if self._vcenter_api_client.can_rename_vm(vm_model, new_name):
                self._update_in_vnc(vm_model.vnc_vm)
        self._database.save(vm_model)

    def update_vm_models_interfaces(self, vmware_vm):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        old_vmi_models = {vmi_model.uuid: vmi_model for vmi_model in vm_model.vmi_models}
        vm_model.update_interfaces(vmware_vm)
        new_vmi_models = {vmi_model.uuid: vmi_model for vmi_model in vm_model.vmi_models}

        for uuid, new_vmi_model in new_vmi_models.items():
            old_vmi_models.pop(uuid, None)
            self._database.vmis_to_update.append(new_vmi_model)

        self._database.vmis_to_delete += old_vmi_models.values()

    def update_power_state(self, vmware_vm, power_state):
        vm_model = self._database.get_vm_model_by_uuid(vmware_vm.config.instanceUuid)
        if vm_model.is_power_state_changed(power_state):
            vm_model.update_power_state(power_state)
            logger.info('VM %s was powered %s', vm_model.name, power_state[7:].lower())
            for vmi_model in vm_model.vmi_models:
                self._database.ports_to_update.append(vmi_model)
                self._database.vlans_to_update.append(vmi_model)
            self._database.save(vm_model)


def is_contrail_vm_name(name):
    return CONTRAIL_VM_NAME in name


class VirtualNetworkService(Service):
    def __init__(self, vcenter_api_client, vnc_api_client, database):
        super(VirtualNetworkService, self).__init__(vnc_api_client, database)
        self._vcenter_api_client = vcenter_api_client

    def update_vns(self):
        for vmi_model in list(self._database.vmis_to_update):
            portgroup_key = vmi_model.vcenter_port.portgroup_key
            if self._database.get_vn_model_by_key(portgroup_key) is not None:
                continue
            logger.info('Fetching new portgroup for key: %s', portgroup_key)
            with self._vcenter_api_client:
                dpg = self._vcenter_api_client.get_dpg_by_key(portgroup_key)
                fq_name = [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT, dpg.name]
                vnc_vn = self._vnc_api_client.read_vn(fq_name)
                if dpg and vnc_vn:
                    self._create_vn_model(dpg, vnc_vn)
                else:
                    logger.error('Unable to fetch new portgroup for key: %s', portgroup_key)
                    self._database.vmis_to_update.remove(vmi_model)
                    self._database.vmis_to_delete.append(vmi_model)
                    vmi_model.remove_from_vm_model()

    def _create_vn_model(self, dpg, vnc_vn):
        logger.info('Fetched new portgroup key: %s name: %s', dpg.key, vnc_vn.name)
        vn_model = VirtualNetworkModel(dpg, vnc_vn)
        self._vcenter_api_client.enable_vlan_override(vn_model.vmware_vn)
        self._database.save(vn_model)
        logger.info('Created %s', vn_model)


class VRouterPortService(object):
    def __init__(self, vrouter_api_client, database):
        self._vrouter_api_client = vrouter_api_client
        self._database = database

    def sync_ports(self):
        self._delete_ports()
        self._update_ports()
        self.sync_port_states()

    def sync_port_states(self):
        ports = list(self._database.ports_to_update)
        for vmi_model in ports:
            self._set_port_state(vmi_model)
            self._database.ports_to_update.remove(vmi_model)

    def _delete_ports(self):
        uuids = list(self._database.ports_to_delete)
        for uuid in uuids:
            self._delete_port(uuid)
            self._database.ports_to_delete.remove(uuid)

    def _delete_port(self, uuid):
        self._vrouter_api_client.delete_port(uuid)

    def _update_ports(self):
        ports = list(self._database.ports_to_update)
        for vmi_model in ports:
            vrouter_port = self._vrouter_api_client.read_port(vmi_model.uuid)
            if not vrouter_port:
                self._create_port(vmi_model)
                return
            if self._port_needs_an_update(vrouter_port, vmi_model):
                self._update_port(vmi_model)

    def _create_port(self, vmi_model):
        self._vrouter_api_client.add_port(vmi_model)
        if not vmi_model.vm_model.is_powered_on:
            self._database.ports_to_update.remove(vmi_model)

    def _update_port(self, vmi_model):
        self._vrouter_api_client.delete_port(vmi_model.uuid)
        self._vrouter_api_client.add_port(vmi_model)

    def _set_port_state(self, vmi_model):
        if vmi_model.vm_model.is_powered_on:
            self._vrouter_api_client.enable_port(vmi_model.uuid)
        else:
            self._vrouter_api_client.disable_port(vmi_model.uuid)

    @staticmethod
    def _port_needs_an_update(vrouter_port, vmi_model):
        return (vrouter_port.get('instance-id') != vmi_model.vm_model.uuid or
                vrouter_port.get('vn-id') != vmi_model.vn_model.uuid or
                vrouter_port.get('rx-vlan-id') != vmi_model.vcenter_port.vlan_id or
                vrouter_port.get('tx-vlan-id') != vmi_model.vcenter_port.vlan_id or
                vrouter_port.get('ip-address') != vmi_model.vnc_instance_ip.instance_ip_address)


class VlanIdService(object):
    def __init__(self, vcenter_api_client, esxi_api_client, vlan_id_pool, database):
        self._vcenter_api_client = vcenter_api_client
        self._esxi_api_client = esxi_api_client
        self._vlan_id_pool = vlan_id_pool
        self._database = database

    def sync_vlan_ids(self):
        vrouter_uuid = self._esxi_api_client.read_vrouter_uuid()
        with self._vcenter_api_client:
            reserved_vlan_ids = self._vcenter_api_client.get_reserved_vlan_ids(vrouter_uuid)
            for vlan_id in reserved_vlan_ids:
                self._vlan_id_pool.reserve(vlan_id)

        self.update_vlan_ids()

    def update_vlan_ids(self):
        for vmi_model in list(self._database.vlans_to_update):
            logger.info('Updating %s', vmi_model)
            self._update_vlan_id(vmi_model)
            self._database.vlans_to_update.remove(vmi_model)
            logger.info('Updated %s', vmi_model)

        for vmi_model in list(self._database.vlans_to_restore):
            self._restore_vlan_id(vmi_model)
            self._database.vlans_to_restore.remove(vmi_model)

    def _update_vlan_id(self, vmi_model):
        with self._vcenter_api_client:
            current_vlan_id = self._vcenter_api_client.get_vlan_id(vmi_model.vcenter_port)
            if current_vlan_id:
                self._preserve_old_vlan_id(current_vlan_id, vmi_model)
            else:
                self._assign_new_vlan_id(vmi_model)

    def _preserve_old_vlan_id(self, current_vlan_id, vmi_model):
        if self._database.is_vlan_available(vmi_model, current_vlan_id):
            vmi_model.vcenter_port.vlan_id = current_vlan_id
            vmi_model.vcenter_port.vlan_success = True
            self._vlan_id_pool.reserve(current_vlan_id)
        else:
            self._assign_new_vlan_id(vmi_model)

    def _assign_new_vlan_id(self, vmi_model):
        vmi_model.vcenter_port.vlan_id = self._vlan_id_pool.get_available()
        self._update_vcenter_vlan(vmi_model)

    def _restore_vlan_id(self, vmi_model):
        self._restore_vcenter_vlan_id(vmi_model)
        self._vlan_id_pool.free(vmi_model.vcenter_port.vlan_id)

    def _restore_vcenter_vlan_id(self, vmi_model):
        with self._vcenter_api_client:
            self._vcenter_api_client.restore_vlan_id(vmi_model.vcenter_port)

    def update_vcenter_vlans(self, retry=False):
        for vmi_model in list(self._database.vlans_to_update):
            self._update_vcenter_vlan(vmi_model, retry=retry)
            self._database.vlans_to_update.remove(vmi_model)

    def _update_vcenter_vlan(self, vmi_model, retry=False):
        if vmi_model.vcenter_port.vlan_success:
            logger.info('VLAN ID is already set with success')
            return
        if retry:
            i = 0
            while True:
                if i != 0:
                    logger.error('Task failed to complete, retrying...')
                with self._vcenter_api_client:
                    logger.info('Updating VLAN ID of %s in vCenter', vmi_model.display_name)
                    if wait_for_port(vmi_model):
                        state, error_msg = self._vcenter_api_client.set_vlan_id(vmi_model.vcenter_port)
                        if state == 'success':
                            vmi_model.vcenter_port.vlan_success = True
                            return
                        if error_msg != DVS_UNSTABLE_CLUSTER_ERROR:
                            break
                i += 1
            logger.error('Unable to finish the task.')
        else:
            with self._vcenter_api_client:
                state, _ = self._vcenter_api_client.set_vlan_id(vmi_model.vcenter_port)
                if state == 'success':
                    vmi_model.vcenter_port.vlan_success = True
