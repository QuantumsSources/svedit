import os
import re
import sys
import tty
import select
import termios
import svedit_core as core

from pathlib import Path
from xml.etree import ElementTree
from ansicodelib import ANSIBuffer as buf, ANSICursor as cur, ANSIColors as colors

class IncorrectTerminalError(Exception):
    pass

ANSI_KEY_MAP = {
    "\x1B[A": "UP",
    "\x1B[B": "DOWN",
    "\x1B[C": "RIGHT",
    "\x1B[D": "LEFT",
    "\x1B[1;2A": "SHIFT_UP",
    "\x1B[1;2B": "SHIFT_DOWN",
    "\x1B[1;2C": "SHIFT_RIGHT",
    "\x1B[1;2D": "SHIFT_LEFT",
}

def get_key(timeout: float = 0.05) -> str|None:
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        raise IncorrectTerminalError()

    try:
        tty.setraw(fd)
        r, _, _ = select.select([fd], [], [], timeout)
        if not r or not (ch_bytes := os.read(fd, 1)):
            return None

        ch = ch_bytes.decode("utf-8")
        if ch != "\x1b":
            return ch

        seq = ch
        while True:
            r_seq, _, _ = select.select([fd], [], [], 0.05)
            if not r_seq:
                break
            seq += os.read(fd, 1).decode("utf-8")
            if seq in ANSI_KEY_MAP:
                return ANSI_KEY_MAP[seq]
            if len(seq) > 6:
                break

        return ANSI_KEY_MAP.get(seq, ch)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, old)

class UnknownFormatError(Exception):
    pass

mappings: dict[str, str] = { }
contributors: dict[str, str] = { }
for file in os.listdir(core.FORMATS_PATH):
    file = Path(core.FORMATS_PATH / file)
    if file.is_file() and file.suffix == ".xml":
        root = ElementTree.parse(file).getroot()
        pattern = root.attrib.get("pattern", None)
        generic = root.attrib.get("generic", None)

        if pattern is not None and generic is not None:
            mappings[pattern] = generic
            contributor = root.attrib.get("contributor", None)
            if contributor is not None:
                contributors[generic] = contributor

def get_mapped_format(fmt: str) -> str:
    if not fmt:
        return ""
    for k, v in mappings.items():
        if re.match(k, fmt):
            return v
    return fmt

def is_format_supported(fmt: str) -> bool:
    fmt = get_mapped_format(fmt)
    fmt_path = Path(core.FORMATS_PATH / (fmt + ".xml"))
    return fmt_path.exists() and fmt_path.is_file()

def get_format_file(fmt: str) -> Path|None:
    mapped_fmt = get_mapped_format(fmt)
    if not is_format_supported(mapped_fmt):
        matched = f"(matched to {mapped_fmt}) " if fmt != mapped_fmt else ""
        raise UnknownFormatError(f"File format {fmt} {matched}is not recognized!")
    return Path(core.FORMATS_PATH / (get_mapped_format(mapped_fmt) + ".xml"))

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def visible_len(s: str) -> int:
    return len(ANSI_ESCAPE.sub('', s))

class BoxDrawingParams:
    def __init__(self, **kwargs):
        self.x: int = kwargs.get("x", 1)
        self.y: int = kwargs.get("y", 1)
        self.width: int = kwargs.get("width", 2)
        self.height: int = kwargs.get("height", 2)
        self.title: str = kwargs.get("title", "")
        self.border_color: str = kwargs.get("border_color", "")
        self.fill_color: str = kwargs.get("fill_color", "")
        self.title_color: str = kwargs.get("title_color", "")

