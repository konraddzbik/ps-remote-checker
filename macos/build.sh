#!/bin/bash
# Builds "PS Remote Checker.app" (universal: Apple silicon + Intel) into macos/build/.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
BUILD="build"
APP="$BUILD/PS Remote Checker.app"
MIN_OS="13.0"

rm -rf "$APP" "$BUILD/tmp"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$BUILD/tmp"

echo "→ compiling Swift (arm64 + x86_64)"
for arch in arm64 x86_64; do
  swiftc -swift-version 5 -parse-as-library -O \
    -target "$arch-apple-macos$MIN_OS" \
    Sources/*.swift -o "$BUILD/tmp/PSRemoteChecker-$arch"
done
lipo -create "$BUILD"/tmp/PSRemoteChecker-* -output "$APP/Contents/MacOS/PSRemoteChecker"

echo "→ app icon"
swift Resources/make_icon.swift "$BUILD/tmp/AppIcon.iconset" >/dev/null
iconutil -c icns "$BUILD/tmp/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"

echo "→ bundling checker engine"
cp Resources/Info.plist "$APP/Contents/Info.plist"
rsync -a --exclude '__pycache__' "$ROOT/ps_remote_checker" "$APP/Contents/Resources/"
mkdir -p "$APP/Contents/Resources/rpi"
cp "$ROOT/deploy/rpi/install.sh" "$APP/Contents/Resources/rpi/install.sh"

echo "→ signing (ad-hoc)"
codesign --force --deep --sign - "$APP"
rm -rf "$BUILD/tmp"
echo "✔ built $APP"
