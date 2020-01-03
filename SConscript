# -*- mode: python; -*-

#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#
import itertools
import os
import fnmatch

env = DefaultEnvironment()


SConscript('../controller/src/vnsw/SConscript')

setup_sources = [
    'setup.py',
    'requirements.txt',
    'requirements_dev.txt',
    'tox.ini',
    '.coveragerc',
]

setup_sources_rules = []
for file in setup_sources:
    setup_sources_rules.append(
        env.Install(Dir('.'), "#vcenter-manager/" + file))

cvm_sandesh_files = ["vcenter_manager.sandesh"]

cvm_sandesh = [
    env.SandeshGenPy(sandesh_file, "cvm/sandesh/", False)
    for sandesh_file in cvm_sandesh_files
]

cvm_root_dir = Dir("#vcenter-manager/").abspath

cvm_source_files = []
for root, dirs, files in os.walk(os.path.join(cvm_root_dir, "cvm")):
    for _file in files:
        if fnmatch.fnmatch(_file, "*.py"):
            abs_path = os.path.join(root, _file)
            if fnmatch.fnmatch(abs_path, "*/sandesh/*"):
                continue
            rel_path = os.path.relpath(abs_path, cvm_root_dir)
            cvm_source_files.append(rel_path)

cvm_test_files = []
for root, dirs, files in os.walk(os.path.join(cvm_root_dir, "tests")):
    for _file in files:
        if fnmatch.fnmatch(_file, "*.py"):
            abs_path = os.path.join(root, _file)
            rel_path = os.path.relpath(abs_path, cvm_root_dir)
            cvm_test_files.append(rel_path)


cvm = []
for cvm_file in itertools.chain(cvm_source_files, cvm_test_files):
    target = "/".join(cvm_file.split("/")[:-1])
    cvm.append(
        env.Install(Dir(target), "#vcenter-manager/" + cvm_file)
    )

cd_cmd = 'cd ' + Dir('.').path + ' && '
sdist_depends = []
sdist_depends.extend(setup_sources_rules)
sdist_depends.extend(cvm)
sdist_depends.extend(cvm_sandesh)
sdist_gen = env.Command('dist/contrail-vcenter-manager-0.1dev.tar.gz',
                        'setup.py', cd_cmd + 'python setup.py sdist')

env.Depends(sdist_gen, sdist_depends)

test_target = env.SetupPyTestSuite(sdist_gen, use_tox=True)
env.Alias('vcenter-manager:test', test_target)

# cvm_sandesh_files = [
#     'vcenter_manager.sandesh',
# ]
#
# cvm_sandesh = [
#     env.SandeshGenPy(sandesh_file, 'cvm/sandesh/', False)
#     for sandesh_file in cvm_sandesh_files
# ]
#
# cvm_source_files = [
#     file_ for file_ in os.listdir(Dir('#vcenter-manager/cvm/').abspath)
#     if fnmatch.fnmatch(file_, '*.py')
# ]
#
# cvm_root_dir = Dir('#vcenter-manager/cvm/').abspath
#
# cvm_test_files = []
# for root, dirs, files in os.walk(os.path.join(cvm_root_dir, "tests")):
#     for _file in files:
#         if fnmatch.fnmatch(_file, "*.py") or fnmatch.fnmatch(_file, "*.conf"):
#             abs_path = os.path.join(root, _file)
#             rel_path = os.path.relpath(abs_path, cvm_root_dir)
#             cvm_test_files.append(rel_path)
#
#
# cvm = [
#     env.Install(Dir('cvm'), '#vcenter-manager/cvm/' + cvm_file)
#     for cvm_file in cvm_source_files
# ]
# cvm.append(env.Install(Dir('.'), "#vcenter-manager/setup.py"))
# cvm.append(env.Install(Dir('.'), "#vcenter-manager/requirements.txt"))

env.Depends(cvm, cvm_sandesh)
env.Alias('cvm', cvm)

install_cmd = env.Command(None, 'setup.py',
        'cd ' + Dir('.').path + ' && python setup.py install %s' % env['PYTHON_INSTALL_OPT'])

env.Depends(install_cmd, cvm)
env.Alias('cvm-install', install_cmd)
