import struct
import unicodedata

from pathlib import Path
from typing import TypeAlias
from ansicodelib import ANSIBuffer as buf, ANSICursor as cur, ANSIColors as col

class OutOfBoundsError(Exception):
    pass

class MCDReader:
    def __init__(self, stream: bytes | bytearray):
        self._pointer = 0
        self._stream = bytearray(stream)

    def readall(self, *, reset_pointer: bool = False) -> bytes:
        if reset_pointer:
            self.reset()
        return self._stream

    def read(self, length: int = 1, wrap: bool = False) -> bytes:
        length = max(1, length)

        if self._pointer + length > len(self._stream) and not wrap:
            raise OutOfBoundsError(f"Requested to read past stream bounds!"
                                   f"({self._pointer} + {length} > {len(self._stream)})")

        if wrap:
            result = b''
            while length > len(self._stream):
                result += self._stream[self._pointer:len(self._stream)]
                length -= len(self._stream)
                self._pointer = 0
            result = self._stream[self._pointer:self._pointer + length]
            self._pointer = (self._pointer + length) % len(self._stream)
        else:
            result = self._stream[self._pointer:self._pointer + length]
            self._pointer += length
        return bytes(result)

    def read_at(self, length: int = 1, start: int = 1, wrap: bool = False, *, return_at_end: bool = False):
        old_pc = self._pointer
        self.goto(start)
        result = self.read(length, wrap)
        if return_at_end:
            self.goto(old_pc)
        return result

    def jump(self, n: int = 1, wrap: bool = False):
        n = max(0, n)
        if wrap:
            self._pointer = (self._pointer + n) % len(self._stream)
            return
        if self._pointer + n > len(self._stream):
            raise OutOfBoundsError(f"Requested to read past stream bounds! "
                                   f"({self._pointer} + {n} > {len(self._stream)})")
        self._pointer += n

    def goto(self, goto: int, wrap: bool = False):
        if wrap:
            self._pointer = goto % len(self._stream)
            return
        if goto < 0 or goto > len(self._stream):
            raise OutOfBoundsError(f"Requested to send PC out of stream bounds! "
                                   f"({goto} not in range [0:{len(self._stream)}])")
        self._pointer = goto

    def reset(self):
        self._pointer = 0

    @property
    def pointer(self):
        return self._pointer

class MCDWriter(MCDReader):
    def __init__(self, stream: bytes | bytearray):
        super().__init__(stream=bytearray(stream))

    def write(self, input_bytes: bytes):
        self._stream[self._pointer:self._pointer+len(input_bytes)] = input_bytes
        self.jump(len(input_bytes))

    def write_at(self, i: int, input_bytes: bytes):
        self.goto(i)
        self.write(input_bytes)
        self.jump(len(input_bytes))

    def dump(self, file: Path, *, merge_at: int = 0):
        content = bytearray(open(file, "rb").read())
        content[merge_at:merge_at+len(self._stream)] = self._stream
        open(file, "wb").write(content)
        self.reset()

class MalformedFrameError(Exception):
    pass

class MalformedBlockError(Exception):
    pass

class MCDDirectoryFrame:
    VALID_STATUS_BYTES = {
        0xA0: "Uninitialized",
        0xA1: "Deleted",
        0x51: "In Use",
        0xFF: "Unused"
    }
    VALID_REGIONS = {
        b'BA': "NTSC-U",  # america
        b'BE': "PAL",  # europe
        b'BI': "NTSC-J"  # japan
    }
    WORLD_REGIONS = {
        b'BA': "North America",
        b'BE': "Europe, Australia, Asia",
        b'BI': "Japan"
    }

    def __init__(self, frame_stream: bytes, i: int):
        self._frame_id = i

        reader = MCDReader(frame_stream)
        status = int.from_bytes(reader.read())
        if status not in MCDDirectoryFrame.VALID_STATUS_BYTES:
            raise MalformedFrameError(f"Unknown status byte '0x{status:02X}' "
                                      f"found @ {128 * i + reader.pointer - 1}!")

        self._status = status
        reader.jump(9)

        if status in (0xA0, 0xFF):
            self._region = b''
            self._product_code = ""
            self._format_id = ""
            return

        self._region = reader.read(2)
        if MCDDirectoryFrame.VALID_REGIONS.get(self._region, None) is None:
            raise MalformedBlockError(f"Unknown region '{self._region}' found!")
        self._product_code = reader.read(10).decode("ascii")
        self._format_id = reader.read(8).rstrip(b'\x00').decode("ascii")

    @property
    def ID(self):
        return self._frame_id

    @property
    def Status(self):
        return self._status

    @property
    def StatusString(self):
        return MCDDirectoryFrame.VALID_STATUS_BYTES[self._status]

    @property
    def RegionCode(self) -> str:
        return self._region.decode("ascii")

    @property
    def Region(self) -> str:
        return self.VALID_REGIONS.get(self._region, "UNK")

    @property
    def RegionWorld(self) -> str:
        return self.WORLD_REGIONS.get(self._region, "World")

    @property
    def ProductCode(self):
        return self._product_code

    @property
    def FormatID(self):
        return self._format_id

    def IsDeleted(self):
        return self._status == 0xA1

    def IsUninitialized(self):
        return self._status in (0xA0, 0xFF)

    def IsUnused(self):
        return self._status == 0xFF

    def __str__(self) -> str:
        if self.Status in (0xA0, 0xFF):
            return f"MCDDirectoryFrame {self.ID} ({self.Status}: {self.StatusString})"
        return (f"MCDDirectoryFrame {self.ID} ({self.Status}: {self.StatusString}) with region "
                f"'{self.RegionCode}'|{self.ProductCode}/{self.FormatID}")


