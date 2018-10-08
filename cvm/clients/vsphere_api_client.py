from pyVmomi import vim  # pylint: disable=no-name-in-module


class VSphereAPIClient(object):
    def __init__(self):
        self._si = None
        self._datacenter = None

    def _get_object(self, vimtype, name):
        content = self._si.content
        container = content.viewManager.CreateContainerView(content.rootFolder, vimtype, True)
        try:
            return [obj for obj in container.view if obj.name == name][0]
        except IndexError:
            return None

    def _get_vm_by_uuid(self, uuid):
        content = self._si.content
        container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        try:
            return [vm for vm in container.view if vm.config.instanceUuid == uuid][0]
        except IndexError:
            return None
