#!/usr/bin/env python
"""
Written by Dann Bohn
Github: https://github.com/whereismyjetpack
Email: dannbohn@gmail.com

Clone a VM from template example
"""
from pyVmomi import vim
from pyVim.connect import SmartConnect, Disconnect
import atexit
import argparse
import getpass
import time
import atexit
import requests
import random
import string
from multiprocessing import Process
from collections import defaultdict

data = {} #needed for print_ips functions

def randomword(length):
   letters = string.ascii_lowercase
   return ''.join(random.choice(letters) for i in range(length))

try:
    _vimtype_dict = {
        'dc' : vim.Datacenter,
        'cluster' : vim.ClusterComputeResource,
        'vm' : vim.VirtualMachine,
        'host' : vim.HostSystem,
        'host.NasSpec' : vim.host.NasVolume.Specification,
        'network' : vim.Network,
        'ds' : vim.Datastore,
        'dvs.PortGroup' : vim.dvs.DistributedVirtualPortgroup,
        'dvs.VSwitch' : vim.dvs.VmwareDistributedVirtualSwitch,
        'dvs.PVLan' : vim.dvs.VmwareDistributedVirtualSwitch.PvlanSpec,
        'dvs.VLan' : vim.dvs.VmwareDistributedVirtualSwitch.VlanIdSpec,
        'dvs.PortConfig' : vim.dvs.VmwareDistributedVirtualSwitch.VmwarePortConfigPolicy,
        'dvs.ConfigSpec' : vim.dvs.DistributedVirtualPortgroup.ConfigSpec,
        'dvs.PortConn' : vim.dvs.PortConnection,
        'dvs.PortGroupSecurity' : vim.dvs.VmwareDistributedVirtualSwitch.SecurityPolicy,
        'dvs.PortGroupPolicy' : vim.host.NetworkPolicy,
        'dvs.Blob' : vim.dvs.KeyedOpaqueBlob,
        'ip.Config' : vim.vApp.IpPool.IpPoolConfigInfo,
        'ip.Association' : vim.vApp.IpPool.Association,
        'ip.Pool' : vim.vApp.IpPool,
        'dev.E1000' : vim.vm.device.VirtualE1000,
        'dev.Vmxnet3' : vim.vm.device.VirtualVmxnet3,
        'dev.VDSpec' : vim.vm.device.VirtualDeviceSpec,
        'dev.VD' : vim.vm.device.VirtualDevice,
        'dev.ConnectInfo' : vim.vm.device.VirtualDevice.ConnectInfo,
        'dev.DVPBackingInfo' : vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo,
        'dev.Ops.add' : vim.vm.device.VirtualDeviceSpec.Operation.add,
        'dev.Ops.remove' : vim.vm.device.VirtualDeviceSpec.Operation.remove,
        'dev.Ops.edit' : vim.vm.device.VirtualDeviceSpec.Operation.edit,
        'vm.Config' : vim.vm.ConfigSpec,
        'vm.Reloc' : vim.vm.RelocateSpec,
        'vm.Clone' : vim.vm.CloneSpec,
        'vm.PassAuth' : vim.vm.guest.NamePasswordAuthentication,
        'vm.Prog' : vim.vm.guest.ProcessManager.ProgramSpec,
     }

except:
    _vimtype_dict = {}
    connect = None
    vim = None
    _vimtype_dict = None

def _vim_obj(typestr, **kwargs):
    return _vimtype_dict[typestr](**kwargs)

def _get_obj_list (content,root, vimtype):
        view = content.viewManager.CreateContainerView(root, [_vimtype_dict[vimtype]], True)
        return [obj for obj in view.view]

def run_a_command(si,vm , vm_user, vm_password, path_to_cmd,datacenter,cmd_args = None):
        content = si.RetrieveContent()    
        creds = _vim_obj('vm.PassAuth', username = vm_user, password = vm_password)
        ps = _vim_obj('vm.Prog', programPath=path_to_cmd, arguments=cmd_args)
        pm = content.guestOperationsManager.processManager
        res = pm.StartProgramInGuest(vm, creds, ps)
        return res

