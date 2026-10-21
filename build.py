import os
import sys
import time
import shutil
import subprocess

from pathlib import Path
from subprocess import CompletedProcess
from src.svedit_core import VERSION, VERSION_NAME

BUILD_SCRIPT_VERSION = "1.4"

argv = sys.argv[1:]
QUIET_MODE = "--quiet" in argv
BUILD_ONLY_MODE = "--buildonly" in argv
NO_CONFIRMATION_MODE = "--yes" in argv

if "--help" in sys.argv[1:]:
    print("> running with:")
    print(">    '--help' will: print this help message and exit early;")
    print(">    '--buildonly' will: only build svedit, not install it;")
    print(">    '--yes' will: not ask for confirmation at any point;")
    print(">                  (be sure you know everything this script will do!)")
    sys.exit(0)

def _print(s: str) -> None:
    if QUIET_MODE:
        return
    print(s)

print(f"> running build.py v{BUILD_SCRIPT_VERSION}.")
print("> this run will:")
if NO_CONFIRMATION_MODE:
    print("> - not ask for confirmation;")
if QUIET_MODE:
    print("> - print reduced information;")
if BUILD_ONLY_MODE:
    print("> - only build svedit, not install it;")
else:
    print("> - build and install svedit;")

def run(args: str|list[str], show_output: bool = False) -> CompletedProcess:
    return subprocess.run(args, stderr=subprocess.DEVNULL if not show_output else None)

if sys.platform not in ("linux", "android"):
    print("error: currently svedit only works on linux!")
    sys.exit(1)

if sys.version_info < (3, 10):
    print("error: svedit requires python 3.10 or higher to build.")
    sys.exit(1)

if shutil.which("nuitka") is None and run(["python", "-m", "nuitka", "--version"]).returncode != 0:
    print("error: 'nuitka' is not installed")
    print("       install via pip, pipx, or native (aur, apt, etc...)")
    sys.exit(1)

def _clean():
    if Path("svedit.dist").exists():
        shutil.rmtree(Path("svedit.dist"))
    if Path("svedit.build").exists():
        shutil.rmtree(Path("svedit.build"))

os.chdir(Path(__file__).resolve().parent)
_clean()

result = run(["killall", "svedit"])
if result.returncode == 0:
    _print("> killed previous svedit processes\n")

HOME = Path.home()
INSTALL_DIR = HOME / ".local/share/svedit"
BIN_DIR = HOME / ".local/bin"
DESKTOP_DIR = HOME / ".local/share/applications"

SRC_DIR = Path("src")
BUILD_TARGET = SRC_DIR / "svedit.py"
SRC_FMTS_DIR = Path("fmts")
FMTS_DIR = Path(INSTALL_DIR / "fmts")

if not BUILD_TARGET.exists():
    print(f"error: could not find build target at {BUILD_TARGET}")
    print(f"       make sure to be in directory {Path(__file__).resolve().parent} and try again")
    sys.exit(1)

def _build() -> CompletedProcess:
    cmd = ["nuitka", "--mode=standalone", "--include-package=yaml", str(BUILD_TARGET)]
    try:
        return subprocess.run(cmd, stderr=subprocess.DEVNULL if QUIET_MODE else None)
    except KeyboardInterrupt:
        print("\nerror: build interrupted!")
        sys.exit(1)

def _get_confirmation(prompt: str) -> bool:
    if NO_CONFIRMATION_MODE:
        _print(f"> {prompt} (auto accepted with --yes)")
        return True

    try:
        return input(f"{prompt} [Y/n] ") in ("y", "yes", "")
    except KeyboardInterrupt:
        print("\nerror: interrupt signal received!")
        sys.exit(1)

if not BUILD_ONLY_MODE and INSTALL_DIR.exists():
    if _get_confirmation(f"clean old build files? ({INSTALL_DIR})"):
        (BIN_DIR / "selfhex.bin").unlink(True)
        shutil.rmtree(INSTALL_DIR)
        _print("> cleaned old build files\n")

def _get_time(s: float|int) -> str:
    if s < 60:
        return f"{s:.2f}s"
    units = ["s", "m", "h"]
    idx = 0
    while s > 60:
        s = s / 60
        idx += 1
    idx = min(len(units), idx)
    return f"{int(s)}{units[idx]} {int(60 * (s - int(s)))}{units[idx - 1]}"

