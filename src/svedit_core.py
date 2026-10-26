from pathlib import Path

VERSION = "1.4.1"
VERSION_NAME = "Crocodile"
MIN_SIZE = (80, 27)

# Thanks DuckStation!
DATABASE_URL = "https://raw.githubusercontent.com/stenzek/duckstation/refs/heads/master/data/resources/gamedb.yaml"

HOME = Path.home().resolve()
CONTENT_PATH = HOME / ".svedit"
CONTENT_PATH.mkdir(exist_ok=True)
FORMATS_PATH = Path(CONTENT_PATH / "fmts")
YAML_PATH    = Path(CONTENT_PATH / "gamedb.yaml")
PKL_PATH     = Path(CONTENT_PATH / "dbcache.pkl")
CONTRIB_FILE = "CONTRIBUTE-%fmt.py"

GITHUB_REPO = "QuantumsSources/svedit"
GIT_URL = f"https://github.com/{GITHUB_REPO}.git"

def info(*s: object, sep: str = " ") -> None:
    print(f"svedit \033[0;96m(INFO)\033[0m: {sep.join(map(str, s))}")

def warn(*s: object, sep: str = " ") -> None:
    print(f"svedit \033[0;93m(WARN)\033[0m: {sep.join(map(str, s))}")

def err(*s: object, sep: str = " ") -> None:
    print(f"svedit \033[0;91m(ERROR)\033[0m: {sep.join(map(str, s))}")

class UserExitCommand(Exception):
    def __init__(self, *args: object, delta: int = 1):
        super().__init__(args)
        self.delta = delta