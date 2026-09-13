#!/usr/bin/env bash
set -euo pipefail
python_bin=${PYTHON:-python3}
"$python_bin" -m PyInstaller --noconfirm --clean --onedir --name powertimer --distpath build/linux-dist --workpath build/linux-work --specpath build python_exp.py
appdir=build/PowerTimer.AppDir
mkdir -p "$appdir/usr/bin"
cp -a build/linux-dist/powertimer "$appdir/usr/bin/"
install -m 755 packaging/AppRun "$appdir/AppRun"
install -m 644 packaging/powertimer.desktop "$appdir/powertimer.desktop"
install -m 644 packaging/powertimer.svg "$appdir/powertimer.svg"
install -m 644 LICENSE "$appdir/LICENSE"
mkdir -p dist
curl --fail --location --retry 3 --output build/appimagetool.AppImage https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
printf '%s\n' 'ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0  build/appimagetool.AppImage' | sha256sum --check
chmod +x build/appimagetool.AppImage
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 build/appimagetool.AppImage "$appdir" dist/PowerTimer-Linux-x86_64.AppImage
