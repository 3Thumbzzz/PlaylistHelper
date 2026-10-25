"""Build PlaylistHelper with PyInstaller.

Windows: dist/PlaylistHelper.exe (single file)
macOS:   dist/PlaylistHelper.app, packed into dist/PlaylistHelper.dmg

A Mac build has to run on a Mac (PyInstaller can't cross-compile); the GitHub
Actions workflow in .github/workflows/build.yml does both in the cloud.
"""
import os
import plistlib
import shutil
import subprocess
import sys

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "PlaylistHelper"
# Oldest macOS the bundled Qt runs on (see the PySide6 pin in requirements.txt). Older
# Macs get a clear "needs a newer macOS" message instead of the app silently dying.
MIN_MACOS = "12.0"


def finish_mac_app(app: str) -> None:
    """Set the minimum macOS version, then re-sign (editing Info.plist breaks the
    ad-hoc signature, and Apple Silicon kills apps with a broken signature)."""
    plist = os.path.join(app, "Contents", "Info.plist")
    with open(plist, "rb") as f:
        info = plistlib.load(f)
    info["LSMinimumSystemVersion"] = MIN_MACOS
    with open(plist, "wb") as f:
        plistlib.dump(info, f)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app], check=True)


def main() -> None:
    os.chdir(HERE)
    args = [
        "playlist_helper.py",
        "--name", NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        # pyrekordbox ships data files and loads sqlcipher3 dynamically;
        # ytmusicapi reads locale files at runtime.
        "--collect-all", "pyrekordbox",
        "--collect-all", "sqlcipher3",
        "--collect-data", "ytmusicapi",
    ]
    if sys.platform == "win32":
        args.append("--onefile")
    elif sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "com.playlisthelper.app"]
    PyInstaller.__main__.run(args)

    if sys.platform == "darwin":
        finish_mac_app(os.path.join("dist", f"{NAME}.app"))
        dmg = os.path.join("dist", f"{NAME}.dmg")
        staging = os.path.join("build", "dmg")
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging)
        shutil.copytree(os.path.join("dist", f"{NAME}.app"), os.path.join(staging, f"{NAME}.app"), symlinks=True)
        os.symlink("/Applications", os.path.join(staging, "Applications"))  # drag-to-install shortcut
        if os.path.exists(dmg):
            os.remove(dmg)
        subprocess.run(["hdiutil", "create", "-volname", NAME, "-srcfolder", staging,
                        "-ov", "-format", "UDZO", dmg], check=True)
        print(f"Built {dmg}")
    elif sys.platform == "win32":
        print(f"Built dist\\{NAME}.exe")


if __name__ == "__main__":
    main()
