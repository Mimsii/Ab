#!/usr/bin/python3
"""
Migrate users from the "ssh" group to "sdssh"

Runs as root on both app and mon servers
"""

import grp
import subprocess
from pathlib import Path

SOURCE_GROUP = "ssh"
DEST_GROUP = "sdssh"


def main() -> None:
    try:
        grp.getgrnam(DEST_GROUP)
        print(f"Group {DEST_GROUP} already exists")
    except KeyError:
        print(f"Creating group {DEST_GROUP}")
        subprocess.run(["groupadd", DEST_GROUP], check=True)

    try:
        source_group_info = grp.getgrnam(SOURCE_GROUP)
    except KeyError:
        # Source group doesn't exist, probably a new install.
        print(f"Group {SOURCE_GROUP} does not exist; stopping migration")
        return
    source_users = source_group_info.gr_mem
    print(f"Need to migrate: {source_users}")

    for username in source_users:
        # Add user to new group while preserving other group memberships
        subprocess.run(["usermod", "-a", "-G", DEST_GROUP, username], check=True)
        print(f"Added {username} to {DEST_GROUP}")
        # can't use usermod -r here since focal doesn't support it
        subprocess.run(["gpasswd", "-d", username, SOURCE_GROUP], check=True)
        print(f"Removed {username} from {SOURCE_GROUP}")
    print("User migration complete")

    # Now update sshd_config
    sshd_config = Path("/etc/ssh/sshd_config")
    text = sshd_config.read_text()
    if f"AllowGroups {SOURCE_GROUP}\n" in text:
        # Update the AllowGroups stanza
        text = text.replace(f"AllowGroups {SOURCE_GROUP}\n", f"AllowGroups {DEST_GROUP}\n")
        # And the comment that precedes it
        text = text.replace(f"in the {SOURCE_GROUP} group", f"in the {DEST_GROUP} group")
        sshd_config.write_text(text)
        print("Updated /etc/ssh/sshd_config")
        # n.b. we don't restart sshd here, we'll let it take effect on boot

    # Now update iptables rules
    iptables = Path("/etc/iptables/rules.v4")
    text = iptables.read_text()
    if f"--gid-owner {SOURCE_GROUP} -j LOGNDROP" in text:
        # Update the --gid-owner stanza
        text = text.replace(
            f"--gid-owner {SOURCE_GROUP} -j LOGNDROP", f"--gid-owner {DEST_GROUP} -j LOGNDROP"
        )
        # And the comment that precedes it
        text = text.replace(
            f"for users in the {SOURCE_GROUP} group", f"for users in the {DEST_GROUP} group"
        )
        iptables.write_text(text)
        print("Updated /etc/iptables/rules.v4")

    print("Done!")


if __name__ == "__main__":
    main()
