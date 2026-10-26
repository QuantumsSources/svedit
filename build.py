import os
import sys
import time
import shutil
import subprocess

from pathlib import Path
from subprocess import CompletedProcess
from src.svedit_core import VERSION, VERSION_NAME

BUILD_SCRIPT_VERSION = "1.6"

argv = sys.argv[1:]
QUIET_MODE = "--quiet" in argv
BUILD_ONLY_MODE = "--buildonly" in argv
SKIP_BUILD_MODE = "--skipbuild" in argv
NO_CONFIRMATION_MODE = "--yes" in argv

if "--help" in sys.argv[1:]:
    print("> running with:")
    print(">    '--quiet' will print reduced information;")
    print(">    '--help' will print this help message and exit early;")
    print(">    '--buildonly' will only build svedit, not install it;")
    print(">    '--skipbuild' will not build svedit, just install it;")
    print(">    '--yes' will not ask for confirmation at any point;")
    print(">            (not recommended!)")
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
elif SKIP_BUILD_MODE:
    print("> - only install svedit, not build it;")
else:
    print("> - build and install svedit;")

def run(args: str|Path|list[str|Path], show_output: bool = False, sudo: bool = False) -> CompletedProcess:
    if isinstance(args, (str, Path)):
        args = [args]
    args = list[str](map(str, args))
    if sudo:
        print(f"warn: running {' '.join(map(str, args))} as sudo!")
        _args = ["sudo", "-k", "-p", "      password: "]
        _args.extend(args)
        args = _args
        show_output = True
    return subprocess.run(args,
        stdout=subprocess.DEVNULL if not show_output else None,
        stderr=subprocess.DEVNULL if not show_output else None
    )

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
if not SKIP_BUILD_MODE:
    _clean()

result = run(["killall", "svedit"])
if result.returncode == 0:
    _print("> killed previous svedit processes\n")

HOME = Path.home().resolve()
LOCAL_DIR = HOME / ".svedit"
INSTALL_DIR = HOME / ".local/share/svedit"
BIN_DIR = HOME / ".local/bin"
DESKTOP_DIR = HOME / ".local/share/applications"

SRC_DIR = Path("src")
BUILD_TARGET = SRC_DIR / "svedit.py"
SRC_FMTS_DIR = Path("fmts")
FMTS_DIR = Path(LOCAL_DIR / "fmts")

ROOT_BIN_DIR = Path("/usr/bin")
ROOT_SHARE_DIR = Path("/usr/share") / "svedit"

if not BUILD_TARGET.exists():
    print(f"error: could not find build target at {BUILD_TARGET}")
    print(f"       make sure to be in directory {Path(__file__).resolve().parent} and try again")
    sys.exit(1)

def _build() -> CompletedProcess:
    if SKIP_BUILD_MODE:
        return CompletedProcess(
            ["echo"], 0,
            "> this would build svedit. (skipped due to --skipbuild)\n", ""
        )

    build_cmd = ["nuitka", "--mode=standalone", "--include-package=yaml", str(BUILD_TARGET)]
    try:
        start_time = time.time()
        process = subprocess.Popen(
            build_cmd,
            stdout=subprocess.PIPE if QUIET_MODE else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if QUIET_MODE else None,
            text=True
        )

        if QUIET_MODE:
            while process.poll() is None:
                elapsed = time.time() - start_time
                print(f"\r> building svedit... {_get_time(elapsed)} elapsed   ", end="", flush=True)
                time.sleep(0.1)

        stdout, stderr = process.communicate()
        if QUIET_MODE:
            print()
        if process.returncode != 0 and QUIET_MODE and stdout:
            print(stdout)
        return CompletedProcess(build_cmd, process.returncode, stdout, stderr)
    except KeyboardInterrupt:
        print("\nerror: build interrupted!")
        sys.exit(1)

def _get_confirmation(prompt: str, accept_empty: bool = True) -> bool:
    if NO_CONFIRMATION_MODE:
        _print(f"> {prompt} (auto accepted with --yes)")
        return True

    suffix = "[Y/n]" if accept_empty else "[y/N]"
    accept = ("y", "yes", "") if accept_empty else ("y", "yes")
    try:
        return input(f"> {prompt} {suffix} ") in accept
    except KeyboardInterrupt:
        print("\nerror: interrupt signal received!")
        sys.exit(1)

