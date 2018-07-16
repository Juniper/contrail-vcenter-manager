from vnc_api.vnc_api import NoIdError

from cvm.constants import (VNC_ROOT_DOMAIN, VNC_VCENTER_DEFAULT_SG,
                           VNC_VCENTER_IPAM, VNC_VCENTER_PROJECT)


def test_read_project(vnc_api_client, vnc_lib, project):
    vnc_lib.project_read.return_value = project

    project = vnc_api_client.read_or_create_project()

    assert project.name == 'project-name'
    assert project.fq_name == ['domain-name', 'project-name']


def test_read_no_project(vnc_api_client, vnc_lib):
    vnc_lib.project_read.side_effect = NoIdError(0)

    project = vnc_api_client.read_or_create_project()

    vnc_lib.project_create.assert_called_once()
    assert project.name == VNC_VCENTER_PROJECT
    assert project.fq_name == [VNC_ROOT_DOMAIN, VNC_VCENTER_PROJECT]


def test_read_security_group(vnc_api_client, vnc_lib, security_group):
    vnc_lib.security_group_read.return_value = security_group

    security_group = vnc_api_client.read_or_create_security_group()

    assert security_group.name == 'security-group-name'
    assert security_group.fq_name == ['domain-name', 'project-name', 'security-group-name']


def test_read_no_security_group(vnc_api_client, vnc_lib, project):
    vnc_lib.security_group_read.side_effect = NoIdError(0)
    vnc_lib.project_read.return_value = project

    security_group = vnc_api_client.read_or_create_security_group()

    vnc_lib.security_group_create.assert_called_once()
    assert VNC_VCENTER_DEFAULT_SG == security_group.name
    assert security_group.fq_name == ['domain-name', 'project-name', VNC_VCENTER_DEFAULT_SG]


def test_read_ipam(vnc_api_client, vnc_lib, ipam):
    vnc_lib.network_ipam_read.return_value = ipam

    ipam = vnc_api_client.read_or_create_ipam()

    assert ipam.name == 'ipam-name'
    assert ipam.fq_name == ['domain-name', 'project-name', 'ipam-name']


def test_read_no_ipam(vnc_api_client, vnc_lib, project):
    vnc_lib.network_ipam_read.side_effect = NoIdError(0)
    vnc_lib.project_read.return_value = project

    ipam = vnc_api_client.read_or_create_ipam()

    vnc_lib.network_ipam_create.assert_called_once()
    assert ipam.name == VNC_VCENTER_IPAM
    assert ipam.fq_name == ['domain-name', 'project-name', VNC_VCENTER_IPAM]