def draw_box(params: BoxDrawingParams):
    if params.width < 2 or params.height < 2:
        return

    fc = getattr(params, "fill_color", "")
    bc = getattr(params, "border_color", "")
    tc = getattr(params, "title_color", "")
    reset = colors.RESET if (bc or tc or fc) else ""

    title_text = getattr(params, "title", "")
    raw_title = ANSI_ESCAPE.sub("", title_text)

    inner_w = params.width - 2

    for i in range(params.height):
        cur.cur_goto(params.x, params.y + i)
        if i == 0:
            if title_text:
                if len(raw_title) > inner_w:
                    raw_title = raw_title[:max(0, inner_w - 3)] + "..."
                    title_fmt = f"{tc}{raw_title}{reset}"
                    t_vis_len = len(raw_title)
                else:
                    title_fmt = f"{tc}{title_text}{reset}" if tc else title_text
                    t_vis_len = visible_len(title_text)

                left_pad = (inner_w - t_vis_len) // 2
                right_pad = inner_w - t_vis_len - left_pad
                top_str = f"{bc}┌{'─' * left_pad}{reset}{title_fmt}{bc}{'─' * right_pad}┐{reset}"
            else:
                top_str = f"{bc}┌{'─' * inner_w}┐{reset}"
            buf.buf_write(top_str)
        elif i == params.height - 1:
            buf.buf_write(f"{bc}└{'─' * inner_w}┘{reset}")
        else:
            buf.buf_write(f"{bc}│{reset}{fc}{' ' * inner_w}{reset}{bc}│{reset}")

def xor_check(data: bytes) -> int:
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum

def is_psx_mcd(path: Path) -> tuple[list[str], list[str]]:
    fatal = []
    nonfatal = []

    try:
        open(path, "rb").close()
    except FileNotFoundError:
        fatal.append(f"file {path} does not exist")
        return fatal, nonfatal

    if path.suffix not in (".mcd", ".psv", ".vm1"):
        nonfatal.append(f"file extension does not match recognized extensions")

    with open(path, "rb") as f:
        content = f.read()
        size_match = len(content) == 0x20000
        if not size_match:
            fatal.append(f"target size mismatch (0x{len(content):X} vs 0x20000)")
            return fatal, nonfatal
        magic_match = content.startswith(b'MC')
        if not magic_match:
            fatal.append(f"magic bytes mismatch ({content[0:2]} vs b'MC')")
        xor_match = xor_check(content[0:0x7E]) == content[0x7F]
        if not xor_match:
            fatal.append(f"xor check mismatch   (0x{content[0x7F]:X} "
                          f"vs 0x{xor_check(content[0:0x7E]):X})")
    return fatal, nonfatal

