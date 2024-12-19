import time

import testutils
from testinfra.host import Host

test_vars = testutils.securedrop_test_vars
testinfra_hosts = [test_vars.app_hostname, test_vars.monitor_hostname]


def test_system_time(host: Host) -> None:
    assert not host.package("ntp").is_installed
    assert not host.package("ntpdate").is_installed

    s = host.service("systemd-timesyncd")
    assert s.is_running
    assert s.is_enabled
    assert not s.is_masked

    # File will be touched on every successful synchronization,
    # see 'man systemd-timesyncd'`
    assert host.file("/run/systemd/timesync/synchronized").exists

    c = host.run("timedatectl show")
    assert "NTP=yes" in c.stdout
    assert "NTPSynchronized=yes" in c.stdout


def test_ossec_cleanup(host: Host) -> None:
    with host.sudo():
        c = host.run("mkdir -p /var/ossec/queue/diff/local/boot/appinfra-test")
        assert c.rc == 0
        c = host.run("echo 'test' > /var/ossec/queue/diff/local/boot/appinfra-test/state.123456789")
        assert c.rc == 0
        # change the mtime on the file to be 2 years ago
        c = host.run(
            "touch -d '2 years ago' /var/ossec/queue/diff/local/boot/appinfra-test/state.123456789"
        )
        assert c.rc == 0
        c = host.run("systemctl start securedrop-cleanup-ossec")
        assert c.rc == 0
        while host.service("securedrop-cleanup-ossec").is_running:
            time.sleep(1)
        assert not host.file(
            "/var/ossec/queue/diff/local/boot/appinfra-test/state.123456789"
        ).exists
        # cleanup
        c = host.run("rm -r /var/ossec/queue/diff/local/boot/appinfra-test")
        assert c.rc == 0
