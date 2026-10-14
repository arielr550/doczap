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
fi
mkdir -p "$APPS_DIR"
APP=$APPS_DIR/DocZap.app
if [ -L "$APP" ] || { [ -e "$APP" ] && [ ! -d "$APP" ]; }; then
    echo "Cannot install: $APP is a symlink or is not an app directory." >&2
    exit 1
fi

# Serialize installers so an update cannot move another update's app or backup.
LOCK_DIR=$APPS_DIR/.doczap-install.lock
if ! mkdir "$LOCK_DIR"; then
    echo "Another install may be running. If it stopped, remove $LOCK_DIR and retry." >&2
    exit 1
fi
STAGE_DIR=
INSTALLED=0
cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$STAGE_DIR" ]; then
        if [ -d "$STAGE_DIR/previous.app" ] && [ "$INSTALLED" -eq 0 ]; then
            if [ ! -e "$APP" ] && [ ! -L "$APP" ] && mv "$STAGE_DIR/previous.app" "$APP"; then
                echo "Restored the previous DocZap installation." >&2
            else
                # A failed restore must not turn into deletion of the backup.
                echo "The previous app is saved at $STAGE_DIR/previous.app. Restore it manually." >&2
                STAGE_DIR=
                status=1
            fi
        fi
        if [ -n "$STAGE_DIR" ]; then
            rm -rf "$STAGE_DIR"
        fi
    fi
    rmdir "$LOCK_DIR" || status=1
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Stage on the destination filesystem so the final moves are renames, not copies.
STAGE_DIR=$(mktemp -d "$APPS_DIR/.doczap-install.XXXXXX")
echo "Downloading DocZap…"
curl -fsSL -o "$STAGE_DIR/DocZap.zip" "$ZIP_URL"
ditto -x -k "$STAGE_DIR/DocZap.zip" "$STAGE_DIR"
NEW_APP=$STAGE_DIR/DocZap.app
if [ -L "$NEW_APP" ] || [ ! -d "$NEW_APP" ] ||
    [ ! -f "$NEW_APP/Contents/Info.plist" ] ||
    [ ! -f "$NEW_APP/Contents/MacOS/DocZap" ] ||
    [ ! -x "$NEW_APP/Contents/MacOS/DocZap" ]; then
    echo "The download does not contain a complete DocZap.app bundle." >&2
    exit 1
fi
plutil -lint "$NEW_APP/Contents/Info.plist"
if [ "$(plutil -extract CFBundleExecutable raw -o - "$NEW_APP/Contents/Info.plist")" != DocZap ]; then
    echo "The downloaded app has an unexpected executable." >&2
    exit 1
fi
codesign --verify --deep --strict "$NEW_APP"

# Recheck after download and validation, before touching an existing installation.
if [ -L "$APP" ] || { [ -e "$APP" ] && [ ! -d "$APP" ]; }; then
    echo "Cannot replace: $APP is a symlink or is not an app directory." >&2
    exit 1
fi
if [ -d "$APP" ]; then
    echo "Replacing the DocZap already in $APPS_DIR"
    mv "$APP" "$STAGE_DIR/previous.app"
fi
mv "$NEW_APP" "$APP"
INSTALLED=1
echo "Installed $APP"

if [ ! -d /Applications/LibreOffice.app ] && [ ! -d "$HOME/Applications/LibreOffice.app" ]; then
    echo
    echo "DocZap needs LibreOffice to convert documents. Install it with"
    echo "  brew install --cask libreoffice"
    echo "or from https://www.libreoffice.org/download/"
fi
