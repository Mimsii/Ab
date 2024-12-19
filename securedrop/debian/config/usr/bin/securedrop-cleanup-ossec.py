#!/usr/bin/python3
"""
Delete OSSEC diff/state files older than a year

Runs as root on both app and mon servers
"""

import os
import re
from datetime import datetime, timedelta

OSSEC_DIFFS = "/var/ossec/queue/diff/local/"
KEEP_DAYS = 365
# Match e.g. state.1667271785
RE_REMOVE = re.compile(r"^(state|diff)\.\d+$")


def main() -> None:
    cutoff_date = datetime.now() - timedelta(days=KEEP_DAYS)

    for root, dirs, files in os.walk(OSSEC_DIFFS):
        for file in files:
            if RE_REMOVE.match(file):
                file_path = os.path.join(root, file)
                modified_time = os.path.getmtime(file_path)
                file_modified_date = datetime.fromtimestamp(modified_time)
                if file_modified_date < cutoff_date:
                    os.remove(file_path)
                    print(f"Deleted file: {file_path} (Last modified: {file_modified_date})")


if __name__ == "__main__":
    main()