def get_args():
    """ Get arguments from CLI """
    parser = argparse.ArgumentParser(
        description='Arguments for talking to vCenter')

    parser.add_argument('-s', '--host',
                        required=True,
                        action='store',
                        help='vSpehre service to connect to')

    parser.add_argument('-o', '--port',
                        type=int,
                        default=443,
                        action='store',
                        help='Port to connect on')

    parser.add_argument('-u', '--user',
                        required=True,
                        action='store',
                        help='Username to use')

    parser.add_argument('-p', '--password',
                        required=False,
                        action='store',
                        help='Password to use')

    parser.add_argument('-v', '--vm-name',
                        required=True,
                        action='store',
                        help='Name of the VM you wish to make')
    
    parser.add_argument('-n', '--vn-name',
                        required=True,
                        action='store',
                        help='Name of the VN you wish to make add to vm')
    
    parser.add_argument('-w', '--dv-switch',
                        required=True,
                        action='store',
                        help='Name of the dv switch')

    parser.add_argument('--template',
                        required=True,
                        action='store',
                        help='Name of the template/VM \
                            you are cloning from')

    parser.add_argument('--datacenter-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Name of the Datacenter you\
                            wish to use. If omitted, the first\
                            datacenter will be used.')

    parser.add_argument('--vm-folder',
                        required=False,
                        action='store',
                        default=None,
                        help='Name of the VMFolder you wish\
                            the VM to be dumped in. If left blank\
                            The datacenter VM folder will be used')

    parser.add_argument('--datastore-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Datastore you wish the VM to end up on\
                            If left blank, VM will be put on the same \
                            datastore as the template')

    parser.add_argument('--datastorecluster-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Datastorecluster (DRS Storagepod) you wish the VM to end up on \
                            Will override the datastore-name parameter.')

    parser.add_argument('--cluster-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Name of the cluster you wish the VM to\
                            end up on. If left blank the first cluster found\
                            will be used')

    parser.add_argument('--resource-pool',
                        required=False,
                        action='store',
                        default=None,
                        help='Resource Pool to use. If left blank the first\
                            resource pool found will be used')

    parser.add_argument('--power-on',
                        dest='power_on',
                        required=False,
                        action='store_true',
                        help='power on the VM after creation')

    parser.add_argument('--no-power-on',
                        dest='power_on',
                        required=False,
                        action='store_false',
                        help='do not power on the VM after creation')

    parser.set_defaults(power_on=True)

    args = parser.parse_args()

    if not args.password:
        args.password = getpass.getpass(
            prompt='Enter password')

    return args


def wait_for_task(task):
    """ wait for a vCenter task to finish """
    task_done = False
    state = task.info.state
    while not task_done:
        state = task.info.state
        if state == 'success':
            result = task.info.result
            return result

        if task.info.state == 'error':
            print "there was an error"
            task_done = True


def get_obj(content, vimtype, name):
    """
    Return an object by name, if name is None the
    first found object is returned
    """
    obj = None
    container = content.viewManager.CreateContainerView(
        content.rootFolder, vimtype, True)
    for c in container.view:
        if name:
            if c.name == name:
                obj = c
                break
        else:
            obj = c
            break

    return obj

def _match_obj(obj, param):
    attr = param.keys()[0]
    attrs = [attr]
    if '.' in attr:
        attrs = attr.split('.')
        for i in range(len(attrs) - 1):
            if not hasattr(obj, attrs[i]):
                break
            obj = getattr(obj, attrs[i])
    attr = attrs[-1]
    return hasattr(obj, attr) and getattr(obj, attr) == param.values()[0]

def _find_obj (si, root, vimtype, param):
        content = si.RetrieveContent()
        if vimtype == 'ip.Pool':
            items = content.ipPoolManager.QueryIpPools(self._dc)
        else:
            items = content.viewManager.CreateContainerView(root, [_vimtype_dict[vimtype]], True).view
        for obj in items:
            if _match_obj(obj, param):
                return obj
        return None


def build_spec(
        content, template, vm_name, si,
        datacenter_name, vm_folder, datastore_name,
        cluster_name, resource_pool, power_on, datastorecluster_name,vn_name,dv_switch):
    """
    Clone a VM from a template/VM, datacenter_name, vm_folder, datastore_name
    cluster_name, resource_pool, and power_on are all optional.
    """
    #template = get_obj(content, [vim.VirtualMachine], template)

    #vm_name = randomword(5)
    vm_name = 'SET1' + randomword(5)
    print "vm_name %s" %vm_name 

    # if none get the first one
    datacenter = get_obj(content, [vim.Datacenter], datacenter_name)

    if vm_folder:
        destfolder = get_obj(content, [vim.Folder], vm_folder)
    else:
        destfolder = datacenter.vmFolder

    if datastore_name:
        datastore = get_obj(content, [vim.Datastore], datastore_name)
    else:
        datastore = get_obj(
            content, [vim.Datastore], template.datastore[0].info.name)

    # if None, get the first one
    cluster = get_obj(content, [vim.ClusterComputeResource], cluster_name)
    if resource_pool:
        tgthost = _find_obj(si,_find_obj(si,datacenter, 'cluster', {'name' : cluster_name}),
                                    'host', {'name' : resource_pool})
        resource_pool = tgthost.parent.resourcePool
    else:
        resource_pool = cluster.resourcePool
    net = _find_obj(si,datacenter, 'dvs.PortGroup', {'name' : vn_name})
    dvs = _get_obj_list(content,datacenter, 'dvs.VSwitch')
    if len(dvs) > 1:
        for dv in dvs:
            if dv.name in dv_switch:
                vs = dv
                break
    else:
        vs = dvs[0]
    switch_id = vs.uuid
    intfs = []
    spec = _vim_obj('dev.VDSpec', operation=_vimtype_dict['dev.Ops.add'],
                    device=_vim_obj('dev.Vmxnet3',
                             addressType='Generated',
                             connectable=_vim_obj('dev.ConnectInfo',
                             startConnected=True,
                             allowGuestControl=True),
                         backing=_vim_obj('dev.DVPBackingInfo',
                                         port = _vim_obj('dvs.PortConn',
                                           switchUuid=switch_id,
                                           portgroupKey=net.key))))
    intfs.append(spec)

    vmconf = vim.vm.ConfigSpec()

    if datastorecluster_name:
        podsel = vim.storageDrs.PodSelectionSpec()
        pod = get_obj(content, [vim.StoragePod], datastorecluster_name)
        podsel.storagePod = pod

        storagespec = vim.storageDrs.StoragePlacementSpec()
        storagespec.podSelectionSpec = podsel
        storagespec.type = 'create'
        storagespec.folder = destfolder
        storagespec.resourcePool = resource_pool
        storagespec.configSpec = vmconf

        try:
            rec = content.storageResourceManager.RecommendDatastores(
                storageSpec=storagespec)
            rec_action = rec.recommendations[0].action[0]
            real_datastore_name = rec_action.destination.name
        except:
            real_datastore_name = template.datastore[0].info.name

        datastore = get_obj(content, [vim.Datastore], real_datastore_name)

    # set relospec
    relospec = vim.vm.RelocateSpec()
    relospec.datastore = datastore
    relospec.pool = resource_pool

    clonespec = vim.vm.CloneSpec()
    clonespec.location = relospec
    clonespec.powerOn = power_on
    clonespec.config = _vim_obj('vm.Config', deviceChange=intfs)
    return (destfolder,vm_name,clonespec)
   