if not BUILD_ONLY_MODE and not SKIP_BUILD_MODE:
    if INSTALL_DIR.exists() and _get_confirmation(f"clean old build files? ({INSTALL_DIR})"):
        (BIN_DIR / "selfhex.bin").unlink(True)
        shutil.rmtree(INSTALL_DIR)
        _print("> cleaned old build files\n")
    if (ROOT_BIN_DIR / "svedit").exists() and _get_confirmation(f"clean old global install?"):
        run(["unlink", ROOT_BIN_DIR / "svedit"], sudo=True)
        run(["rm", "-r", ROOT_SHARE_DIR], sudo=True)

def _get_time(s: float|int) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s"

print(f"> compiling svedit v{VERSION} ({VERSION_NAME}) (this might take a while!)")
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
    if not LOCAL_DIR.exists():
        _print(f"> creating {LOCAL_DIR} directory")
        LOCAL_DIR.mkdir(exist_ok=True)

    if (LOCAL_DIR / "fmts").exists():
        _print(f"> removing old {LOCAL_DIR}/fmts directory")
        shutil.rmtree(LOCAL_DIR / "fmts")

    _print(f"> copying fmts to {LOCAL_DIR}/fmts")
    shutil.copytree(SRC_FMTS_DIR, LOCAL_DIR / "fmts")

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
desktop_content = f"""\
[Desktop Entry]
Version=1.0
Name=svedit
Comment=Global PlayStation© 1 Save Viewer/Editor
Exec={BIN_DIR / 'svedit'}
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

if _get_confirmation("remove temporary build files?", False):
    _clean()
    _print("> build files removed")

try:
    if run([f"{INSTALL_DIR}/svedit.bin", "-h"]).returncode != 0:
        print("\n> install failed on share, error below:")
        run([f"{INSTALL_DIR}/svedit.bin", "-h"], show_output=True)
        sys.exit(1)

    if run([f"{BIN_DIR}/svedit", "-h"]).returncode != 0:
        print("\n> install failed on bin, error below:")
        run([f"{BIN_DIR}/svedit", "-h"], show_output=True)
        sys.exit(1)
except Exception as e:
    print("error: an error occurred while testing launch")
    print(f"error: {e}")
    sys.exit(1)

if _get_confirmation(f"install globally to /usr/share?"):
    try:
        print(f"> copying {INSTALL_DIR} to {ROOT_SHARE_DIR}")
        if run(["cp", "-r", INSTALL_DIR, ROOT_SHARE_DIR], sudo=True).returncode != 0:
            raise OSError(f"Failed to copy {INSTALL_DIR} to {ROOT_SHARE_DIR}")
        _print("> copy complete\n")

        print(f"> creating symlink from {ROOT_SHARE_DIR / 'svedit.bin'} to {ROOT_BIN_DIR / 'svedit'}")
        if (ROOT_BIN_DIR / "svedit").exists():
            print(f"warn: file named svedit found in {ROOT_BIN_DIR}")
            if (ROOT_BIN_DIR / "svedit").is_symlink():
                run(["unlink", ROOT_BIN_DIR / "svedit"], sudo=True)
            else:
                run(["rm", ROOT_BIN_DIR / "svedit"], sudo=True)

        link_cmd = ["ln", "-s", ROOT_SHARE_DIR / "svedit.bin", ROOT_BIN_DIR / "svedit"]
        if run(link_cmd, sudo=True).returncode != 0:
            raise OSError(f"Failed to create symlink at {ROOT_BIN_DIR / 'svedit'}")
        _print("> symlink created")
    except OSError as e:
        print(f"error: an error occurred during global install: {e}")
        print("       reverting changes to /usr/!")
        if (ROOT_BIN_DIR / "svedit").exists():
            if (ROOT_BIN_DIR / "svedit").is_symlink():
                run(["unlink", ROOT_BIN_DIR / "svedit"], sudo=True)
                print(f"warn: unlinked {ROOT_BIN_DIR / 'svedit'}")
            elif _get_confirmation(f"found file 'svedit' in {ROOT_BIN_DIR}, but isn't a symlink. remove?"):
                run(["rm", ROOT_BIN_DIR / "svedit"], sudo=True)
                print(f"warn: removed {ROOT_BIN_DIR / 'svedit'}")

        if ROOT_SHARE_DIR.exists():
            run(["rm", "-r", ROOT_SHARE_DIR], sudo=True)
            print(f"warn: removed {ROOT_SHARE_DIR}")

        sys.exit(1)

print(f"\n> successfully installed svedit v{VERSION} ({VERSION_NAME})!")
print("> see usage with 'svedit --help'")