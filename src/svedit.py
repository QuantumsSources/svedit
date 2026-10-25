import os
import re
import sys
import subprocess
import svedit_db as db
import svedit_core as core
import svedit_commons as cmn

from pathlib import Path
from types import TracebackType
from svedit_pick import CardPicker
from svedit_edit import MCDFileEditor
from svedit_desktop import SvEditDesktop
from ansicodelib import ANSIColors as colors
from svedit_core import info, warn, err, UserExitCommand

class ArgumentParserError(Exception):
    """Base class for argument parser errors."""

class UnexpectedArgError(ArgumentParserError):
    """Raised when an argument is received while expecting a file."""

class UnfinishedModError(ArgumentParserError):
    """Raised when arguments end while still expecting a file for a mod."""

class UnnamedArgError(ArgumentParserError):
    """Raised when an unnamed mod or kwarg is encountered."""

SPECIAL_MODS = {}

def parse_args(args: list[str]) -> tuple[dict[str, str|bool], dict[str, str|int|float|bool|None], list[Path]]:
    mods: dict[str, str|bool] = {}
    kwargs: dict[str, str|int|float|bool|None] = {}
    files: list[Path] = []
    waiting_on_file: str|None = None

    for arg in args:
        if arg.startswith("--"):
            kwarg_raw = arg.removeprefix("--")
            name = kwarg_raw.rsplit("=", 1)[0]

            if waiting_on_file is not None:
                err_target = f"kwarg '{name}'" if name else "unnamed kwarg"
                raise UnexpectedArgError(f"Expected file for mod '{waiting_on_file}', "
                                         f"found {err_target}.")

            if not name:
                raise UnnamedArgError("Found unnamed kwarg.")

            if "=" in kwarg_raw:
                k, val_str = kwarg_raw.rsplit("=", 1)
                val_lower = val_str.lower()

                if val_lower in ("true", "false"):
                    parsed_val: str|int|float|bool|None = val_lower == "true"
                elif val_lower == "none":
                    parsed_val = None
                else:
                    try:
                        parsed_val = int(val_str, 0)
                    except ValueError:
                        try:
                            parsed_val = float(val_str)
                        except ValueError:
                            parsed_val = val_str

                kwargs[k] = parsed_val
            else:
                if name in kwargs:
                    warn(f"Found duplicate kwarg '{name}'! Overriding previous entry.")
                kwargs[name] = True

        elif arg.startswith("-"):
            for mod in arg.removeprefix("-"):
                if waiting_on_file == mod:
                    raise UnexpectedArgError(f"Expected file for mod '{waiting_on_file}', "
                                             f"found duplicate declaration.")
                if waiting_on_file is not None:
                    raise UnexpectedArgError(f"Expected file for mod '{waiting_on_file}', "
                                             f"found mod '{mod}'.")
                if mod in mods:
                    warn(f"Found duplicate mod '{mod}'! Overriding previous entry.")

                if mod in SPECIAL_MODS:
                    waiting_on_file = mod
                else:
                    mods[mod] = True

        else:
            if waiting_on_file is not None:
                mods[waiting_on_file] = arg
                waiting_on_file = None
            else:
                files.append(Path(arg))

    if waiting_on_file is not None:
        raise UnfinishedModError(f"Expected file for mod '{waiting_on_file}', "
                                 f"instead reached end of args.")

    return mods, kwargs, files

def get_pretty_tb(tb: TracebackType|None) -> list[str]:
    if tb is None:
        return []
    result = []
    current = tb
    while current is not None:
        code = current.tb_frame.f_code
        filename = Path(code.co_filename).name

        result.append(f"{current.tb_lineno} ({filename})")
        current = current.tb_next
    return result

def get_term() -> str|None:
    try:
        shell_pid = os.getppid()
        terminal_pid = subprocess.check_output(["ps", "-o", "ppid=", "-p", str(shell_pid)]).decode().strip()
        terminal_name = subprocess.check_output(["ps", "-o", "comm=", "-p", terminal_pid]).decode().strip()

        return os.path.basename(terminal_name)
    except Exception:
        return None

