import re

import pytest
import testutils

sdvars = testutils.securedrop_test_vars
testinfra_hosts = [sdvars.app_hostname]


# Prod Tor services may have unexpected configs
# TODO: read from admin workstation site-specific file if available
@pytest.mark.skip_in_prod
@pytest.mark.parametrize("tor_service", sdvars.tor_services)
def test_tor_service_directories(host, tor_service):
    """
    Check mode and ownership on Tor service directories.
    """
    with host.sudo():
        f = host.file("/var/lib/tor/services/{}".format(tor_service["name"]))
        assert f.is_directory
        assert f.mode == 0o700
        assert f.user == "debian-tor"
        assert f.group == "debian-tor"


@pytest.mark.skip_in_prod
@pytest.mark.parametrize("tor_service", sdvars.tor_services)
def test_tor_service_hostnames(host, tor_service):
    """
    Check contents of Tor service hostname file. For v3 onion services,
    the file should contain only hostname (.onion URL).
    """
    # Declare regex only for THS; we'll build regex for ATHS only if
    # necessary, since we won't have the required values otherwise.
    ths_hostname_regex = r"[a-z0-9]{16}\.onion"
    ths_hostname_regex_v3 = r"[a-z0-9]{56}\.onion"

    with host.sudo():
        f = host.file("/var/lib/tor/services/{}/hostname".format(tor_service["name"]))
        assert f.is_file
        assert f.mode == 0o600
        assert f.user == "debian-tor"
        assert f.group == "debian-tor"

        # All hostnames should contain at *least* the hostname.
        assert re.search(ths_hostname_regex, f.content_string)

        if tor_service["authenticated"] and tor_service["version"] == 3:
            # For authenticated version 3 onion services, the authorized_client
            # directory will exist and contain a file called client.auth.
            client_auth = host.file(
                "/var/lib/tor/services/{}/authorized_clients/client.auth".format(
                    tor_service["name"]
                )
            )
            assert client_auth.is_file
        else:
            assert re.search(f"^{ths_hostname_regex_v3}$", f.content_string)


@pytest.mark.skip_in_prod
@pytest.mark.parametrize("tor_service", sdvars.tor_services)
def test_tor_services_config(host, tor_service):
    """
    Ensure torrc file contains relevant lines for onion service declarations.
    All onion services must include:

      * HiddenServiceDir
      * HiddenServicePort
    """
    f = host.file("/etc/tor/torrc")
    dir_regex = "HiddenServiceDir /var/lib/tor/services/{}".format(tor_service["name"])
    # We need at least one port, but it may be used for both config values.
    # On the Journalist Interface, we reuse the "80" remote port but map it to
    # a different local port, so Apache can listen on several sockets.
    remote_port = tor_service["ports"][0]
    try:
        local_port = tor_service["ports"][1]
    except IndexError:
        local_port = remote_port

    port_regex = f"HiddenServicePort {remote_port} 127.0.0.1:{local_port}"

    assert f.contains(f"^{dir_regex}$")
    assert f.contains(f"^{port_regex}$")

    # Check for block in file, to ensure declaration order
    service_regex = "\n".join([dir_regex, port_regex])
    assert service_regex in f.content_string
