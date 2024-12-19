import pytest
import testutils

sdvars = testutils.securedrop_test_vars
testinfra_hosts = [sdvars.app_hostname]


@pytest.mark.skip_in_prod
def test_backup(host):
    """Create a backup and verify it contains expected files"""

    with host.sudo():
        result = host.run("securedrop-app-backup.py --dest /tmp")
        assert result.rc == 0
        tarball = result.stdout.strip()
        # looks like a file path
        assert tarball.endswith(".tar.gz")
        assert host.file(f"/tmp/{tarball}").exists
        # list files in the tarball
        contains = host.run(f"tar -tzf /tmp/{tarball}")
        assert contains.rc == 0
        contains_list = contains.stdout.splitlines()
        assert "var/www/securedrop/config.py" in contains_list
        assert "etc/tor/torrc" in contains_list
        assert "var/lib/tor/services/" in contains_list
        # cleanup
        cleanup = host.run(f"rm /tmp/{tarball}")
        assert cleanup.rc == 0
