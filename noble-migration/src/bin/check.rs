//! Check migration of a SecureDrop server from focal to noble
//!
//! This script is run as root on both the app and mon servers.
//!
//! It is typically run by a systemd service/timer, but we also
//! support admins running it manually to get more detailed output.
use anyhow::{bail, Context, Result};
use rustix::process::geteuid;
use serde::Serialize;
use std::{
    fs,
    path::Path,
    process::{self, ExitCode},
};
use url::{Host, Url};
use walkdir::WalkDir;

/// This file contains the state of the pre-migration checks.
///
/// There are four possible states:
/// * does not exist: check script hasn't run yet
/// * empty JSON object: script determines it isn't on focal
/// * {"error": true}: script encountered an error
/// * JSON object with boolean values for each check (see `State` struct)
const STATE_PATH: &str = "/etc/securedrop-noble-migration.json";

#[derive(Serialize)]
struct State {
    ssh: bool,
    ufw: bool,
    free_space: bool,
    apt: bool,
    systemd: bool,
}

impl State {
    fn is_ready(&self) -> bool {
        self.ssh && self.ufw && self.free_space && self.apt && self.systemd
    }
}

/// Parse the OS codename from /etc/os-release
fn os_codename() -> Result<String> {
    let contents = fs::read_to_string("/etc/os-release")
        .context("reading /etc/os-release failed")?;
    for line in contents.lines() {
        if line.starts_with("VERSION_CODENAME=") {
            // unwrap: Safe because we know the line contains "="
            let (_, codename) = line.split_once("=").unwrap();
            return Ok(codename.trim().to_string());
        }
    }

    bail!("Could not find VERSION_CODENAME in /etc/os-release")
}

