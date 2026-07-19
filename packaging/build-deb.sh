#!/usr/bin/env bash
# Build the meeting-recorder .deb package.
#
#   ./packaging/build-deb.sh              -> dist/meeting-recorder_<version>_all.deb
#
# Override the maintainer/homepage that get written into the package metadata:
#   MAINTAINER="Jane Doe <jane@example.com>" HOMEPAGE="https://..." ./packaging/build-deb.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="meeting-recorder"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/meeting_recorder/__init__.py")"
MAINTAINER="${MAINTAINER:-Smart Meeting Recorder contributors <noreply@example.com>}"
HOMEPAGE="${HOMEPAGE:-https://github.com/ssKazal/meeting-recorder}"

[ -n "$VERSION" ] || { echo "could not read __version__"; exit 1; }

BUILD="$ROOT/build/deb"
DIST="$ROOT/dist"
rm -rf "$BUILD"
mkdir -p "$DIST"

SITE="$BUILD/usr/lib/python3/dist-packages/meeting_recorder"
mkdir -p "$SITE" \
         "$BUILD/DEBIAN" \
         "$BUILD/usr/bin" \
         "$BUILD/usr/lib/systemd/user" \
         "$BUILD/usr/share/applications" \
         "$BUILD/usr/share/icons/hicolor/scalable/apps" \
         "$BUILD/usr/share/man/man1" \
         "$BUILD/usr/share/doc/$PKG"

echo ">> staging python package (v$VERSION)"
install -m 644 "$ROOT"/meeting_recorder/*.py "$SITE/"
install -m 644 "$ROOT/meeting_recorder/default_config.json" "$SITE/"

echo ">> staging entry point"
# Same file the debian/ (PPA) build installs, so both paths stay identical.
install -m 755 "$ROOT/packaging/meeting-recorder.bin" "$BUILD/usr/bin/$PKG"

echo ">> staging service, desktop entry, icon, docs"
install -m 644 "$ROOT/packaging/meeting-recorder.service" \
               "$BUILD/usr/lib/systemd/user/meeting-recorder.service"
install -m 644 "$ROOT/packaging/meeting-recorder-settings.desktop" \
               "$BUILD/usr/share/applications/meeting-recorder-settings.desktop"
install -m 644 "$ROOT/packaging/meeting-recorder.desktop" \
               "$BUILD/usr/share/applications/meeting-recorder.desktop"
install -m 644 "$ROOT/packaging/meeting-recorder.svg" \
               "$BUILD/usr/share/icons/hicolor/scalable/apps/meeting-recorder.svg"
gzip -9nc "$ROOT/packaging/meeting-recorder.1" \
    > "$BUILD/usr/share/man/man1/meeting-recorder.1.gz"
chmod 644 "$BUILD/usr/share/man/man1/meeting-recorder.1.gz"
install -m 644 "$ROOT/README.md" "$BUILD/usr/share/doc/$PKG/README.md"
sed "s#HOMEPAGE_PLACEHOLDER#$HOMEPAGE#" "$ROOT/packaging/copyright" \
    > "$BUILD/usr/share/doc/$PKG/copyright"
chmod 644 "$BUILD/usr/share/doc/$PKG/copyright"
gzip -9nc "$ROOT/CHANGELOG.md" > "$BUILD/usr/share/doc/$PKG/changelog.gz"
chmod 644 "$BUILD/usr/share/doc/$PKG/changelog.gz"

echo ">> control files"
sed -e "s#VERSION_PLACEHOLDER#$VERSION#" \
    -e "s#MAINTAINER_PLACEHOLDER#$MAINTAINER#" \
    -e "s#HOMEPAGE_PLACEHOLDER#$HOMEPAGE#" \
    "$ROOT/packaging/control" > "$BUILD/DEBIAN/control"
install -m 755 "$ROOT/packaging/postinst" "$BUILD/DEBIAN/postinst"
install -m 755 "$ROOT/packaging/prerm" "$BUILD/DEBIAN/prerm"
# Mark the shipped defaults as a conffile so local edits survive upgrades.
echo "/usr/lib/python3/dist-packages/meeting_recorder/default_config.json" \
    > "$BUILD/DEBIAN/conffiles"

DEB="$DIST/${PKG}_${VERSION}_all.deb"
echo ">> building $DEB"
dpkg-deb --root-owner-group --build "$BUILD" "$DEB" >/dev/null

echo
echo "Built: $DEB"
dpkg-deb --info "$DEB" | sed -n '1,12p'
echo
echo "Install with:  sudo apt install $DEB"
