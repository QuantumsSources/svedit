from pathlib import Path

VERSION = "1.3.3+2α"
VERSION_NAME = "Bison"
MIN_SIZE = (80, 27)

# Thanks DuckStation!
DATABASE_URL = "https://raw.githubusercontent.com/stenzek/duckstation/refs/heads/master/data/resources/gamedb.yaml"
IS_DEBUG_SESSION = False

if IS_DEBUG_SESSION:
    PARENT_PATH  = Path("..")
else:
    PARENT_PATH  = Path(__file__).resolve().parent

FORMATS_PATH = Path(PARENT_PATH / "fmts")
YAML_PATH    = Path(PARENT_PATH / "gamedb.yaml")
PKL_PATH     = Path(PARENT_PATH / "dbcache.pkl")
CONTRIB_FILE = "CONTRIBUTE-%fmt.py"

GITHUB_REPO = "QuantumsSources/svedit"
GIT_URL = f"https://github.com/{GITHUB_REPO}.git"

def info(*s: object, sep: str = " ") -> None:
    print(f"svedit \033[0;96m(INFO)\033[0m: {sep.join(map(str, s))}")

def warn(*s: object, sep: str = " ") -> None:
    print(f"svedit \033[0;93m(WARN)\033[0m: {sep.join(map(str, s))}")

def err(*s: object, sep: str = " ") -> None:
    print(f"svedit \033[0;91m(ERROR)\033[0m: {sep.join(map(str, s))}")