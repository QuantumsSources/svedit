import os
import svedit_core as core
import svedit_commons as cmn

from pathlib import Path
from ansicodelib import ANSIBuffer as buf, ANSICursor as cur, ANSIColors as colors


class SvEditDesktop:
    def __init__(self, current_path: Path | None = None):
        self.running = False
        self.width, self.height = 0, 0

        self.path = current_path if current_path and current_path.exists() else Path.home().expanduser()
        self.is_picker_open = False

        self.p_show_hidden = False
        self.p_contents = [".."]

        self.p_line = 0
        self.p_offset = 0

    def update(self, key: str | None) -> Path | None:
        self.width, self.height = os.get_terminal_size()

        contents_dirs = []
        contents_files = []
        try:
            for item in sorted(os.listdir(self.path)):
                if item.startswith(".") and not self.p_show_hidden:
                    continue
                full_path = self.path / item
                if full_path.is_dir():
                    contents_dirs.append(item)
                else:
                    contents_files.append(item)
        except PermissionError:
            pass

        self.p_contents = ([".."] if self.path != Path("/") else []) + contents_dirs + contents_files

        p_height = self.height // 2
        visible_height = max(1, p_height - 2)

        if key in ("q", "Q"):
            if self.is_picker_open:
                self.is_picker_open = False
            else:
                raise core.UserExitCommand
        elif key == "\x1B":
            raise core.UserExitCommand
        elif key == ":":
            self.is_picker_open = not self.is_picker_open
        elif key == "H":
            self.p_show_hidden = not self.p_show_hidden
            self.p_line = 0
            self.p_offset = 0
        elif self.is_picker_open:
            if key == "DOWN":
                if self.p_line < visible_height - 1 and self.p_line < len(self.p_contents) - 1:
                    self.p_line += 1
                elif self.p_offset + visible_height < len(self.p_contents):
                    self.p_offset += 1
            elif key == "UP":
                if self.p_line > 0:
                    self.p_line -= 1
                elif self.p_offset > 0:
                    self.p_offset -= 1
            elif key == "\r":
                if self.p_contents:
                    selected = self.p_contents[self.p_offset + self.p_line]
                    if selected == "..":
                        self.path = self.path.parent
                        self.p_line = 0
                        self.p_offset = 0
                    else:
                        target_path = self.path / selected
                        try:
                            if target_path.is_dir():
                                self.path = target_path
                                self.p_line = 0
                                self.p_offset = 0
                            elif len(cmn.is_psx_mcd(target_path)[0]) == 0:
                                return target_path
                        except PermissionError:
                            pass

        self.p_offset = max(0, min(self.p_offset, max(0, len(self.p_contents) - visible_height)))
        self.p_line = max(0, min(self.p_line, len(self.p_contents) - 1 - self.p_offset, visible_height - 1))
        return None

    @staticmethod
    def _get_short_path(path: Path, parents: int = 3) -> str:
        parts = path.parts
        if len(parts) - 1 <= parents:
            return str(path)

        truncated = "/".join(parts[-parents:])
        return f".../{truncated.lstrip('/')}"

    @staticmethod
    def _format_size(size_bytes: int | None) -> str:
        if size_bytes is None:
            return "-"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.0f}{unit}" if unit == 'B' else f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f}TB"

    def render(self):
        buf.buf_clear()
        min_size = core.MIN_SIZE
        if self.width < min_size[0] or self.height < min_size[1]:
            cx = self.width // 2
            cy = self.height // 2

            bad_x = colors.FG_RED_EX if self.width < 80 else ""
            bad_y = colors.FG_RED_EX if self.height < 27 else ""
            res = colors.RESET if (bad_x or bad_y) else ""

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

        cmn.draw_box(cmn.BoxDrawingParams(
            width=self.width,
            height=self.height,

            title=f"[ svedit Desktop ]",

            border_color=colors.DIM,
            title_color=colors.BOLD if not self.is_picker_open else colors.DIM
        ))

        cx, cy = self.width // 2, self.height // 2
        message = [
            "                                     .o8   o8o      .   ",
            "                                    \"888   `\"'    .o8   ",
            " .oooo.o oooo    ooo  .ooooo.   .oooo888  oooo  .o888oo ",
            "d88(  \"8  `88.  .8'  d88' `88b d88' `888  `888    888   ",
            "`\"Y88b.    `88..8'   888ooo888 888   888   888    888   ",
            "o.  )88b    `888'    888    .o 888   888   888    888 . ",
            "8\"\"888P'     `8'     `Y8bod8P' `Y8bod88P\" o888o   \"888\" ",
            "",
            f"Welcome to svedit, the global PlayStation© save editor,",
            f"currently serving {len(cmn.mappings)} formats!",
            "",
            "Press : to open file picker.",
            "",
            f"{colors.DIM}You are currently running svedit v{core.VERSION} ({core.VERSION_NAME}){colors.RESET}"
        ]

        for i, line in enumerate(message):
            cur.cur_goto(cx - (cmn.visible_len(line) // 2), cy - len(message) // 2 + i)
            if self.is_picker_open:
                line = f"{colors.DIM}{line}{colors.RESET}"
            buf.buf_write(line)

        if self.is_picker_open:
            p_width = max(self.width // 2, 63)
            p_height = self.height // 2

            px, py = cx - p_width // 2, cy

            cmn.draw_box(cmn.BoxDrawingParams(
                x=px,
                y=py,

                width=p_width,
                height=p_height,

                title=f"[ File Picker: {self._get_short_path(self.path)} ]",
                title_color=colors.BOLD,
                border_color=colors.DIM
            ))

            visible_height = p_height - 2
            max_items = min(visible_height, len(self.p_contents))

            for i in range(max_items):
                cur.cur_goto(px + 1, py + 1 + i)
                item_idx = self.p_offset + i
                if item_idx >= len(self.p_contents):
                    break

                file_name = self.p_contents[item_idx]
                full_path = self.path / file_name if file_name != ".." else self.path.parent

                try:
                    if file_name == "..":
                        file_size = "DIR"
                    elif full_path.is_dir():
                        file_size = "DIR"
                    else:
                        file_size = self._format_size(full_path.stat().st_size)
                except (FileNotFoundError, PermissionError):
                    file_size = "???"

                size_col_width = 8
                name_col_width = p_width - size_col_width - 8

                if len(file_name) > name_col_width:
                    display_name = file_name[:name_col_width - 3] + "..."
                else:
                    display_name = file_name.ljust(name_col_width)

                try:
                    if full_path.is_dir() or full_path.stat().st_size != 0x20000:
                        is_valid_mcd = False
                    else:
                        is_valid_mcd = len(cmn.is_psx_mcd(full_path)[0]) == 0
                except (FileNotFoundError, PermissionError):
                    is_valid_mcd = False

                if not full_path.is_dir() and not is_valid_mcd:
                    dim = colors.DIM if i != self.p_line else ''
                    display_name = f"{dim}{display_name}{colors.RESET_BOLD_DIM}"

                line = f" {display_name} │ {file_size.rjust(size_col_width)} "
                padded = line.ljust(p_width - 4)

                if i == self.p_line:
                    buf.buf_write(f"{colors.REVERSE}>{padded}{colors.RESET}")
                else:
                    buf.buf_write(f" {padded}")

            cur.cur_goto(px + 1, py + p_height - 1)
            buf.buf_write(f" [H] to {'hide' if self.p_show_hidden else 'show'} hidden files ")

            cur.cur_goto(2, self.height)
            buf.buf_write(" [q] to close picker | [Enter] to open ")
        else:
            cur.cur_goto(2, self.height)
            buf.buf_write(" [q] to exit ")

        buf.buf_flush()

    def run(self) -> Path | None:
        self.running = True
        buf.buf_enable_alt()
        buf.buf_clear()
        cur.cur_hide()

        try:
            while self.running:
                key = cmn.get_key()
                result = self.update(key)
                if result is not None:
                    return result
                self.render()
        except core.UserExitCommand:
            return None
        finally:
            buf.buf_disable_alt()
            cur.cur_show()