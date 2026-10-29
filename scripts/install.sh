#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT/scripts/build_app.sh"

mkdir -p "$ROOT/bin"
cat > "$ROOT/bin/ghsw" << EOF
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:\${PATH:-}"
exec /opt/homebrew/bin/python3 "$ROOT/ghsw.py" "\$@"
EOF
chmod +x "$ROOT/bin/ghsw" "$ROOT/ghsw.py"
ln -sfn "$ROOT/bin/ghsw" /opt/homebrew/bin/ghsw

DEST="/Applications/GitHub Switch.app"
if [[ ! -w /Applications ]]; then
  mkdir -p "$HOME/Applications"
  DEST="$HOME/Applications/GitHub Switch.app"
fi
rm -rf "$DEST"
ditto "$ROOT/GitHub Switch.app" "$DEST"

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "$LSREGISTER" ]]; then
  "$LSREGISTER" -f "$DEST"
fi

echo "Command: ghsw"
echo "App: $DEST"