def clone_vm(template,destfolder,vm_name,clonespec):
    print "cloning VM..."
    task = template.Clone(folder=destfolder, name=vm_name, spec=clonespec)
    wait_for_task(task)


def get_conn(args):
    """
    Let this thing fly
    """
    args = get_args()

    # connect this thing
    try:
        si = SmartConnect(host=args.host, port=args.port, user=args.user, pwd=args.password)
    except Exception as exc:
        if isinstance(exc, vim.fault.HostConnectFault) and '[SSL: CERTIFICATE_VERIFY_FAILED]' in exc.msg:
            try:
                import ssl
                default_context = ssl._create_default_https_context
                ssl._create_default_https_context = ssl._create_unverified_context
                si = SmartConnect(
                    host=args.host,
                    port=args.port,
                    user=args.user,
                    pwd=args.password,
                    )
                ssl._create_default_https_context = default_context
            except Exception as exc1:
                raise Exception(exc1)
        else:
            import ssl
            context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            context.verify_mode = ssl.CERT_NONE
            si = SmartConnect(
                   host=args.host, 
                   port=args.port, 
                   user=args.user, 
                   pwd=args.password,
                   sslContext=context)
    atexit.register(Disconnect, si)
    return si

def clone_vm(template,destfolder,vm_name,clonespec):
    print "cloning VM..."
    task = template.Clone(folder=destfolder, name=vm_name, spec=clonespec)
    return task

def main():
    args = get_args()
    si = get_conn(args)

    content = si.RetrieveContent()
    template = None

    datacenter = get_obj(content, [vim.Datacenter], args.datacenter_name)
    template = get_obj(content, [vim.VirtualMachine], args.template)
    threads = []
    build_spec_list = []
    if template:
        for i in range(15):
            val = build_spec(
                  content, template, args.vm_name, si,
                  args.datacenter_name, args.vm_folder,
                  args.datastore_name, args.cluster_name,
                  args.resource_pool, args.power_on, 
                  args.datastorecluster_name,
                  args.vn_name,args.dv_switch)
            build_spec_list.append(val)
        tasks_list = []
        for val in build_spec_list:
            tasks_list.append(clone_vm(
                  template,val[0],val[1],val[2]))
#        threads = []
        for task in tasks_list:
            if wait_for_task(task):
                time.sleep(5)
#                val = build_spec_list[tasks_list.index(task)]
#                vm_name = val[1] 
#                vmobj = _find_obj(si,datacenter, 'vm', {'name' : vm_name})
#                vm_id = vmobj.summary.config.uuid
#                path_to_cmd = 'cat /dev/zero > /dev/null'
#                cmd_args = None 
#                vm_user = 'tc'
#                vm_password = 'secret'
#                try: 
#                    run_a_command( si,vmobj , vm_user, vm_password, path_to_cmd,datacenter, cmd_args = cmd_args)
#                    print "run command failed for %s"%vm_name 
#                except Exception as e:
#                    pass
    else:
        print "template not found"


# start this thing with the below command
#python clone_vm.py --host 10.204.217.246 --user 'administrator@vsphere.local' --password 'Contrail123!' --vm-name 'test_vm' --template vcenter_tiny_vm --datacenter-name c4_datacenter11 --cluster-name c4_cluster11 --power-on --dv-switch c4k4_dvs --vn-name test_vn --resource-pool 10.204.216.226
if __name__ == "__main__":
    main()