/// Check that the UNIX "ssh" group has no members
///
/// See <https://github.com/freedomofpress/securedrop/issues/7316>.
fn check_ssh_group() -> Result<bool> {
    // There are no clean bindings to getgrpname in rustix,
    // so jut shell out to getent to get group members
    let output = process::Command::new("getent")
        .arg("group")
        .arg("ssh")
        .output()
        .context("spawning getent failed")?;
    if output.status.code() == Some(2) {
        println!("ssh OK: group does not exist");
        return Ok(true);
    } else if !output.status.success() {
        bail!(
            "running getent failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let stdout = String::from_utf8(output.stdout)
        .context("getent stdout is not utf-8")?;
    let members = parse_getent_output(&stdout)?;
    if members.is_empty() {
        println!("ssh OK: group is empty");
        Ok(true)
    } else {
        println!("ssh ERROR: group is not empty: {members:?}");
        Ok(false)
    }
}

/// Parse the output of `getent group ssh`, return true if empty
fn parse_getent_output(stdout: &str) -> Result<Vec<&str>> {
    let stdout = stdout.trim();
    // The format looks like `ssh:x:123:member1,member2`
    if !stdout.contains(":") {
        bail!("unexpected output from getent: '{stdout}'");
    }

    // unwrap: safe, we know the line contains ":"
    let (_, members) = stdout.rsplit_once(':').unwrap();
    if members.is_empty() {
        Ok(vec![])
    } else {
        Ok(members.split(',').collect())
    }
}

/// Check that ufw was removed
///
/// See <https://github.com/freedomofpress/securedrop/issues/7313>.
fn check_ufw_removed() -> bool {
    if Path::new("/usr/sbin/ufw").exists() {
        println!("ufw ERROR: ufw is still installed");
        false
    } else {
        println!("ufw OK: ufw was removed");
        true
    }
}

/// Estimate the size of the backup so we know how much free space we'll need.
///
/// We just check the size of `/var/lib/securedrop` since that's really the
/// data that'll take up space; everything else is just config files that are
/// negligible post-compression. We also don't estimate compression benefits.
fn estimate_backup_size() -> Result<u64> {
    let path = Path::new("/var/lib/securedrop");
    if !path.exists() {
        // mon server
        return Ok(0);
    }
    let mut total: u64 = 0;
    let walker = WalkDir::new(path);
    for entry in walker {
        let entry = entry.context("walking /var/lib/securedrop failed")?;
        if entry.file_type().is_dir() {
            continue;
        }
        let metadata = entry.metadata().context("getting metadata failed")?;
        total += metadata.len();
    }

    Ok(total)
}

/// We want to have enough space for a backup, the upgrade (~4GB of packages,
/// conservatively), and not take up more than 90% of the disk.
fn check_free_space() -> Result<bool> {
    // Also no simple bindings to get disk size, so shell out to df
    // Explicitly specify -B1 for bytes (not kilobytes)
    let output = process::Command::new("df")
        .args(["-B1", "/"])
        .output()
        .context("spawning df failed")?;
    if !output.status.success() {
        bail!(
            "running df failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let stdout =
        String::from_utf8(output.stdout).context("df stdout is not utf-8")?;
    let parsed = parse_df_output(&stdout)?;

    let backup_needs = estimate_backup_size()?;
    let upgrade_needs: u64 = 4 * 1024 * 1024 * 1024; // 4GB
    let headroom = parsed.total / 10; // 10% headroom
    let total_needs = backup_needs + upgrade_needs + headroom;

    if parsed.free < total_needs {
        println!(
            "free space ERROR: not enough free space, have {} free bytes, need {total_needs} bytes",
            parsed.free
        );
        Ok(false)
    } else {
        println!("free space OK: enough free space");
        Ok(true)
    }
}

/// Sizes are in bytes
struct DfOutput {
    total: u64,
    free: u64,
}

fn parse_df_output(stdout: &str) -> Result<DfOutput> {
    let line = match stdout.split_once('\n') {
        Some((_, line)) => line,
        None => bail!("df output didn't have a newline"),
    };
    let parts: Vec<_> = line.split_whitespace().collect();

    if parts.len() < 4 {
        bail!("df output didn't have enough columns");
    }

    // vec indexing is safe because we did the bounds check above
    let total = parts[1]
        .parse::<u64>()
        .context("parsing total space failed")?;
    let free = parts[3]
        .parse::<u64>()
        .context("parsing free space failed")?;

    Ok(DfOutput { total, free })
}

const EXPECTED_DOMAINS: [&str; 3] = [
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "apt.freedom.press",
];

const TEST_DOMAINS: [&str; 2] =
    ["apt-qa.freedom.press", "apt-test.freedom.press"];

/// Verify only expected sources are configured for apt
fn check_apt() -> Result<bool> {
    let output = process::Command::new("apt-get")
        .arg("indextargets")
        .output()
        .context("spawning apt-get indextargets failed")?;
    if !output.status.success() {
        bail!(
            "running apt-get indextargets failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let stdout = String::from_utf8(output.stdout)
        .context("apt-get stdout is not utf-8")?;
    for line in stdout.lines() {
        if line.starts_with("URI:") {
            let uri = line.strip_prefix("URI: ").unwrap();
            let parsed = Url::parse(uri)?;
            if let Some(Host::Domain(domain)) = parsed.host() {
                if TEST_DOMAINS.contains(&domain) {
                    println!("apt: WARNING test source found ({domain})");
                } else if !EXPECTED_DOMAINS.contains(&domain) {
                    println!("apt ERROR: unexpected source: {domain}");
                    return Ok(false);
                }
            } else {
                println!("apt ERROR: unexpected source: {uri}");
                return Ok(false);
            }
        }
    }

    println!("apt OK: all sources are expected");
    Ok(true)
}

/// Check that systemd has no failed units
fn check_systemd() -> Result<bool> {
    let output = process::Command::new("systemctl")
        .arg("is-failed")
        .output()
        .context("spawning systemctl failed")?;
    if output.status.success() {
        // success means some units are failed
        println!("systemd ERROR: some units are failed");
        Ok(false)
    } else {
        println!("systemd OK: all units are happy");
        Ok(true)
    }
}

fn run() -> Result<()> {
    let codename = os_codename()?;
    if codename != "focal" {
        println!("Unsupported Ubuntu version: {codename}");
        // nothing to do, write an empty JSON blob
        fs::write(STATE_PATH, "{}")?;
        return Ok(());
    }

    let state = State {
        ssh: check_ssh_group()?,
        ufw: check_ufw_removed(),
        free_space: check_free_space()?,
        apt: check_apt()?,
        systemd: check_systemd()?,
    };

    fs::write(
        STATE_PATH,
        serde_json::to_string(&state).context("serializing state failed")?,
    )
    .context("writing state file failed")?;
    if state.is_ready() {
        println!("All ready for migration!");
    } else {
        println!();
        println!(
            "Some errors were found that will block migration.

Documentation on how to resolve these errors can be found at:
<https://docs.securedrop.org/en/stable/admin/maintenance/noble_migration_prep.html>

If you are unsure what to do, please contact the SecureDrop
support team: <https://docs.securedrop.org/en/stable/getting_support.html>."
        );
        // Logically we should exit with a failure here, but we don't
        // want the systemd unit to fail.
    }
    Ok(())
}

fn main() -> Result<ExitCode> {
    if !geteuid().is_root() {
        println!("This script must be run as root");
        return Ok(ExitCode::FAILURE);
    }

    match run() {
        Ok(()) => Ok(ExitCode::SUCCESS),
        Err(e) => {
            // Try to log the error in the least complex way possible
            fs::write(STATE_PATH, "{\"error\": true}")?;
            eprintln!("Error running migration pre-check: {e}");
            Ok(ExitCode::FAILURE)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_getent_output() {
        // no members
        assert_eq!(
            parse_getent_output("ssh:x:123:\n").unwrap(),
            Vec::<&str>::new()
        );
        // one member
        assert_eq!(
            parse_getent_output("ssh:x:123:member1\n").unwrap(),
            vec!["member1"]
        );
        // two members
        assert_eq!(
            parse_getent_output("ssh:x:123:member1,member2\n").unwrap(),
            vec!["member1", "member2"]
        );
    }

    #[test]
    fn test_parse_df_output() {
        let output = parse_df_output(
            "Filesystem                           1B-blocks       Used   Available Use% Mounted on
/dev/mapper/ubuntu--vg-ubuntu--lv 105089261568 8573784064 91129991168   9% /
",
        )
        .unwrap();

        assert_eq!(output.total, 105089261568);
        assert_eq!(output.free, 91129991168);
    }
}
