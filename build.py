"""Build PlaylistHelper with PyInstaller.

Windows: dist/PlaylistHelper.exe (single file)
macOS:   dist/PlaylistHelper.app, packed into dist/PlaylistHelper.dmg

A Mac build has to run on a Mac (PyInstaller can't cross-compile); the GitHub
Actions workflow in .github/workflows/build.yml does both in the cloud.
"""
import os
import plistlib
import re
import shutil
import subprocess
import sys

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "PlaylistHelper"
# Oldest macOS the bundled Qt runs on (see the PySide6 pin in requirements.txt). Older
# Macs get a clear "needs a newer macOS" message instead of the app silently dying.
MIN_MACOS = "12.0"
MACHO_MAGIC = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
               b"\xca\xfe\xba\xbe"}  # 64/32-bit, both byte orders, universal


def check_min_macos(app: str) -> None:
    """Fail the build if any bundled binary needs a newer macOS than MIN_MACOS. The build
    machine runs a newer macOS than many users, and pip happily picks wheels built for it."""
    limit = tuple(int(x) for x in MIN_MACOS.split("."))
    too_new = []
    for folder, _, files in os.walk(app):
        for name in files:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue
            with open(path, "rb") as f:
                if f.read(4) not in MACHO_MAGIC:
                    continue
            out = subprocess.run(["otool", "-arch", "all", "-l", path], capture_output=True, text=True).stdout
            # LC_BUILD_VERSION has "minos 14.0"; older binaries have LC_VERSION_MIN_MACOSX "version 10.9".
            # Other load commands (LC_SOURCE_VERSION) also print "version", so look only in these two.
            versions = []
            for cmd in re.split(r"^Load command \d+$", out, flags=re.M):
                if re.search(r"^\s*cmd LC_BUILD_VERSION$", cmd, re.M):
                    v = re.search(r"^\s*minos (\d+(?:\.\d+)*)$", cmd, re.M)
                elif re.search(r"^\s*cmd LC_VERSION_MIN_MACOSX$", cmd, re.M):
                    v = re.search(r"^\s*version (\d+(?:\.\d+)*)$", cmd, re.M)
                else:
                    continue
                if v:
                    versions.append(tuple(int(x) for x in v.group(1).split(".")))
            if versions and max(versions) > limit:
                too_new.append(f"  {os.path.relpath(path, app)} needs macOS {'.'.join(map(str, max(versions)))}")
    if too_new:
        sys.exit(f"These files need a newer macOS than MIN_MACOS {MIN_MACOS}:\n" + "\n".join(too_new))


def finish_mac_app(app: str) -> None:
    """Check every binary runs on MIN_MACOS, set it as the minimum, then re-sign (editing
    Info.plist breaks the ad-hoc signature, and Apple Silicon kills apps with a broken one)."""
    check_min_macos(app)
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
    try:
        main()
    except (SystemExit, Exception) as e:
        if os.environ.get("GITHUB_ACTIONS") and getattr(e, "code", 1) not in (0, None):
            # Show the reason on the workflow run page (job logs need a GitHub login)
            msg = str(e.code if isinstance(e, SystemExit) else repr(e))
            print("::error title=build.py failed::" + msg.replace("%", "%25").replace("\n", "%0A"))
        raise
