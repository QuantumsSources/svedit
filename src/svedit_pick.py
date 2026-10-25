import os
import time
import svedit_db as db
import svedit_core as core
import svedit_commons as cmn

from math import sin
from MCDTypes import *
from pathlib import Path
from ansicodelib import ANSIBuffer as buf, ANSICursor as cur, ANSIColors as colors

class CardPicker:
    def __init__(self, file: Path, *, selected_block: int = 0):
        self.running = False
        self.fits = False
        self.message = "Q to quit"

        try:
            self.width, self.height = os.get_terminal_size()
        except OSError:
            raise cmn.IncorrectTerminalError

        file_path = file
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError

        self.mcd_file_path = file_path
        self.mcd = MCDFile(self.mcd_file_path)

        self.game_db: dict = { }
        self.selected_block = selected_block

        self.current_col_off = 0
        self.current_frame = 0
        self.current_page = 0

    @staticmethod
    def _vwrite(text: str, x: int = 1, y: int = 1):
        for i, char in enumerate(text):
            cur.cur_goto(x, y + i)
            buf.buf_write(char)

    def render(self):
        buf.buf_clear()
        min_size = core.MIN_SIZE

        if self.width < min_size[0] or self.height < min_size[1]:
            cx = self.width // 2
            cy = self.height // 2

            bad_x = colors.FG_RED_EX if self.width < 80 else ""
            bad_y = colors.FG_RED_EX if self.height < 27 else ""
            res = colors.RESET if (bad_x or bad_x) else ""

            message = [
                colors.RESET + "Terminal too small!",
                colors.RESET + f"Resize to {colors.FG_GREEN_EX}80x27 or larger{colors.RESET}!",
                colors.RESET + f"Current size is {bad_x}{self.width}{res}x{bad_y}{self.height}{res}"
            ]

            for i, line in enumerate(message):
                cur.cur_goto(cx - cmn.visible_len(line) // 2, cy - len(message) // 2 + i)
                buf.buf_write(line)

            buf.buf_flush()
            return

        card_width = 39
        card_height = 22
        block_width = 11
        block_height = 4

        px = (self.width // 2) - (card_width // (2 if self.mcd.GetBlockDirectory(
            self.selected_block).IsUninitialized() else 1)) + 4
        py = (self.height // 2) - (card_height // 2) + 1

        card_params = cmn.BoxDrawingParams(
            x=px,
            y=py,
            width=card_width,
            height=card_height,
            title=f"[ Memory Card ]",
            title_color=colors.BOLD,
            border_color=colors.DIM,
        )
        cmn.draw_box(card_params)

        for i in range(15):
            is_selected = (i == self.selected_block)
            block = self.mcd.GetBlock(i)
            frame = self.mcd.GetBlockDirectory(i)

            if is_selected and not frame.IsUninitialized():
                cmn.draw_box(cmn.BoxDrawingParams(
                    x=px + card_width - 1,
                    y=py,
                    width=34,
                    height=5,
                    title=f"[ Data Preview {self.current_page + 1}/3 ]",
                    title_color=colors.BOLD,
                    border_color=colors.DIM
                ))
                self._vwrite("1 2", px + card_width + 32, py + 1)

                if self.current_page == 0:
                    cur.cur_goto(px + card_width + 1, py + 1)
                    g_data = db.get_db_entry(self.game_db, frame.ProductCode)
                    if g_data is not None:
                        g_name = g_data.localized_name
                        if len(g_name) > 30:
                            g_name = g_name[:30 - 3] + "..."
                        buf.buf_write(f"{colors.BOLD}{g_name}{colors.RESET}")
                        cur.cur_goto(px + card_width + 1, py + 2)
                        dev_name = g_data.developer
                        if len("by " + dev_name) > 30:
                            dev_name = dev_name[:30 - 6] + "..."
                        buf.buf_write(f"by {colors.BOLD}{dev_name}{colors.RESET}")
                        cur.cur_goto(px + card_width + 1, py + 3)
                        rel_date = g_data.release_date
                        buf.buf_write(f"released {colors.BOLD}{rel_date}{colors.RESET}")
                elif self.current_page == 1:
                    cur.cur_goto(px + card_width + 1, py + 1)
                    buf.buf_write(f"Product: {colors.BOLD}{frame.ProductCode}{colors.RESET}")
                    cur.cur_goto(px + card_width + 1, py + 2)
                    buf.buf_write(f"Region:  {colors.BOLD}{frame.Region} ({frame.RegionCode}){colors.RESET}")
                    cur.cur_goto(px + card_width + 1, py + 3)
                    buf.buf_write(f"Format:  {colors.BOLD}{frame.FormatID}{colors.RESET}")
                elif self.current_page == 2:
                    cur.cur_goto(px + card_width + 1, py + 1)
                    buf.buf_write(f"BIOS Name: ↓")
                    cur.cur_goto(px + card_width + 1, py + 2)
                    buf.buf_write(f"{colors.BOLD}{block.metadata.BIOSText}{colors.RESET}")
                    cur.cur_goto(px + card_width + 1, py + 3)
                    if block.metadata.IconCount > 1:
                        buf.buf_write(f"PSIcon Frames: {colors.BOLD}{block.metadata.IconCount}{colors.RESET}")
                    else:
                        buf.buf_write(f"{colors.DIM}PSIcon Frames: {block.metadata.IconCount}{colors.RESET}")

                cmn.draw_box(cmn.BoxDrawingParams(
                    x=px + card_width - 1,
                    y=py + 4,
                    width=34,
                    height=18,
                    title="[ Icon Preview ]",
                    title_color=colors.BOLD,
                    border_color=colors.DIM
                ))
                cur.cur_goto(px + card_width - 1, py)
                buf.buf_write(f"{colors.DIM}┬{colors.RESET}")
                cur.cur_goto(px + card_width - 1, py + 4)
                buf.buf_write(f"{colors.DIM}├{colors.RESET}")
                cur.cur_goto(px + card_width + 32, py + 4)
                buf.buf_write(f"{colors.DIM}┤{colors.RESET}")
                cur.cur_goto(px + card_width - 1, py + 21)
                buf.buf_write(f"{colors.DIM}┴{colors.RESET}")

                if block.icon_frames:
                    cur.cur_goto(px + card_width, py + card_height - 1)
                    cur_frame = self.current_frame % len(block.icon_frames) + 1
                    if len(block.icon_frames) > 1:
                        buf.buf_write(f" Frame: {cur_frame}/{len(block.icon_frames)} ")
                    block.icon_frames[self.current_frame % len(block.icon_frames)] \
                        .Draw(px + card_width, py + 5, 1, self.current_col_off)
                else:
                    message = "No image!"
                    cur.cur_goto(px + card_width, py + 12)
                    buf.buf_write(message.center(32))

            x = i % 3
            y = i // 3
            tx = (px + 2) + ((block_width + 1) * x)
            ty = (py + 1) + (block_height * y)
            rev = colors.REVERSE if is_selected else ""
            bld = colors.BOLD if is_selected else ""
            dim = colors.DIM if frame.IsUninitialized() else ""
            res = colors.RESET if (rev or dim or bld) else ""

            cmn.draw_box(cmn.BoxDrawingParams(
                x=tx,
                y=ty,
                width=block_width,
                height=block_height,
                border_color=colors.REVERSE if is_selected else colors.DIM if frame.IsUninitialized() else "",
                title_color=rev + bld,
                fill_color=rev,
                title=f"▶ 0x{(i + 1):X} ◀" if is_selected else f" Block {(i + 1):X} "
            ))

            if frame.IsDeleted():
                message = f"{rev}[Deleted]{res}"
                cur.cur_goto(tx + (block_width // 2) - (cmn.visible_len(message) // 2), ty + block_height - 1)
                buf.buf_write(message)

            if is_selected:
                if frame.IsUninitialized():
                    cur.cur_goto(tx + 1, ty + 1)
                    buf.buf_write(f"{rev}   No{res}")
                    cur.cur_goto(tx + 1, ty + 2)
                    buf.buf_write(f"{rev}  Game!{res}")
                else:
                    region = frame.RegionCode
                    p_reg, p_code = frame.ProductCode.split("-")

                    cur.cur_goto(tx + 1, ty + 1)
                    buf.buf_write(f"{rev}{dim} {region}{p_reg}-{res}")
                    cur.cur_goto(tx + 1, ty + 2)
                    buf.buf_write(f"{rev}{dim}  {p_code}{res}")
            else:
                block_start = str((0x2000 * (i + 1)).__format__("05X"))
                block_end = str((0x2000 * (i + 2) - 1).__format__("05X"))

                cur.cur_goto(tx + 1, ty + 1)
                buf.buf_write(f"{rev}{dim}  {block_start}-{res}")
                cur.cur_goto(tx + 1, ty + 2)
                buf.buf_write(f"{rev}{dim} -{block_end}{res}")

        selected_frame = self.mcd.GetBlockDirectory(self.selected_block)
        if not selected_frame.IsUninitialized():
            if selected_frame and not cmn.is_format_supported(selected_frame.FormatID):
                self.message = f"Format {selected_frame.FormatID} unsupported!"
            else:
                self.message = f"[Enter] to select block 0x{(self.selected_block + 1):X}"
        else:
            self.message = f"[q/Q]: quit  [arrows]: move"

        cur.cur_goto(px + 1, py + card_height - 1)
        width = (card_width - 2) - (cmn.visible_len(self.message) - len(self.message))
        buf.buf_write(colors.BOLD + f"[ {self.message} ]".center(width, "─").replace("─", f"{colors.DIM}─{colors.RESET}") + colors.RESET)
        buf.buf_flush()

    def update(self, key: str|None):
        self.width, self.height = os.get_terminal_size()

        current_block = self.mcd.GetBlock(self.selected_block)
        if current_block.icon_frames:
            self.current_frame = int(time.time() * 3) % len(current_block.icon_frames)
            self.current_col_off = int(sin(time.time()) * 20)

        if key in ("q", "Q"):
            raise core.UserExitCommand(delta=1)
        elif key == "\x1B":
            raise core.UserExitCommand(delta=2)
        elif key in ("RIGHT", "d", "D"):
            self.selected_block = (self.selected_block + 1) % 15
        elif key in ("LEFT", "a", "A"):
            self.selected_block = (self.selected_block - 1) % 15
        elif key in ("DOWN", "s", "S"):
            self.selected_block = (self.selected_block + 3) % 15
        elif key in ("UP", "w", "W"):
            self.selected_block = (self.selected_block - 3) % 15
        elif key == "1":
            self.current_page = (self.current_page - 1) % 3
        elif key == "2":
            self.current_page = (self.current_page + 1) % 3

    def run(self) -> MCDBlock|None:
        self.running = True
        buf.buf_enable_alt()
        buf.buf_clear()
        cur.cur_hide()

        if not core.YAML_PATH.exists() and not core.PKL_PATH.exists():
            message = f"Fetching game database... {colors.DIM}(This might take a sec...){colors.RESET}"
        elif not core.PKL_PATH.exists():
            message = f"Compiling game database... {colors.DIM}(This might take a sec...){colors.RESET}"
        else:
            message = f"Loading svedit..."
        cur.cur_goto(self.width // 2 - cmn.visible_len(message) // 2, self.height // 2)
        buf.buf_write(message)
        buf.buf_flush()

        try:
            self.game_db = db.get_db()
        except db.IncompleteUpdateError:
            buf.buf_disable_alt()
            cur.cur_show()
            core.err("Download incomplete! Will retry on next launch!")
            return None
        except db.NoInternetError:
            buf.buf_disable_alt()
            cur.cur_show()
            core.err("Check your internet connection! Will retry download on next launch!")
            core.err("Note: If you don't want svedit to download the game database for you:")
            core.err(f"      1. Download {core.DATABASE_URL};")
            core.err(f"      2. Place the downloaded file here: {core.YAML_PATH.absolute()};")
            core.err(f"      3. Launch svedit again;")
            return None

        try:
            while self.running:
                self.render()
                key = cmn.get_key()
                if key == "\r":
                    return self.mcd.GetBlock(self.selected_block)
                self.update(key)
        finally:
            buf.buf_disable_alt()
            cur.cur_show()