class MCDBlockMeta:
    def __init__(self, **kwargs):
        self.psicon_count: int = kwargs.get("psicon_count", 0)
        self.bios_text: bytes = kwargs.get("bios_text", b'')
        self.icon_palette: bytes = kwargs.get("palette", b'')

    @property
    def IconCount(self):
        return self.psicon_count

    @property
    def EncodedBIOSText(self):
        return self.bios_text

    @property
    def BIOSText(self):
        return unicodedata.normalize("NFKC", self.bios_text.decode("shift-jis"))

    @property
    def Palette(self):
        return self.icon_palette

PSIconColor: TypeAlias = tuple[int, int, int, int]

class MCDPSIconImage:
    def __init__(self, palette: list[PSIconColor], image: list[PSIconColor], double: bool = True):
        self.palette = palette
        self.pixels = image
        self.double = double

    def Draw(self, x: int = 1, y: int = 1, scale: float|int = 1, col_off: int = 0):
        if scale <= 0:
            return

        characters: list[str] = []
        def _get_char(s: str) -> str:
            return s + s if self.double else s

        for pixel in self.pixels:
            r, g, b, a = pixel
            if a == 0:
                characters.append(_get_char(" "))
            else:
                r = max(0, min(r + col_off, 255))
                g = max(0, min(g + col_off, 255))
                b = max(0, min(b + col_off, 255))

                color = col.get_ansi_code(r, g, b)
                characters.append(f"{color}{_get_char('█')}{col.RESET}")

        char_width = 2 if self.double else 1
        scaled_size = int(16 * scale)

        for y_off in range(scaled_size):
            src_y = min(int(y_off / scale), 15)

            for x_off in range(scaled_size):
                src_x = min(int(x_off / scale), 15)
                pixel_index = (src_y * 16) + src_x

                cur.cur_goto(x + (x_off * char_width), y + y_off)
                buf.buf_write(characters[pixel_index])

