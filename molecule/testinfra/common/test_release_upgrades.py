import json
import time

import pytest
import testutils

test_vars = testutils.securedrop_test_vars
testinfra_hosts = [test_vars.app_hostname, test_vars.monitor_hostname]


def test_release_manager_installed(host):
    """
    The securedrop-config package munges `do-release-upgrade` settings
    that assume the release-upgrader logic is installed. On hardware
    installs of Ubuntu, it is, but the VM images we use in CI may
    remove it to make the boxes leaner.
    """
    assert host.package("ubuntu-release-upgrader-core").is_installed
    assert host.exists("do-release-upgrade")


def test_release_manager_upgrade_channel(host):
    """
    Ensures that the `do-release-upgrade` command will not
    suggest upgrades to a future LTS, until we test it and provide support.
    """
    config_path = "/etc/update-manager/release-upgrades"
    assert host.file(config_path).is_file

    raw_output = host.check_output(f"grep '^Prompt' {config_path}")
    _, channel = raw_output.split("=")

    assert channel == "never"


def test_migration_check(host):
    """Verify our migration check script works"""
    if host.system_info.codename != "focal":
        pytest.skip("only applicable/testable on focal")

    with host.sudo():
        # remove state file so we can see if it works
        if host.file("/etc/securedrop-noble-migration.json").exists:
            host.run("rm /etc/securedrop-noble-migration.json")
        cmd = host.run("systemctl start securedrop-noble-migration-check")
        assert cmd.rc == 0
        while host.service("securedrop-noble-migration-check").is_running:
            time.sleep(1)

        # JSON state file was created
        assert host.file("/etc/securedrop-noble-migration.json").exists

        cmd = host.run("cat /etc/securedrop-noble-migration.json")
        assert cmd.rc == 0

        contents = json.loads(cmd.stdout)
        print(contents)
        # The script did not error out
        if "error" in contents:
            # Run the script manually to get the error message
            cmd = host.run("securedrop-noble-migration-check")
            print(cmd.stdout)
            # We'll fail in the next line after this
        assert "error" not in contents
        # All the values should be True
        assert all(contents.values())
