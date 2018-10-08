# -*- mode: python; -*-

#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#
import os
import glob
import fnmatch

env = DefaultEnvironment()

cvm_sandesh_files = [
    'vcenter_manager.sandesh',
]

cvm_sandesh = [
    env.SandeshGenPy(sandesh_file, 'cvm/sandesh/', False)
    for sandesh_file in cvm_sandesh_files
]

cvm_source_files = [
    y for x in os.walk('cvm')
    for y in glob.glob(os.path.join(x[0], '*.py'))
    if 'cvm/sandesh/' not in y
]

cvm = [
    env.Install(Dir('cvm'), '#vcenter-manager/' + cvm_file)
    for cvm_file in cvm_source_files
]
cvm.append(env.Install(Dir('.'), "#vcenter-manager/setup.py"))
cvm.append(env.Install(Dir('.'), "#vcenter-manager/requirements.txt"))

env.Depends(cvm, cvm_sandesh)
env.Alias('cvm', cvm)

install_cmd = env.Command(None, 'setup.py',
        'cd ' + Dir('.').path + ' && python setup.py install %s' % env['PYTHON_INSTALL_OPT'])

env.Depends(install_cmd, cvm)
env.Alias('cvm-install', install_cmd)