_print(f"> compiling svedit v{VERSION} ({VERSION_NAME}) (this might take a while!)")
start = time.time()
result = _build()

if result.returncode != 0:
    if BUILD_ONLY_MODE or shutil.which("pipx") is None:
        print("error: build failed")
        sys.exit(1)

    print("warn: build failed, attempting correction.")
    if _get_confirmation("if you're using pipx nuitka, try injecting pyyaml into nuitka venv?"):
        _print("> ensuring pipx venv is in path")
        run(["pipx", "ensurepath"])
        _print("> injecting pyyaml into nuitka venv")
        result = run(["pipx", "inject", "nuitka", "pyyaml"])
        if result.returncode != 0:
            print("error: injection failed.")
            sys.exit(1)
        result = _build()
        if result.returncode != 0:
            print("error: build failed.")
            sys.exit(1)
    else:
        print("error: build failed.")
        sys.exit(1)
print(f"> build complete in {_get_time(time.time() - start)}!")

DIST_DIR = Path("svedit.dist")
BUILD_DIR = Path("svedit.build")
if not DIST_DIR.exists() or not BUILD_DIR.exists():
    print(f"error: expected build output at {DIST_DIR} and {BUILD_DIR}, of which one or both were not found:")
    if not DIST_DIR.exists():
        print(f"       {DIST_DIR} was not found.")
    if not BUILD_DIR.exists():
        print(f"       {BUILD_DIR} was not found.")
    sys.exit(1)

if BUILD_ONLY_MODE:
    if (DIST_DIR / "fmts").exists():
        _print(f"> removing old {DIST_DIR}/fmts directory")
        shutil.rmtree(DIST_DIR / "fmts")

    _print(f"> copying fmts to {DIST_DIR}/fmts")
    shutil.copytree(SRC_FMTS_DIR, DIST_DIR / "fmts")

    _print(f"> copying icon to {DIST_DIR}")
    shutil.copy(SRC_DIR / "svedit.png", DIST_DIR)

    if run([f"./{DIST_DIR}/svedit.bin", "-h"], show_output=True).returncode != 0:
        print("error: build failed!")
        sys.exit(1)

    print("> build successful!")
    sys.exit(0)

_print(f"> installing to {INSTALL_DIR}")
INSTALL_DIR.mkdir(parents=True, exist_ok=True)
BIN_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_DIR.mkdir(parents=True, exist_ok=True)

shutil.copy(SRC_DIR / "svedit.png", DIST_DIR)
shutil.copytree(DIST_DIR, INSTALL_DIR, dirs_exist_ok=True)
shutil.copytree(SRC_FMTS_DIR, FMTS_DIR, dirs_exist_ok=True)

symlink_path = BIN_DIR / "svedit"
if symlink_path.is_symlink() or symlink_path.exists():
    symlink_path.unlink()
symlink_path.symlink_to(INSTALL_DIR / "svedit.bin")

icon_file = INSTALL_DIR / "svedit.png"
icon_path = str(icon_file) if icon_file.exists() else "utilities-terminal"

_print(f"\n> creating desktop entry in {DESKTOP_DIR}")
desktop_content = f"""[Desktop Entry]
Version=1.0
Name=svedit
Comment=Global PlayStation© 1 Save Viewer/Editor
Exec={BIN_DIR / 'svedit'} %F
Icon={icon_path}
Terminal=true
Type=Application
Categories=Utility;
"""

desktop_file = DESKTOP_DIR / "svedit.desktop"
desktop_file.write_text(desktop_content)

if _get_confirmation("update desktop database and icon cache?"):
    _print("> updating desktop database")
    run("update-desktop-database")
    _print("> updating icon cache")
    run("gtk-update-icon-cache")

if _get_confirmation("remove temporary build files?"):
    _clean()
    _print("> build files removed")

if run([f"./{INSTALL_DIR}/svedit.bin", "-h"]).returncode != 0:
    print("\n> install failed on share, error below:")
    run([f"./{INSTALL_DIR}/svedit.bin", "-h"], show_output=True)
    sys.exit(1)

if run([f"./{BIN_DIR}/svedit", "-h"]).returncode != 0:
    print("\n> install failed on bin, error below:")
    run([f"./{BIN_DIR}/svedit", "-h"], show_output=True)
    sys.exit(1)

print(f"\n> svedit successfully installed svedit v{VERSION} ({VERSION_NAME})!")
print("> see usage with 'svedit --help'")