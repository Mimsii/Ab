import re

import pytest
import testutils

sdvars = testutils.securedrop_test_vars
testinfra_hosts = [sdvars.monitor_hostname]
alert_level_regex = re.compile(r"Level: '(\d+)'")
rule_id_regex = re.compile(r"Rule id: '(\d+)'")


@pytest.mark.parametrize("log_event", sdvars.log_events_without_ossec_alerts)
def test_ossec_false_positives_suppressed(host, log_event):
    with host.sudo():
        c = host.run('echo "{}" | /var/ossec/bin/ossec-logtest'.format(log_event["alert"]))
        assert "Alert to be generated" not in c.stderr


@pytest.mark.parametrize("log_event", sdvars.log_events_with_ossec_alerts)
def test_ossec_expected_alerts_are_present(host, log_event):
    with host.sudo():
        c = host.run('echo "{}" | /var/ossec/bin/ossec-logtest'.format(log_event["alert"]))
        assert "Alert to be generated" in c.stderr
        alert_level = alert_level_regex.findall(c.stderr)[0]
        assert alert_level == log_event["level"]
        rule_id = rule_id_regex.findall(c.stderr)[0]
        assert rule_id == log_event["rule_id"]


def test_noble_migration_check(host):
    """
    Verify the noble migration check does not generate OSSEC notifications

    Regression check for <https://github.com/freedomofpress/securedrop/issues/7393>;
    we are assuming that no checks will fail; otherwise
    test_release_upgrades.py::test_migration_check would've already failed
    """
    if host.system_info.codename != "focal":
        pytest.skip("only applicable/testable on focal")

    with host.sudo():
        cmd = host.run("securedrop-noble-migration-check | /var/ossec/bin/ossec-logtest")
        assert "Alert to be generated" not in cmd.stderr
