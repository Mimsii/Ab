#!/usr/bin/python3
"""
This script is invoked by the ansible playbook, typically via
`securedrop-admin`. It is run as root on the app server.

The backup file in the format sd-backup-$TIMESTAMP.tar.gz is then copied to the
Admin Workstation by the playbook, and removed on the server. For further
information and limitations, see https://docs.securedrop.org/en/stable/backup_and_restore.html
"""

import argparse
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create backup")
    parser.add_argument(
        "--dest",
        type=Path,
        default=os.getcwd(),
        help="Destination folder for backup",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.dest.exists():
        print(f"Error: {args.dest} does not exist")
        sys.exit(1)

    backup_filename = "sd-backup-{}.tar.gz".format(datetime.utcnow().strftime("%Y-%m-%d--%H-%M-%S"))

    # This code assumes everything is in the default locations.
    sd_data = "/var/lib/securedrop"

    sd_code = "/var/www/securedrop"
    sd_config = os.path.join(sd_code, "config.py")
    sd_custom_logo = os.path.join(sd_code, "static/i/custom_logo.png")

    tor_hidden_services = "/var/lib/tor/services"
    torrc = "/etc/tor/torrc"

    with tarfile.open(os.path.join(args.dest, backup_filename), "w:gz") as backup:
        backup.add(sd_config)

        # If no custom logo has been configured, the file will not exist
        if os.path.exists(sd_custom_logo):
            backup.add(sd_custom_logo)
        backup.add(sd_data)
        backup.add(tor_hidden_services)
        backup.add(torrc)

    print(backup_filename)


if __name__ == "__main__":
    main()
