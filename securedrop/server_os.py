import functools
import json
from datetime import date
from pathlib import Path

FOCAL_VERSION = "20.04"
NOBLE_VERSION = "24.04"

FOCAL_ENDOFLIFE = date(2025, 4, 2)


@functools.lru_cache
def get_os_release() -> str:
    with open("/etc/os-release") as f:
        os_release = f.readlines()
        for line in os_release:
            if line.startswith("VERSION_ID="):
                version_id = line.split("=")[1].strip().strip('"')
                break
    return version_id


def is_os_past_eol() -> bool:
    """
    Check if it's focal and if today is past the official EOL date
    """
    return get_os_release() == FOCAL_VERSION and date.today() >= FOCAL_ENDOFLIFE


def needs_migration_fixes() -> bool:
    """
    See if the check script has flagged any issues
    """
    if get_os_release() != FOCAL_VERSION:
        return False
    state_path = Path("/etc/securedrop-noble-migration.json")
    if not state_path.exists():
        # Script hasn't run yet
        return False
    try:
        contents = json.loads(state_path.read_text())
    except json.JSONDecodeError:
        # Invalid output from the script is an error
        return True
    if "error" in contents:
        # Something went wrong with the script itself,
        # it needs manual fixes.
        return True
    # True if any of the checks failed
    return not all(contents.values())
