#!/usr/bin/env bash
# Generate a signed APT repository from one or more .deb files.
#
#   ./packaging/build-apt-repo.sh <repo-dir> <deb> [<deb> ...]
#
# The repo directory is updated in place (existing pool/ contents are kept, so
# older versions stay installable). Signing is skipped when GPG_KEY_ID is unset,
# which lets the layout be tested without a key.
#
# Env:
#   GPG_KEY_ID      key to sign with; unsigned repo if empty
#   GPG_PASSPHRASE  passphrase for that key (optional)
set -euo pipefail

REPO_DIR="${1:?usage: build-apt-repo.sh <repo-dir> <deb>...}"
shift
[ "$#" -gt 0 ] || { echo "no .deb files given" >&2; exit 1; }

SUITE="stable"
COMPONENT="main"
ARCH="all"
POOL="pool/${COMPONENT}/m/meeting-recorder"
DIST="dists/${SUITE}/${COMPONENT}/binary-${ARCH}"

mkdir -p "$REPO_DIR/$POOL" "$REPO_DIR/$DIST"

echo ">> adding packages to pool"
for deb in "$@"; do
    install -m 644 "$deb" "$REPO_DIR/$POOL/"
    echo "   $(basename "$deb")"
done

cd "$REPO_DIR"

echo ">> generating Packages index"
# Paths in the index must be relative to the repo root.
dpkg-scanpackages --arch "$ARCH" pool > "$DIST/Packages" 2>/dev/null
gzip -9nc "$DIST/Packages" > "$DIST/Packages.gz"

echo ">> generating Release"
apt-ftparchive \
    -o APT::FTPArchive::Release::Origin="meeting-recorder" \
    -o APT::FTPArchive::Release::Label="Smart Meeting Recorder" \
    -o APT::FTPArchive::Release::Suite="$SUITE" \
    -o APT::FTPArchive::Release::Codename="$SUITE" \
    -o APT::FTPArchive::Release::Architectures="$ARCH" \
    -o APT::FTPArchive::Release::Components="$COMPONENT" \
    -o APT::FTPArchive::Release::Description="Smart Meeting Recorder APT repository" \
    release "dists/$SUITE" > "dists/$SUITE/Release"

if [ -n "${GPG_KEY_ID:-}" ]; then
    echo ">> signing Release with $GPG_KEY_ID"
    GPG_ARGS=(--batch --yes --pinentry-mode loopback --local-user "$GPG_KEY_ID")
    [ -n "${GPG_PASSPHRASE:-}" ] && GPG_ARGS+=(--passphrase "$GPG_PASSPHRASE")
    # InRelease (inline signature) is what modern apt prefers; Release.gpg is
    # kept for older clients.
    gpg "${GPG_ARGS[@]}" --clearsign -o "dists/$SUITE/InRelease" "dists/$SUITE/Release"
    gpg "${GPG_ARGS[@]}" -abs -o "dists/$SUITE/Release.gpg" "dists/$SUITE/Release"
    gpg --armor --export "$GPG_KEY_ID" > KEY.gpg
    echo ">> exported public key to KEY.gpg"
else
    echo ">> GPG_KEY_ID not set - repository is UNSIGNED (testing only)"
fi

echo
echo "Repository ready in: $REPO_DIR"
find . -type f | sort | sed 's/^/  /'