CONTRIBUTE_PY_TEMPLATE = """\
\"""
CONTRIBUTE-%fmt.py

For transparency, running this file will:
1. Check for and prompt to delete old clone results;
2. Fork & clone svedit's GitHub repository;
3. Move results to "~/svedit_dev"
4. Open %fmt.xml in your editor, if it exists;
5. Else, create it in ./fmts/%fmt.xml;
6. Create COMMIT.py for submitting your update;
\"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

try:
    print(f"> setting up contribution workspace for %fmt...")
    if shutil.which("git") is None:
        print("error: git not found.")
        print("       install from pacman, apt, etc...")
        sys.exit(1)

    if shutil.which("gh") is None:
        print("error: github cli not found.")
        print("       install from pacman, apt, etc...")
        sys.exit(1)

    if subprocess.run(["gh", "auth", "status"], stderr=subprocess.DEVNULL).returncode != 0:
        print("warn: you must be signed into the github cli")
        try:
            if subprocess.run(["gh", "auth", "login"], stderr=subprocess.STDOUT).returncode != 0:
                print("error: failed to authenticate. try again.")
                sys.exit(1)
        except KeyboardInterrupt:
            print("error: login canceled!")
            sys.exit(1)

    if Path("svedit").exists():
        if input("> found old clone directory. remove? [Y/n] ").lower().strip() in ("y", "yes", ""):
            print("> removed old clone directory")
            shutil.rmtree(Path("svedit"))
        else:
            print("warn: remove ./svedit before proceeding")
            sys.exit(1)

    try:
        print("> forking and cloning '%repo'")
        subprocess.run(["gh", "repo", "fork", "%repo", "--clone"], check=True)
    except subprocess.CalledProcessError:
        print("error: error during forking/cloning. do you already have a fork or directory named 'svedit'?")
        sys.exit(1)
    except KeyboardInterrupt:
        print("error: fork and/or clone interrupted!")
        print("       check for leftover files!")
        sys.exit(1)
except KeyboardInterrupt:
    print("warn: setup interrupted!")
    sys.exit(1)

TARGET_PATH = Path.home() / "svedit_dev"
if TARGET_PATH.exists():
    shutil.rmtree(TARGET_PATH)
shutil.copytree("svedit", TARGET_PATH)
print(f"> moved cloned fork to '{TARGET_PATH}'")

if input("> remove original clone location? [Y/n] ").lower().strip() in ("y", "yes", ""):
    print("> removed old clone directory")
    shutil.rmtree(Path("svedit"))
os.chdir(TARGET_PATH)

branch_name = f"format/{"%fmt".lower()}-update"
subprocess.run(["git", "checkout", "-b", branch_name], check=True)
print(f"> created new branch '{branch_name}'")

xml_path = Path(f"fmts/%fmt.xml")
if not xml_path.exists():
    print(f"warn: could not find {xml_path}. creating template file.")

    root = ElementTree.Element("svedit", {
        "pattern": "", "generic": "", "contributor": ""
    })
    root.append(ElementTree.Comment("Make sure to read XML_DOCS.md before editing!"))
    
    file_node = ElementTree.SubElement(root, "file", {"unfinished": "true"})
    file_node.append(ElementTree.Comment("Add the file structure for %fmt here!"))

    tree = ElementTree.ElementTree(root)
    ElementTree.indent(tree, "    ")
    tree.write(xml_path)

COMMIT_PY = \"""\\
%commit_py\""".replace("%branch", branch_name)

open("COMMIT.py", "w").write(COMMIT_PY)
print("> created COMMIT.py")

if input(f"\\n> open {xml_path} in your default editor? [Y/n] ").lower().strip() in ("y", "yes", ""):
    if os.environ.get("EDITOR", None) is None:
        print("warn: $EDITOR environment variable is not set.")
        editor = input("> what editor do you want to use? [cmd] ")
        if not editor:
            print("warn: no editor input! defaulting to 'nano'")
            editor = "nano"
        elif shutil.which(editor) is None:
            print(f"warn: editor '{editor}' not found! defaulting to 'nano'")
            editor = "nano"
    else:
        editor = os.environ.get("EDITOR", "nano")

    print(f"> opening {xml_path} in {editor}...")
    subprocess.run([editor, str(xml_path)])

print("\\n> set up complete! make your edits, save, and run 'python COMMIT.py' when you're ready.")
print("> if you'd rather not build svedit, and run straight from python...")
print("  ...set 'IS_DEBUG_SESSION' to True in ./src/svedit_core.py")"""

COMMIT_PY = """\
\\\"""
COMMIT.py

For transparency, running this file will:
1. Commit your changed format file to the new branch;
2. Start a pull request to the main repository;
\\\"""

import shutil
import subprocess

if shutil.which("git") is None:
    print("error: git not found.")
    print("       install from pacman, apt, etc...")
    sys.exit(1)

if shutil.which("gh") is None:
    print("error: github cli not found.")
    print("       install from pacman, apt, etc...")
    sys.exit(1)

if subprocess.run(["gh", "auth", "status"], stderr=subprocess.DEVNULL).returncode != 0:
    print("warn: you must be signed into the github cli")
    try:
        if subprocess.run(["gh", "auth", "login"], stderr=subprocess.STDOUT).returncode != 0:
            print("error: failed to authenticate. try again.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("error: login canceled!")
        sys.exit(1)

print(f"> pushing changes to format '%fmt'...")
subprocess.run(["git", "add", "."])
subprocess.run(["git", "commit", "-m", '"update %fmt.xml"'])
subprocess.run(["git", "push", "-u", "origin", "%branch"])
subprocess.run(["gh", "pr", "create", "--fill"])

target = Path.home() / "svedit_dev"
if target.exists() and target.is_dir():
    if input(f"> remove local clone at '{target}'? [y/N] ").lower().strip() in ("y", "yes"):
        print("> removed local clone")
        shutil.rmtree(target)"""

def generate_contribute_sh(mapped_fmt: str):
    file_content = (
        CONTRIBUTE_PY_TEMPLATE
        .replace("%commit_py", COMMIT_PY)
        .replace("%fmt", mapped_fmt)
        .replace("%repo", core.GITHUB_REPO)
    )
    with open(core.PARENT_PATH / core.CONTRIB_FILE.replace("%fmt", mapped_fmt), "w") as f:
        f.write(file_content)