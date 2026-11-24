#!/usr/bin/env bash
# Build a macOS .app and .dmg (run on macOS, from the repo root). Signing/notarization only if the env vars are set:
#   SIGN_ID="Developer ID Application: Name (TEAMID)"   NOTARY_PROFILE=<notarytool keychain profile>
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="$(python3 tools/brand.py app_name)"; ID="$(python3 tools/brand.py app_id)"; VER="$(python3 tools/brand.py version)"
brew list mpv >/dev/null 2>&1 || brew install mpv
brew list create-dmg >/dev/null 2>&1 || brew install create-dmg
brew list dylibbundler >/dev/null 2>&1 || brew install dylibbundler

python3 -m venv .venv-build && . .venv-build/bin/activate
pip install -q --upgrade pip && pip install -q . pyinstaller pillow
python tools/make_icons.py

LIBMPV="$(brew --prefix mpv)/lib/libmpv.2.dylib"
pyinstaller --noconfirm --clean --windowed --name "$NAME" --osx-bundle-identifier "org.$ID" \
  --icon like_potplayer/assets/build/app.icns \
  --add-data "like_potplayer/defaults:like_potplayer/defaults" \
  --add-data "like_potplayer/assets:like_potplayer/assets" \
  --add-binary "$LIBMPV:." packaging/entry.py

APP="dist/$NAME.app"
# pull libmpv's own dependencies (ffmpeg, etc.) into the bundle
dylibbundler -od -b -x "$APP/Contents/MacOS/$NAME" -d "$APP/Contents/Frameworks" -p @executable_path/../Frameworks || true

# declare the media types so Finder offers "Open with"
P="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes array" "$P" || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0 dict" -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string Media" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer" \
  -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes array" \
  -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:0 string public.movie" \
  -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:1 string public.audio" "$P" || true

[ -z "${SIGN_ID:-}" ] || codesign --deep --force --options runtime --sign "$SIGN_ID" "$APP"
DMG="dist/$NAME-$VER-$(uname -m).dmg"
create-dmg --volname "$NAME" --app-drop-link 480 120 "$DMG" "$APP"
if [ -n "${SIGN_ID:-}" ] && [ -n "${NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi
echo "built $DMG"
