from unittest import TestCase
from cvm.models import VirtualMachineModel


class TestVirtualMachineModel(TestCase):
    def test_to_vnc_vm(self):
        vm_model = VirtualMachineModel()
        vm_model.uuid = 'd376b6b4-943d-4599-862f-d852fd6ba425'
        vm_model.vrouter_ip_address = '192.168.0.10'

        vnc_vm = vm_model.to_vnc_vm()

        self.assertEqual(vnc_vm.name, vm_model.uuid)
        self.assertEqual(vnc_vm.uuid, vm_model.uuid)
        self.assertEqual(vnc_vm.display_name, vm_model.vrouter_ip_address)
        self.assertEqual(vnc_vm.fq_name, [vm_model.uuid])
