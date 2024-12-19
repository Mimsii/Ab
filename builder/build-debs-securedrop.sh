#!/bin/bash
# shellcheck disable=SC2209
# Build SecureDrop packages. This runs *inside* the container.

export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_PROGRESS_BAR=off
export CARGO_TERM_COLOR=never
export CARGO_TERM_PROGRESS_WHEN=never

set -euxo pipefail

# Make a copy of the source tree since we do destructive operations on it
cp -R /src/securedrop /srv/securedrop
mkdir /srv/rust
cp -R /src/noble-migration /srv/rust/noble-migration
cp -R /src/redwood /srv/rust/redwood
cp /src/Cargo.{toml,lock} /srv/rust/
cd /srv/securedrop/

# Control the version of setuptools used in the default construction of virtual environments
# TODO: get rid of this when we switch to reproducible wheels
pip3 download --no-deps --require-hashes -r requirements/python3/requirements.txt --dest /tmp/requirements-download
rm -f /usr/share/python-wheels/setuptools-*.whl
mv /tmp/requirements-download/setuptools-*.whl /usr/share/python-wheels/

# Add the distro suffix to the version
bash /fixup-changelog

# Build the package
dpkg-buildpackage -us -uc

# Copy the built artifacts back and print checksums
source /etc/os-release
mkdir -p "/src/build/${VERSION_CODENAME}"
mv -v ../*.{buildinfo,changes,deb,ddeb,tar.gz} "/src/build/${VERSION_CODENAME}"
cd "/src/build/${VERSION_CODENAME}"
# Rename "ddeb" packages to just "deb"
for file in *.ddeb; do
    mv "$file" "${file%.ddeb}.deb";
done
sha256sum ./*
