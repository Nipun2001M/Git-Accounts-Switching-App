#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/GitHub Switch.app"
ICONSET="$APP/Contents/Resources/AppIcon.iconset"
SOURCE_PNG="$ROOT/scripts/icon_1024.png"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$ICONSET"

python3 "$ROOT/scripts/make_icon.py" "$SOURCE_PNG"

copy_icon() {
  local size="$1"
  local name="$2"
  sips -z "$size" "$size" "$SOURCE_PNG" --out "$ICONSET/$name" >/dev/null
}

copy_icon 16 icon_16x16.png
copy_icon 32 icon_16x16@2x.png
copy_icon 32 icon_32x32.png
copy_icon 64 icon_32x32@2x.png
copy_icon 128 icon_128x128.png
copy_icon 256 icon_128x128@2x.png
copy_icon 256 icon_256x256.png
copy_icon 512 icon_256x256@2x.png
copy_icon 512 icon_512x512.png
copy_icon 1024 icon_512x512@2x.png
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET" "$SOURCE_PNG"

cp "$ROOT/macos/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
printf '%s\n' "$ROOT/ghsw.py" > "$APP/Contents/Resources/cli.path"

swiftc -parse-as-library -O \
  -framework AppKit -framework SwiftUI \
  -o "$APP/Contents/MacOS/GitHub Switch" \
  "$ROOT/macos/GitHubSwitchApp.swift"

codesign --force --deep --sign - "$APP"
echo "Built $APP"