class MCDBlock:
    def __init__(self, block_stream: bytes, i: int, *, is_uninitialized: bool = False, dir_frame: MCDDirectoryFrame|None = None):
        self.block_id = i
        self.stream = block_stream
        self.directory = dir_frame
        reader = MCDReader(block_stream)

        self.icon_frames: list[MCDPSIconImage] = []
        self.data_frames: list[bytes] = []

        if is_uninitialized:
            return
        else:
            magic = reader.read(2)
            if magic != b'SC':
                raise MalformedBlockError(f"Expected first 2 bytes of non-header "
                                          f"block to be b'SC', found {magic}!")

            icon_count_flag = int.from_bytes(reader.read())
            if icon_count_flag == 0x00:
                icon_frame_count = 0
            elif icon_count_flag == 0x11:
                icon_frame_count = 1
            elif icon_count_flag == 0x12:
                icon_frame_count = 2
            elif icon_count_flag == 0x13:
                icon_frame_count = 3
            else:
                raise MalformedBlockError(f"Invalid PSIcon count flag (Expected "
                                          f"0x00, 0x11, 0x12, or 0x13, got 0x{icon_count_flag:X}")

            reader.jump()
            bios_text = reader.read(64).rstrip(b'\x00')
            reader.jump(28)
            icon_palette = reader.read(32)
            reader.reset()

            self.metadata = MCDBlockMeta(
                psicon_count=icon_frame_count,
                bios_text=bios_text,
                palette=icon_palette
            )

        for i in range(63):
            data = reader.read(0x80)
            if i <= self.metadata.IconCount:
                if i == 0: continue

                palette = []
                for i in range(16):
                    color = struct.unpack_from("<H", self.metadata.Palette, i * 2)[0]
                    r = (color & 0x001F) * 8
                    g = ((color >> 5) & 0x001F) * 8
                    b = ((color >> 10) & 0x001F) * 8
                    a = 0 if color == 0 else 255
                    palette.append((r, g, b, a))
                pixels = []
                for byte in data:
                    p1_idx = byte & 0x0F
                    p2_idx = (byte >> 4) & 0x0F
                    pixels.append(palette[p1_idx])
                    pixels.append(palette[p2_idx])

                self.icon_frames.append(MCDPSIconImage(palette, pixels))
            else:
                self.data_frames.append(data)

    @property
    def DirectoryFrame(self) -> MCDDirectoryFrame:
        return self.directory or MCDDirectoryFrame(b'\xFF' * 0x2000, self.block_id)

class MCDHeaderBlock:
    class MalformedBlockError(Exception):
        pass

    def __init__(self, block_stream: bytes):
        self.stream = block_stream

        self.frames = []
        reader = MCDReader(block_stream)

        magic = reader.read(2)
        if magic != b'MC':
            raise MalformedBlockError(f"Expected first 2 bytes of header "
                                      f"block to be b'MC', found {magic}!")
        reader.jump(126)
        for i in range(35):
            frame = MCDDirectoryFrame(reader.read(0x80), i)
            self.frames.append(frame)


class MCDFile:
    def __init__(self, file: Path):
        self._file: Path = file

        reader = MCDReader(open(file, "rb").read())
        self._header_block: MCDHeaderBlock = MCDHeaderBlock(reader.read(0x2000))
        self._blocks: list[MCDBlock] = []
        self._logical_blocks: list[MCDBlock] = []

        for i in range(len(self._header_block.frames)):
            frame: MCDDirectoryFrame = self._header_block.frames[i]
            if frame.IsUnused():
                self._logical_blocks.append(MCDBlock(b'\xFF' * 0x2000, i, is_uninitialized=True))
                continue
            block = MCDBlock(reader.read(0x2000), i, is_uninitialized=frame.IsUninitialized(), dir_frame=frame)
            self._blocks.append(block)
            self._logical_blocks.append(block)

    @property
    def File(self) -> str:
        return self._file.name

    @property
    def HeaderBlock(self) -> MCDHeaderBlock:
        return self._header_block

    @property
    def Blocks(self):
        return self._blocks

    @property
    def LogicalBlocks(self):
        """
        Similar to MCDFile.Blocks, but returns 20 extra blocks full of 0xFF bytes,
        as if uninitialized, to account for the 20 extra unused frames in the
        header block.

        This isn't super useful, but is here just in case.

        :return: A list of 15 "real", plus 20 "fake" blocks.
        """
        return self._logical_blocks

    def GetBlock(self, i: int = 0, *, allow_logical: bool = True) -> MCDBlock:
        """
        Return the 0-indexed, ith block, optionally allowing access to the
        20 extra blocks at the end. (See MCDFile.LogicalBlocks)

        :param i: The index of the block to return.
        :param allow_logical: Whether to allow access to the 20 extra blocks.
        If False, raises IndexError in case i > 15.
        :return: The ith block.
        """
        i = max(0, i)
        if allow_logical:
            if i > 35:
                raise IndexError
            return self._logical_blocks[i]
        if i > 15:
            raise IndexError
        return self._blocks[i]

    def GetBlockDirectory(self, i: int = 0) -> MCDDirectoryFrame:
        """
        Returns the MCDDirectoryFrame object associated with the ith block,
        not counting the header block.
        :param i: The ID of the block.
        :return: The block's associated MCDDirectoryFrame object.
        """
        if self._header_block is None:
            raise IndexError

        i = max(0, min(i, 15))
        frame = self._header_block.frames[i]
        return frame

    def GetBlockStatus(self, i: int = 0) -> tuple[int, str]:
        frame: MCDDirectoryFrame = self.GetBlockDirectory(i)
        return frame.Status, frame.StatusString