def main(mods: dict, kwargs: dict, files: list[Path]):
    if not mods and not kwargs and not files:
        kwargs["desktop"] = True

    if mods.get("h", None) or kwargs.get("help", None):
        info(f"svedit {colors.FG_RED_EX}v{core.VERSION} ({core.VERSION_NAME}){colors.RESET}")
        info(f"Usage: svedit [<mods>] [<kwargs>] [<files>]")
        info()
        info("MODS:")
        info(f":: {colors.FG_YELLOW_EX}-h{colors.RESET}: print this help text")
        info(f":: {colors.FG_YELLOW_EX}-d{colors.RESET}: force redownload database from DuckStation")
        info()
        info("KWARGS:")
        info(f":: {colors.FG_YELLOW_EX}--help{colors.RESET}: same as -h")
        info(f":: {colors.FG_YELLOW_EX}--force-dl{colors.RESET}: same as -d")
        info(f":: {colors.FG_YELLOW_EX}--desktop{colors.RESET}: force run svedit in desktop mode")
        info(f":: {colors.FG_YELLOW_EX}  (assumed if no mods, kwargs, or files are passed.){colors.RESET}")
        info(f":: {colors.FG_YELLOW_EX}--db-src=<url>{colors.RESET}: change where to pull the database from")
        info(f":: {colors.FG_YELLOW_EX}  (it must be a .yaml file with a similar structure!){colors.RESET}")
        info(f":: {colors.FG_YELLOW_EX}--nocheck{colors.RESET}: assume valid file, skip checking")
        info()
        info("FOR CONTRIBUTORS:")
        info(f":: {colors.FG_YELLOW_EX}--fmts{colors.RESET}: see a list of currently supported format ids")
        info(f":: {colors.FG_YELLOW_EX}--fmt-avilable=<fmt>{colors.RESET}: returns whether a format is supported or not")
        info()
        info(f"made with {colors.FG_RED_EX}❤{colors.RESET}︎ by quantum")
        info(f"svedit is {colors.FG_RED_EX}free-and-open-source software{colors.RESET},")
        info(f"  licensed under {colors.FG_YELLOW_EX}GNU GPLv3 (or later){colors.RESET}!")
        sys.exit(0)

    if kwargs.get("fmts", None):
        info("Available formats:")
        for pat, gen in cmn.mappings.items():
            contributor = cmn.contributors.get(pat, cmn.contributors.get(gen, None))
            info(f" [{pat}] => {gen}{f' (by {contributor})' if contributor is not None else ''}")
        sys.exit(0)

    checking_fmt = kwargs.get("fmt-available", None)
    if checking_fmt is not None:
        checking_fmt = str(checking_fmt).strip()
        if not checking_fmt.strip():
            warn("Expected format for --fmt-available, got empty string")
            sys.exit(1)
        for pat, gen in cmn.mappings.items():
            if re.match(pat, checking_fmt) or checking_fmt == gen:
                info(f"Format {checking_fmt} is available under '{core.FORMATS_PATH}/{gen}.xml' "
                     f"{colors.DIM}(Pattern: '{pat}'){colors.RESET}")
                if pat in cmn.contributors.keys() or gen in cmn.contributors.keys():
                    contributor = cmn.contributors.get(pat, cmn.contributors.get(gen))
                    info(f"Thank you to {contributor} for providing this format!")
                sys.exit(0)
        info(f"Format {checking_fmt} is not available under '{core.FORMATS_PATH}/'")
        sys.exit(1)

    custom_url = kwargs.get("db-src", None)
    redownload = kwargs.get("force-dl", None) or mods.get("d", None)

    if custom_url:
        if not isinstance(custom_url, str):
            err(f"Expected 'db-src' to be 'str', got '{type(custom_url).__name__}' ({custom_url})")
            sys.exit(1)

        try:
            db.get_db(True, custom_url)
        except ValueError:
            err(f"URL of unknown type '{custom_url}' passed into --db-src!")
            err("Double check your URL to ensure it is correct!")
            sys.exit(1)
        except db.IncompleteUpdateError:
            err("Download cancelled! Will retry on next launch!")
            sys.exit(1)
        except db.NoInternetError:
            err("Check your internet connection! Will retry download on next launch!")
            info("Note: If you don't want svedit to download the game database for you:")
            info(f"      1. Download {core.DATABASE_URL};")
            info(f"      2. Place the downloaded file here: {core.YAML_PATH.absolute()};")
            info(f"      3. Launch svedit again;")
            sys.exit(1)
        sys.exit(0)
    else:
        if redownload:
            if not files:
                db_url = core.DATABASE_URL.split("/")
                info(f"Fetching game database from {'/'.join(db_url[2:5])}/.../{'/'.join(db_url[-1:])}")
                try:
                    db.get_db(True)
                except db.IncompleteUpdateError:
                    err("Download cancelled! Will retry on next launch!")
                    sys.exit(1)
                except db.NoInternetError:
                    err("Check your internet connection! Will retry download on next launch!")
                    info("Note: If you don't want svedit to download the game database for you:")
                    info(f"      1. Download {core.DATABASE_URL};")
                    info(f"      2. Place the downloaded file here: {core.YAML_PATH.absolute()};")
                    info(f"      3. Launch svedit again;")
                    sys.exit(1)
                info(f"Saved raw .yaml to '{core.YAML_PATH}'")
                info(f"  and cached .pkl to '{core.PKL_PATH}'")
                sys.exit(0)
            else:
                if core.PKL_PATH.exists():
                    os.remove(core.PKL_PATH)
                if core.YAML_PATH.exists():
                    os.remove(core.YAML_PATH)

    try:
        os.get_terminal_size()
    except OSError:
        err("Could not get terminal size! Check your terminal and try again.")
        terminal = get_term()
        if terminal is not None:
            err(f"You are using '{terminal}'.")
        sys.exit(1)

    is_desktop_mode = kwargs.get("desktop", None) is not None
    opened_file = Path("~").expanduser() if not files else files[0]

    selected_block = 0
    result = None

    current_step = 2 if (is_desktop_mode and files) else (1 if is_desktop_mode else 2)
    min_step = 1 if is_desktop_mode else 2

    while True:
        try:
            if current_step == 1:
                try:
                    if opened_file.exists():
                        opened_folder = opened_file if opened_file.is_dir() else opened_file.parent
                    else:
                        opened_folder = None

                    file_path = SvEditDesktop(opened_folder).run()
                    if file_path is None:
                        sys.exit(0)
                    opened_file = file_path
                    files = [opened_file]
                    current_step = 2
                except UserExitCommand:
                    sys.exit(0)
            elif current_step == 2:
                if not kwargs.get("nocheck", None):
                    file = files[0]
                    fatal, nonfatal = cmn.is_psx_mcd(Path(file))
                    if nonfatal:
                        info(f"Your file may have non-crucial errors:")
                        for reason in nonfatal:
                            info(f"> {reason}")
                    if fatal:
                        err(f"'.../{file.name}' is not a valid 128KB PlayStation© Memory Card file!")
                        err(f"Here's what we know:")
                        for reason in fatal:
                            err(f"> {reason}")
                        if is_desktop_mode:
                            current_step = 1
                            continue
                        else:
                            sys.exit(1)

                try:
                    picker = CardPicker(file=files[0], selected_block=selected_block)
                    result = picker.run()
                except FileNotFoundError:
                    err(f"File '{files[0]}' does not exist!")
                    sys.exit(1)
                except KeyboardInterrupt:
                    sys.exit(0)
                except UserExitCommand as error:
                    delta = getattr(error, "delta", 1)
                    current_step -= delta
                    if current_step < min_step:
                        sys.exit(0)
                    continue

                if result is None:
                    current_step -= 1
                    if current_step < min_step:
                        sys.exit(0)
                    continue

                selected_block = result.block_id
                current_step = 3

            elif current_step == 3:
                try:
                    if result is None:
                        current_step -= 1
                        continue
                    viewer = MCDFileEditor(result, src_file=Path(files[0]))
                    viewer.run()
                    current_step -= 1
                except UserExitCommand as error:
                    delta = getattr(error, "delta", 1)
                    current_step -= delta
                except KeyboardInterrupt:
                    sys.exit(0)
                except cmn.UnknownFormatError:
                    current_step -= 1

                if current_step < min_step:
                    sys.exit(0)
        except KeyboardInterrupt:
            sys.exit(0)

if __name__ == "__main__":
    try:
        _mods, _kwargs, _files = parse_args(sys.argv[1:])
        main(_mods, _kwargs, _files)
    except Exception as e:
        err(f"{e.__class__.__name__} :: {e}")

        lines = get_pretty_tb(e.__traceback__)
        if lines:
            err(f"Lines: {lines[0]}")
            lines.pop(0)
            for i, line in enumerate(lines):
                err(f"     {' ' * i}-> {line}")