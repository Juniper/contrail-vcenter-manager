# -*- mode: python; -*-

#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#
import os
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
    file_ for file_ in os.listdir(Dir('#vcenter-manager/cvm/').abspath)
    if fnmatch.fnmatch(file_, '*.py')
]

cvm = [
    env.Install(Dir('cvm'), '#vcenter-manager/cvm/' + cvm_file)
    for cvm_file in cvm_source_files
]
cvm.append(env.Install(Dir('.'), "#vcenter-manager/setup.py"))
cvm.append(env.Install(Dir('.'), "#vcenter-manager/requirements.txt"))
cvm.append(env.Install(Dir('.'), "#vcenter-manager/config.yaml"))

env.Depends(cvm, cvm_sandesh)
env.Alias('cvm', cvm)
