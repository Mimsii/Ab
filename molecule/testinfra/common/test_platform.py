import testutils

test_vars = testutils.securedrop_test_vars
testinfra_hosts = [test_vars.app_hostname, test_vars.monitor_hostname]


def test_ansible_version(host):
    """
    Check that a supported version of Ansible is being used.
    """
    localhost = host.get_host("local://")
    c = localhost.check_output("ansible --version")
    assert c.startswith("ansible [core 2.")


def test_platform(host):
    """
    SecureDrop requires Ubuntu 20.04 (focal) or 24.04 (noble)
    """
    assert host.system_info.type == "linux"
    assert host.system_info.distribution == "ubuntu"
    version = (host.system_info.codename, host.system_info.release)
    assert version in {("focal", "20.04"), ("noble", "24.04")}
