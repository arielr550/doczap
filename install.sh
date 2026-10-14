#!/bin/sh
# Install or update DocZap on macOS:
#
#   curl -fsSL https://raw.githubusercontent.com/arielr550/doczap/main/install.sh | sh
#
# Downloads the latest release into /Applications (or ~/Applications when
# /Applications is not writable). DocZap is not notarized by Apple; a download
# made with curl is not quarantined, so macOS opens it without a warning.

set -eu

REPO=arielr550/doczap
ZIP_URL=${DOCZAP_ZIP_URL:-https://github.com/$REPO/releases/latest/download/DocZap-macos-arm64.zip}

if [ "$(uname -s)" != Darwin ]; then
    echo "This installer is for macOS. For Windows, download DocZap-windows-x64.zip from"
    echo "https://github.com/$REPO/releases/latest"
    exit 1
fi
if [ "$(uname -m)" != arm64 ]; then
    echo "DocZap is built for Macs with Apple silicon only, for now."
    exit 1
fi

if [ -n "${DOCZAP_APPS_DIR:-}" ]; then
    APPS_DIR=$DOCZAP_APPS_DIR
elif [ -w /Applications ]; then
    APPS_DIR=/Applications
else
    APPS_DIR=$HOME/Applications
    mkdir -p "$APPS_DIR"
fi

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Downloading DocZap…"
curl -fsSL -o "$WORK_DIR/DocZap.zip" "$ZIP_URL"
ditto -x -k "$WORK_DIR/DocZap.zip" "$WORK_DIR"

if [ -e "$APPS_DIR/DocZap.app" ]; then
    echo "Replacing the DocZap already in $APPS_DIR"
    rm -rf "$APPS_DIR/DocZap.app"
fi
mv "$WORK_DIR/DocZap.app" "$APPS_DIR/DocZap.app"
echo "Installed $APPS_DIR/DocZap.app"

if [ ! -d /Applications/LibreOffice.app ] && [ ! -d "$HOME/Applications/LibreOffice.app" ]; then
    echo
    echo "DocZap needs LibreOffice to convert documents. Install it with"
    echo "  brew install --cask libreoffice"
    echo "or from https://www.libreoffice.org/download/"
fi
