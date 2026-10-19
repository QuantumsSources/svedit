import os
import signal
import struct
import svedit_db as db
import svedit_core as core
import svedit_commons as cmn

from pathlib import Path
from typing import Any, TypeAlias
from xml.etree import ElementTree
from MCDTypes import MCDBlock, MCDReader, MCDWriter
from ansicodelib import ANSIBuffer as buf, ANSICursor as cur, ANSIColors as colors

class MalformedFormatFile(Exception):
    pass

class MCDNodeData:
    def __init__(self, e: ElementTree.Element):
        self.e = e
        self.type = e.tag

        name = e.attrib.get("name")
        if not name and not e.tag == "blank":
            raise MalformedFormatFile(f"Found file node of type {self.type} without 'name' attribute")

        self.name = name or "blank"
        self.display = e.attrib.get("display", self.name)
        self.children = []

        length_attr = e.attrib.get("length", None)
        if self.type == "bool":
            self.length = 1
        elif length_attr is not None:
            try:
                self.length = int(length_attr, 0)
            except ValueError:
                raise MalformedFormatFile(f"Invalid 'length' value '{length_attr}' in node '{self.name or self.type}'")
        elif self.type not in ("dict", "list", "struct"):
            raise MalformedFormatFile(f"Found file node of type '{self.type}' without 'length' attribute")
        else:
            self.length = 0
            for child in e:
                self.children.append(MCDNodeData(child))

class MCDEnumItem:
    def __init__(self, name: str, value: int, display: str = ""):
        self.name = name
        self.value = value
        self.display = display if display else self.name

    def __str__(self) -> str:
        display = f" ({self.display})" if self.display != self.name else ""
        return f"EnumItem {self.name}{display}: {self.value}"

    def __repr__(self) -> str:
        return f"MCDEnumItem(name='{self.name}', value={self.value}, display={self.display})"

class InvalidEnumItemError(Exception):
    pass

class MCDEnum:
    def __init__(self, name: str, items: list[MCDEnumItem], *, values: list[int]|None = None):
        self.name = name
        if values is not None:
            for item in items:
                if item.value not in values:
                    type_name = type(item.value).__name__
                    raise InvalidEnumItemError(f"Value {type_name} not in valid values for enum {name}!")
        self.items = items

    def GetEnumItem(self, name: str) -> MCDEnumItem|None:
        for item in self.items:
            if item.name == name:
                return item
        return None

    def GetEnumItemFromValue(self, value: int) -> MCDEnumItem|None:
        for item in self.items:
            if item.value == value:
                return item
        return None

    def __contains__(self, item: int) -> bool:
        for valid in self.items:
            if item == valid.value:
                return True
        return False

class MCDStruct:
    def __init__(self, name: str, nodes: list[MCDNodeData], *, struct_type: str = "list"):
        self.id = name
        self.nodes = nodes
        self.display = struct_type

class MCDSaveFilePath:
    def __init__(self, a: str|int|list[str|int]|tuple[str|int]|MCDSaveFilePath):
        if isinstance(a, MCDSaveFilePath):
            self.parts = list[str](a.parts)
        elif isinstance(a, str):
            self.parts = a.split(".")
        elif isinstance(a, (tuple, list)):
            self.parts = [str(part) for part in a]
        elif isinstance(a, int):
            self.parts = [str(a)]
        else:
            raise TypeError(f"Unsupported type for MCDSaveFilePath: {type(a).__name__}")

    def __len__(self):
        return len(self.parts)

    def __getitem__(self, item):
        return self.parts[item]

    def __iter__(self):
        return iter(self.parts)

    def __truediv__(self, other) -> MCDSaveFilePath:
        new_parts = list(self.parts)

        if isinstance(other, MCDSaveFilePath):
            new_parts.extend(other.parts)
        elif isinstance(other, (tuple, list)):
            new_parts.extend(str(p) for p in other)
        elif isinstance(other, str):
            new_parts.extend(other.split("."))
        elif isinstance(other, int):
            new_parts.extend(str(other))
        else:
            new_parts.append(str(other))

        return MCDSaveFilePath(new_parts)

    def __eq__(self, other) -> bool:
        if isinstance(other, MCDSaveFilePath):
            return self.parts == other.parts
        return False

    def __hash__(self) -> int:
        return hash(tuple(self.parts))

    def __str__(self) -> str:
        display_path = ""
        for part in self.parts:
            if part.isdigit():
                display_path += f"[{part}]"
            elif " " in part:
                display_path += f"['{part}']"
            else:
                display_path += f".{part}"
        return display_path.lstrip(".")

    def __repr__(self) -> str:
        return f"MCDSaveFilePath(a={'.'.join(self.parts)})"

ValidSaveFilePath: TypeAlias = str|list[str]|tuple[str]|MCDSaveFilePath

class MCDSaveFile:
    def _get_value_from_element(self, e: ElementTree.Element, *, value: Any = None, r: MCDReader|None = None) -> Any:
        if e.tag == "blank":
            if r is not None:
                r.jump(MCDNodeData(e).length)
            return None

        if value is not None:
            target = value
        elif r is not None and e.tag not in ("dict", "list", "struct"):
            target = r.read(MCDNodeData(e).length)
        else:
            target = e.text

        if e.tag == "int":
            if isinstance(target, bytes):
                order = "little" if e.attrib.get("order", "big").lower() == "little" else "big"
                signed = e.attrib.get("signed", "false").lower() == "true"
                return int.from_bytes(target, order, signed=signed)
            if isinstance(target, str):
                return int(target, 0)
            return int(target or 0)
        elif e.tag == "str":
            if isinstance(target, bytes):
                encoding = e.attrib.get("encoding", "ascii")
                return target.decode(encoding).replace("\x00", " ")
            return target if target is not None else ""
        elif e.tag == "bool":
            if isinstance(target, bytes):
                return bool(int.from_bytes(target))
            if isinstance(target, str):
                return target.strip().lower() in ("true", "1", "yes")
            return bool(target) if target is not None else False
        elif e.tag == "float":
            if isinstance(target, bytes):
                order = "<" if e.attrib.get("order", "big").lower() == "little" else ">"
                fmt = f"{order}f" if len(target) == 4 else f"{order}d"
                return struct.unpack(fmt, target)[0]
            return float(target) if target is not None else 0.0
        elif e.tag == "dict":
            _dict = {}
            for node in e:
                node_data = MCDNodeData(node)
                if node_data.type == "blank":
                    if r is not None:
                        r.jump(node_data.length)
                    continue
                key = node_data.name if node_data.name is not None else node.tag
                _dict[key] = self._get_value_from_element(node, r=r)
            return _dict
        elif e.tag == "list":
            _list = []
            for node in e:
                node_data = MCDNodeData(node)
                if node_data.type == "blank":
                    if r is not None:
                        r.jump(node_data.length)
                    continue
                _list.append(self._get_value_from_element(node, r=r))
            return _list
        elif e.tag == "enum":
            enum_id = e.attrib.get("id", None)
            order = "little" if e.attrib.get("order", "big").lower() == "little" else "big"

            if enum_id is None:
                return None
            enum_def = self._enums.get(enum_id, None)
            if enum_def is None:
                return None
            if not isinstance(target, bytes):
                return None
            value = int.from_bytes(target, order)
            return enum_def.GetEnumItemFromValue(value)
        elif e.tag == "struct":
            struct_id = e.attrib.get("id", None)
            if struct_id is None:
                return None
            struct_def = self._structs.get(struct_id, None)
            if struct_def is None:
                return None

            if struct_def.display == "list":
                _struct = []
                for node_data in struct_def.nodes:
                    if node_data.type == "blank":
                        if r is not None:
                            r.jump(node_data.length)
                        continue
                    _struct.append(self._get_value_from_element(node_data.e, r=r))
                return _struct
            elif struct_def.display == "dict":
                _struct = {}
                for node_data in struct_def.nodes:
                    if node_data.type == "blank":
                        if r is not None:
                            r.jump(node_data.length)
                        continue
                    _struct[node_data.name] = self._get_value_from_element(node_data.e, r=r)
                return _struct

        return target if target is not None else ""

    def __init__(self, root: ElementTree.Element, data_block: MCDBlock, src_file: Path):
        if root.tag != "svedit":
            raise MalformedFormatFile(f"Expected root tag to be 'svedit', got '{root.tag}'!")

        self._src_file = src_file
        self._enums: dict[str, MCDEnum] = {}
        self._structs: dict[str, MCDStruct] = {}
        self._stream = data_block.stream

        reader = MCDReader(self._stream)
        reader.jump(0x100)

        _file = root.find("file")
        if _file is None:
            raise MalformedFormatFile("Format file should have a 'file' node. None found.")

        for enum_node in root.findall("enumdef"):
            enum_id = enum_node.attrib.get("id", None)
            if enum_id is None:
                raise MalformedFormatFile("Found nameless enum definition")
            enum_values: dict[str, tuple[int, str]] = {}
            for enum_item in enum_node:
                item_name = enum_item.attrib.get("name", None)
                if item_name is None:
                    raise MalformedFormatFile(f"Found nameless enum item definition for enum {enum_id}")
                item_value = self._get_value_from_element(enum_item)
                if item_value is None:
                    raise MalformedFormatFile(f"Found valueless enum item definition for enum {enum_id}")
                if not isinstance(item_value, int):
                    raise MalformedFormatFile(f"Found enum item definition for enum {enum_id} with non-int value")
                item_display = enum_item.attrib.get("display", "")
                enum_values[item_name] = (item_value, item_display)
            self._enums[enum_id] = MCDEnum(enum_id, [
                MCDEnumItem(name, value, display) for name, (value, display) in enum_values.items()
            ], values=[
                value for (value, _) in enum_values.values()
            ])

        for struct_node in root.findall("structdef"):
            struct_id = struct_node.attrib.get("id", None)
            if struct_id is None:
                raise MalformedFormatFile("Found nameless struct definition")
            struct_type = struct_node.attrib.get("type", "list")
            struct_values: list[MCDNodeData] = []
            for struct_item in struct_node:
                struct_values.append(MCDNodeData(struct_item))
            self._structs[struct_id] = MCDStruct(struct_id, struct_values, struct_type=struct_type)

        _result: dict[str, Any] = {}
        for node in _file:
            node_data = MCDNodeData(node)
            if node_data.type == "blank":
                reader.jump(node_data.length)
                continue
            node_value = self._get_value_from_element(node, r=reader)
            if node_data.name:
                _result[node_data.name] = node_value

        self._root = _file
        self._content = _result

        self.svedit_root = root
        self.changes: dict[MCDSaveFilePath, Any] = { }
        self.block = data_block

    def _get_content_value(self, path: MCDSaveFilePath) -> Any:
        current = self._content
        for a in path:
            if isinstance(current, dict):
                current = current.get(a)
            elif isinstance(current, list):
                current = current[int(a)]
        return current

    def _serialize_element(self, e: ElementTree.Element, path: MCDSaveFilePath, writer: MCDWriter):
        node_data = MCDNodeData(e)

        if e.tag == "blank":
            writer.write(b'\x00' * node_data.length)
            return

        val = self.GetFileEntryValue(path)

        packed_bytes = b''
        length = node_data.length

        if e.tag == "int":
            order = "little" if e.attrib.get("order", "big").lower() == "little" else "big"
            signed = e.attrib.get("signed", "false").lower() == "true"
            int_val = int(val.value) if isinstance(val, MCDEnumItem) else int(val or 0)
            packed_bytes = int_val.to_bytes(length, order, signed=signed)
        elif e.tag == "str":
            encoding = e.attrib.get("encoding", "ascii")
            str_val = str(val or "")
            packed_bytes = str_val.encode(encoding)
        elif e.tag == "bool":
            order = "little" if e.attrib.get("order", "big").lower() == "little" else "big"
            if isinstance(val, str):
                bool_val = val.strip().lower() in ("true", "1", "yes")
            else:
                bool_val = bool(val)
            packed_bytes = int(bool_val).to_bytes(length, order)
        elif e.tag == "float":
            order = "<" if e.attrib.get("order", "big").lower() == "little" else ">"
            fmt = f"{order}f" if length == 4 else f"{order}d"
            packed_bytes = struct.pack(fmt, float(val or 0.0))
        elif e.tag == "enum":
            order = "little" if e.attrib.get("order", "big").lower() == "little" else "big"
            enum_id = e.attrib.get("id")
            if isinstance(val, MCDEnumItem):
                enum_val = val.value
            elif enum_id and enum_id in self._enums:
                enum_def = self._enums[enum_id]
                item = enum_def.GetEnumItem(str(val))
                if item is None:
                    try:
                        int_val = int(val, 0) if isinstance(val, str) else int(val)
                        item = enum_def.GetEnumItemFromValue(int_val)
                    except (ValueError, TypeError):
                        pass
                enum_val = item.value if item else 0
            else:
                try:
                    enum_val = int(val, 0) if isinstance(val, str) else int(val or 0)
                except (ValueError, TypeError):
                    enum_val = 0
            packed_bytes = enum_val.to_bytes(length, order)
        elif e.tag == "list":
            idx = 0
            for child in e:
                child_data = MCDNodeData(child)
                if child_data.type == "blank":
                    writer.jump(child_data.length)
                    continue
                self._serialize_element(child, path / idx, writer)
                idx += 1
            return
        elif e.tag == "dict":
            for child in e:
                child_data = MCDNodeData(child)
                if child_data.type == "blank":
                    writer.jump(child_data.length)
                    continue
                key = child_data.name if child_data.name is not None else child.tag
                self._serialize_element(child, path / key, writer)
            return
        elif e.tag == "struct":
            struct_id = e.attrib.get("id")
            if not struct_id or struct_id not in self._structs:
                return
            struct_def = self._structs[struct_id]
            if struct_def.display == "list":
                idx = 0
                for node_data in struct_def.nodes:
                    if node_data.type == "blank":
                        writer.jump(node_data.length)
                        continue
                    self._serialize_element(node_data.e, path / idx, writer)
                    idx += 1
            elif struct_def.display == "dict":
                for node_data in struct_def.nodes:
                    if node_data.type == "blank":
                        writer.jump(node_data.length)
                        continue
                    key = node_data.name if node_data.name is not None else node_data.e.tag
                    self._serialize_element(node_data.e, path / key, writer)
            return

        if packed_bytes:
            writer.write(packed_bytes)

    def _find_from_name(self, e: ElementTree.Element, name: str) -> ElementTree.Element|None:
        if not name:
            return None

        if e.tag == "list":
            try:
                target_idx = int(name, 0)
            except ValueError:
                return None
            non_blank_idx = 0
            for node in e:
                if MCDNodeData(node).type == "blank":
                    continue
                if non_blank_idx == target_idx:
                    return node
                non_blank_idx += 1
            return None
        elif e.tag == "struct":
            struct_id = e.attrib.get("id")
            if not struct_id or struct_id not in self._structs:
                return None
            struct_def = self._structs[struct_id]
            if struct_def.display == "list":
                try:
                    target_idx = int(name, 0)
                except ValueError:
                    return None
                non_blank_idx = 0
                for node_data in struct_def.nodes:
                    if node_data.type == "blank":
                        continue
                    if non_blank_idx == target_idx:
                        return node_data.e
                    non_blank_idx += 1
                return None
            else:
                for node_data in struct_def.nodes:
                    if node_data.type == "blank":
                        continue
                    node_name = node_data.name if node_data.name != "blank" else node_data.e.tag
                    if node_data.name == name or node_name == name:
                        return node_data.e
                return None
        else:
            for node in e:
                if node.attrib.get("name", "") == name:
                    return node
        return None

    def _get_node_from_path(self, path: MCDSaveFilePath) -> ElementTree.Element:
        current = self._root

        for i, a in enumerate(path):
            nxt = self._find_from_name(current, a)
            if nxt is not None:
                current = nxt
            else:
                raise KeyError(f"Entry \'{'.'.join(map(str, path[0:i + 1]))}\' does not "
                               f"contain key '{path[i]}'")
        return current

    def _get_from_path(self, path: MCDSaveFilePath) -> Any:
        current = self._content
        for a in path:
            if isinstance(current, dict):
                current = current.get(a)
            elif isinstance(current, list):
                try:
                    a = int(a, 0)
                except TypeError:
                    raise TypeError(f"Expected numerical index for 'list', got '{a}'")
                current = current[a]
            else:
                raise TypeError(f"Found non-iterable type '{type(current).__name__}' in the middle of path.")
        return current

    def GetFileEntryName(self, path: ValidSaveFilePath, *, get_formal_name: bool = False) -> str:
        path = MCDSaveFilePath(path)
        node = self._get_node_from_path(path)

        attrib = node.attrib
        if get_formal_name:
            result = attrib.get("name", node.tag or "UNKNOWN")
        else:
            result = attrib.get("display", attrib.get("name", node.tag or "UNKNOWN"))

        return result

    def IsEntryUnused(self, path: ValidSaveFilePath) -> bool:
        path = MCDSaveFilePath(path)
        current = self._root

        for i, a in enumerate(path):
            nxt = self._find_from_name(current, a)
            if nxt is not None:
                current = nxt
                attrib = current.attrib
                if attrib.get("unused", "").lower() == "true":
                    return True
            else:
                raise KeyError(f"Entry \'{'.'.join(map(str, path[0:i + 1]))}\' does not "
                               f"contain key '{path[i]}'")
        return False

    @property
    def RawContent(self):
        return self._content

    @property
    def Unfinished(self):
        return self._root.attrib.get("unfinished").lower() in ("true", "1")

    def GetFileEntry(self, path: ValidSaveFilePath) -> ElementTree.Element:
        path = MCDSaveFilePath(path)
        return self._get_node_from_path(path)

    def GetFileEntryOriginalValue(self, path: ValidSaveFilePath) -> Any:
        path = MCDSaveFilePath(path)
        return self._get_from_path(path)

    def GetFileEntryValue(self, path: ValidSaveFilePath) -> Any:
        path = MCDSaveFilePath(path)
        if path in self.changes:
            return self.changes.get(path)
        return self.GetFileEntryOriginalValue(path)

    def GetFileEntryByteLength(self, path: ValidSaveFilePath) -> int:
        path = MCDSaveFilePath(path)
        node = self._get_node_from_path(path)
        return MCDNodeData(node).length

    def GetInputMaxLength(self, path: ValidSaveFilePath) -> int:
        path = MCDSaveFilePath(path)
        node = self._get_node_from_path(path)
        node_data = MCDNodeData(node)

        if node_data.type == "str":
            return node_data.length
        elif node_data.type == "int":
            length = node_data.length
            signed = node.attrib.get("signed", "false").lower() == "true"
            if signed:
                max_val = (2 ** (8 * length - 1)) - 1
                return len(str(max_val)) + 1
            else:
                max_val = (2 ** (8 * length)) - 1
                return max(len(str(max_val)), length * 2 + 2)
        elif node_data.type == "float":
            return 20
        elif node_data.type == "bool":
            return 5
        return 15

    def GetEnumChoices(self, path: ValidSaveFilePath) -> list[MCDEnumItem] | None:
        path = MCDSaveFilePath(path)
        node = self._get_node_from_path(path)
        if node.tag == "enum":
            enum_id = node.attrib.get("id")
            if enum_id and enum_id in self._enums:
                return self._enums[enum_id].items
        return None

    def parse_value(self, path: ValidSaveFilePath, raw_input: str) -> Any:
        path = MCDSaveFilePath(path)
        if raw_input == "":
            return self.GetFileEntryOriginalValue(path)

        node = self._get_node_from_path(path)
        node_data = MCDNodeData(node)

        if node_data.type == "int":
            try:
                parsed_value = int(raw_input, 0)
            except ValueError:
                raise ValueError("Invalid integer format.")

            length = node_data.length
            signed = node.attrib.get("signed", "false").lower() == "true"

            if signed:
                min_val = -(2 ** (8 * length - 1))
                max_val = (2 ** (8 * length - 1)) - 1
            else:
                min_val = 0
                max_val = (2 ** (8 * length)) - 1

            if not (min_val <= parsed_value <= max_val):
                raise ValueError(f"Value out of bounds! Must be between {min_val} and {max_val} for {length} byte(s).")
            return parsed_value
        elif node_data.type == "float":
            try:
                return float(raw_input)
            except ValueError:
                raise ValueError("Invalid float format.")
        elif node_data.type == "bool":
            val_lower = raw_input.strip().lower()
            if val_lower in ("true", "1", "yes"):
                return True
            if val_lower in ("false", "0", "no"):
                return False
            raise ValueError("Boolean must be true/false, 1/0, or yes/no.")
        elif node_data.type == "str":
            length = node_data.length
            encoding = node.attrib.get("encoding", "ascii")
            encoded = raw_input.encode(encoding)
            if len(encoded) > length:
                raise ValueError(f"String too long! Exceeds maximum length of {length} bytes.")
            return raw_input.ljust(length, "\x00")

        return raw_input

    def SerializeToFile(self, block: MCDBlock, root: ElementTree.Element):
        writer = MCDWriter(block.stream)
        writer.jump(0x100)

        file_node = root.find("file")
        if file_node is not None:
            for node in file_node:
                node_data = MCDNodeData(node)
                if node_data.type == "blank":
                    writer.jump(node_data.length)
                    continue
                key = node_data.name if node_data.name is not None else node.tag
                self._serialize_element(node, MCDSaveFilePath(key), writer)

            for checksum_node in root.findall("checksum"):
                cs_type = checksum_node.attrib.get("type", "xor").lower()
                cs_range = checksum_node.attrib.get("range", "0x0:0x1FFE")
                cs_offset = int(checksum_node.attrib.get("offset", "0x1FFF"), 0)
                cs_length = int(checksum_node.attrib.get("length", "1"), 0)
                cs_order = str(checksum_node.attrib.get("order", "big")).lower()
                if cs_order not in ("big", "little"):
                    raise ValueError(f"Expected checksum 'order' to be 'big' or 'little', got '{cs_order}'")

                start_str, end_str = cs_range.split(":")
                start_pos = 0x2000 * (self.block.block_id + 1) + int(start_str, 0)
                end_pos = 0x2000 * (self.block.block_id + 1) + int(end_str, 0)
                target_data = writer.read_at(start_pos, end_pos - start_pos)

                if cs_type == "sum":
                    chk = 0
                    for b in target_data:
                        chk += b
                    cs_bytes = chk.to_bytes(cs_length, cs_order)
                    writer.write_at(cs_offset, cs_bytes)
                elif cs_type == "xor":
                    chk = 0
                    for b in target_data:
                        chk ^= b
                    cs_bytes = chk.to_bytes(cs_length, cs_order)
                    writer.write_at(cs_offset, cs_bytes)
                else:
                    raise ValueError(f"Unknown checksum type: '{cs_type}'")

        block.stream = bytes(writer.readall())
        writer.dump(self._src_file, merge_at=(block.block_id + 1) * 0x2000)

        buf.buf_disable_alt()
        core.info(f"Changes applied to .../{'/'.join(self._src_file.parts[-2:])}:")
        for i, (c_path, c_val) in enumerate(self.changes.items()):
            if i >= 10:
                core.info(f"  ...and {len(self.changes) - i} more")
                break
            core.info(f"  [{c_path}] => {c_val}")
        buf.buf_enable_alt()

        self.changes.clear()
        raise UserExitCommand

class Notification:
    def __init__(self, **kwargs):
        self.width: int = kwargs.get("width", 30)
        self.height: int = kwargs.get("height", 8)
        self.title: str = kwargs.get("title", "")
        self.hint: str = kwargs.get("hint", "")
        self.prompt: list[str] = kwargs.get("prompt", "")

        self.is_input: bool = kwargs.get("is_input", False)
        if self.is_input:
            self.path: MCDSaveFilePath = kwargs.get("path", MCDSaveFilePath(""))
            self.max_len: int = kwargs.get("max_len", 0)
            self.limit_choices: list[Any] = kwargs.get("valid_choices", [])
            self.choice_index: int = kwargs.get("choice_index", 0)
            self.input_text: str = str(kwargs.get("initial_value", ""))

class UserExitCommand(Exception):
    pass

class MCDFileEditor:
    def __init__(self, block: MCDBlock, src_file: Path):
        if not core.FORMATS_PATH.exists() or not core.FORMATS_PATH.is_dir():
            raise FileNotFoundError(core.FORMATS_PATH)

        self.running = False
        self.width, self.height = 0, 0
        self.game_db: dict|None = None

        self.open_notifs: list[Notification] = []

        self._block = block
        self._frame = block.DirectoryFrame

        self._editor_option_selected = 0
        self._editor_cursor_pos = 0

        self._format_id = self._frame.FormatID
        self._mapped_id = cmn.get_mapped_format(self._format_id)
        try:
            self._format_file_path = cmn.get_format_file(self._format_id)
            if not self._format_file_path:
                return

            root = ElementTree.parse(self._format_file_path).getroot()
            self._save_file = MCDSaveFile(root, block, src_file)
            self._content = self._save_file.RawContent
        except cmn.UnknownFormatError:
            self._format_file_path = ""
            self._content = {}

        self._pretty_content: list[tuple[str, MCDSaveFilePath, bool, bool]] = []
        self._collapsed_paths: set[MCDSaveFil_save_fileePath] = set()
        self._current_line = 0
        self._win_off = 0

    def _get_lines(self, name: str, src: Any, path: ValidSaveFilePath, prefix: str = "", is_last: bool = True, is_root: bool = False) -> list[tuple[str, MCDSaveFilePath, bool, bool]]:
        path = MCDSaveFilePath(path)
        src = self._save_file.GetFileEntryValue(path) if path in self._save_file.changes else src

        lines = []

        if is_root:
            connector = ""
            child_prefix = ""
        else:
            connector = f"{colors.DIM} └─ {colors.RESET}" if is_last else f"{colors.DIM} ├─ {colors.RESET}"
            child_prefix = prefix + ("   " if is_last else f"{colors.DIM} │  {colors.RESET}")

        t_col = colors.DIM
        res = colors.RESET

        u_col = colors.DIM if self._save_file.IsEntryUnused(path) else ""
        u_name = " (unedit.)" if self._save_file.IsEntryUnused(path) else ""

        c_col = colors.DIM if path in self._save_file.changes else ""
        c_name = " (changed)" if path in self._save_file.changes else ""

        current_prefix = prefix + connector

        def trunc(s: str, max_len: int = 60) -> str:
            return s if len(s) <= max_len else s[:max_len - 3] + "..."

        is_expandable = isinstance(src, (list, dict)) and len(src) > 0
        is_uneditable = self._save_file.IsEntryUnused(path)

        informal_name = self._save_file.GetFileEntryName(path)
        f_name = f" ({informal_name})" if informal_name != name else ''

        if is_expandable:
            indicator = f"{colors.BOLD}[+]{res}" if path in self._collapsed_paths else f"{colors.BOLD}[-]{res}"
            name_display = f"{indicator} {u_col}{name}{f_name}{u_name}{res}{c_col}{c_name}{res}"
        else:
            name_display = f"{u_col}{name}{f_name}{u_name}{res}{c_col}{c_name}{res}"

        if isinstance(src, str):
            length = self._save_file.GetFileEntryByteLength(path)
            l_msg = f"{t_col}({length}, 0x{length:X}){res}"
            lines.append((f"{current_prefix}{name_display} {t_col}(str){res}: '{trunc(src)}' {l_msg}", path, False, is_uneditable))
        elif isinstance(src, int):
            lines.append(
                (f"{current_prefix}{name_display} {t_col}(int){res}: {src} {t_col}(0x{src:X}){res}", path, False, is_uneditable))
        elif isinstance(src, list):
            t_name = type(src).__name__
            lines.append((f"{current_prefix}{name_display} {t_col}({t_name}, {len(src)}){res}:", path, True, is_uneditable))
            if path not in self._collapsed_paths:
                for i, v in enumerate(src):
                    lines.extend(self._get_lines(f"[{i}]", v, path / i, child_prefix, i == len(src) - 1))
        elif isinstance(src, dict):
            lines.append((f"{current_prefix}{name_display} {t_col}(dict, {len(src)}){res}:", path, True, is_uneditable))
            if path not in self._collapsed_paths:
                items = list(src.items())
                for i, (k, v) in enumerate(items):
                    lines.extend(self._get_lines(str(k), v, path / k, child_prefix, i == len(items) - 1))
        elif isinstance(src, MCDEnumItem):
            lines.append(
                (f"{current_prefix}{name_display} {t_col}(enum){res}: {src.display} {t_col}({src.name}, 0x{src.value:X}){res}",
                 path, False, is_uneditable)
            )
        else:
            lines.append(
                (f"{current_prefix}{name_display} {t_col}({type(src).__name__}){res}: {t_col}(content omitted){res}",
                 path, False, is_uneditable))

        return lines

    def _update_content(self):
        if self._format_file_path:
            self._content = self._save_file.RawContent

        frame = self._block.DirectoryFrame
        mapped_fmt = cmn.get_mapped_format(frame.FormatID)
        contributor = cmn.contributors.get(mapped_fmt, None)
        contributor_message = f" by {contributor}" \
            if contributor is not None else ""

        if self._format_file_path:
            matched = f" {colors.DIM}(matched to {mapped_fmt}.xml{contributor_message}){colors.RESET}"\
                if frame.FormatID != mapped_fmt else ""
        else:
            matched = f" {colors.DIM}(missing format file){colors.RESET}"

        product = frame.ProductCode.replace('-', f'{colors.DIM}-{colors.RESET}')
        game_name = db.get_db_entry(self.game_db, frame.ProductCode).localized_name
        dev_name = db.get_db_entry(self.game_db, frame.ProductCode).developer
        self._pretty_content = [
            (f"Region: {frame.RegionCode} {colors.DIM}({frame.Region}: {frame.RegionWorld}){colors.RESET}", MCDSaveFilePath(""), False, True),
            (f"Format: {frame.FormatID}{matched}", MCDSaveFilePath(""), False, True),
            (f"Product Code: {product} {colors.DIM}({game_name} by {dev_name}){colors.RESET}", MCDSaveFilePath(""), False, True),
        ]

        if not self._format_file_path:
            message = "─[ 404 Not Found! ]"
            width = self.width - len(message) - 4

            self._pretty_content.extend([
                ((message + "─" * width), MCDSaveFilePath(""), False, True),
                ("", MCDSaveFilePath(""), False, True),
                ("This file does not exist yet!", MCDSaveFilePath(""), False, True),
                (f"{colors.ITALIC}If you'd like, press [Enter] to create a CONTRIBUTE.py file for it!{colors.RESET}",
                 MCDSaveFilePath(""), False, True),
            ])
        else:
            message = f"─[ ↑ Metadata ↓ Save Data ]"
            width = self.width - len(message) - 4

            self._pretty_content.extend([
                ((message + "─" * width), MCDSaveFilePath(""), False, True),
                ("", MCDSaveFilePath(""), False, True)
            ])

            items = list(self._content.items())
            for i, (k, v) in enumerate(items):
                self._pretty_content.extend(self._get_lines(k, v, path=k, is_root=True))
            if self._save_file.Unfinished:
                message = "─[ This is a work in progress! ]"
                width = self.width - len(message) - 4

                self._pretty_content.extend([
                    ("", MCDSaveFilePath(""), False, True),
                    ((message + "─" * width), MCDSaveFilePath(""), False, True),
                    ("The author of this file has marked it as unfinished!", MCDSaveFilePath(""), False, True),
                    ("Not every value, option, nook and cranny may be available for editing!", MCDSaveFilePath(""), False,
                     True),
                    (f"{colors.ITALIC}If you'd like to help out, press [Enter] to generate a CONTRIBUTE file "
                     f"for {mapped_fmt}.xml{colors.RESET}", MCDSaveFilePath(""), False, False),
                ])
            else:
                message = "─[ Found an issue? ]"
                width = self.width - len(message) - 4

                self._pretty_content.extend([
                    ("", MCDSaveFilePath(""), False, True),
                    ((message + "─" * width), MCDSaveFilePath(""), False, True),
                    ("If you've found an issue in this file, you can do something about it!", MCDSaveFilePath(""), False, True),
                    (f"{colors.ITALIC}If you'd like to contribute, press [Enter] to generate a CONTRIBUTE file "
                     f"for {mapped_fmt}.xml{colors.RESET}", MCDSaveFilePath(""), False, False),
                ])

    def _add_notif(self, params: Notification):
        self.open_notifs.append(params)

    def _close_notif(self):
        self.open_notifs.pop()

    @staticmethod
    def _write_multiline_center(lines: list[str], cx: int, cy: int):
        for i, line in enumerate(lines):
            cur.cur_goto(cx - cmn.visible_len(line) // 2, cy + i)
            buf.buf_write(line)

    def _render_notifs(self):
        cx, cy = self.width // 2, self.height // 2
        if not self.open_notifs:
            return

        for i, notif in enumerate(self.open_notifs):
            is_last = i == len(self.open_notifs) - 1

            lines = []
            min_height = 2
            min_width = max(2, len(notif.title) + 2, len(notif.hint) + 2)

            if hasattr(notif, "prompt"):
                lines = notif.prompt
                for line in lines:
                    if cmn.visible_len(line) + 2 > min_width:
                        min_width = cmn.visible_len(line) + 2
                min_height += len(lines)
            if hasattr(notif, "is_input") and getattr(notif, "is_input"):
                min_height += 1

            notif.width = max(notif.width, min_width + 2)
            notif.height = max(notif.height, min_height + 2)

            px, py = cx - notif.width // 2, cy - notif.height // 2
            cmn.draw_box(cmn.BoxDrawingParams(
                x=px,
                y=py,
                width=notif.width,
                height=notif.height,
                title=notif.title,
                border_color="" if is_last else colors.DIM
            ))

            if notif.hint:
                cur.cur_goto(cx - len(notif.hint) // 2, py + notif.height - 1)
                buf.buf_write(notif.hint)
            if lines:
                self._write_multiline_center(lines, cx, py + 2)
            if notif.is_input:
                if notif.limit_choices:
                    display_str = f"< {notif.input_text} >"
                    self._write_multiline_center([display_str], cx, py + len(lines) + 2)
                elif notif.max_len != 0:
                    cur.cur_goto(cx - notif.max_len // 2 - 1, py + len(lines) + 2)
                    padded_input = notif.input_text + " " * (notif.max_len - len(notif.input_text))
                    cursor_pos = min(len(notif.input_text), notif.max_len)

                    before = padded_input[:cursor_pos]
                    if cursor_pos == notif.max_len:
                        cursor_char = ""
                    else:
                        cursor_char = padded_input[cursor_pos]
                    after = padded_input[cursor_pos + 1:]

                    buf.buf_write(f"|{before}{colors.REVERSE}{cursor_char}{colors.RESET}{after}{colors.RESET}|")
                else:
                    self._write_multiline_center([notif.input_text], cx, py + len(lines) + 2)

    def _save_notification_input(self, notif: Notification) -> bool:
        path = notif.path
        original_value = self._save_file.GetFileEntryOriginalValue(path)
        raw_input = notif.input_text

        try:
            parsed_value = self._save_file.parse_value(path, raw_input)
            if parsed_value == original_value:
                self._save_file.changes.pop(path, None)
            else:
                self._save_file.changes[path] = parsed_value
            return True
        except ValueError as e:
            self._close_notif()
            self._add_notif(Notification(
                width=0,
                height=0,
                title=" Edit failed! ",
                hint=" [q] to close ",
                prompt=[
                    f"{colors.BOLD}Failed to edit value!{colors.RESET}",
                    f"{colors.DIM}(changes were not applied){colors.RESET}",
                    "",
                    f"Here's what we know {colors.DIM}(error message){colors.RESET}:",
                    str(e),
                ]
            ))
            return False

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

        if self.open_notifs:
            self._render_notifs()
            buf.buf_flush()
            return

        max_lines = len(self._pretty_content)
        visible_rows = max(1, self.height - 2)

        g_name = db.get_db_entry(self.game_db, self._frame.ProductCode).localized_name
        title = f"[ Index of Block 0x{self._block.block_id:02X} | {g_name} ]"

        cmn.draw_box(cmn.BoxDrawingParams(
            x=1,
            y=1,
            width=self.width,
            height=self.height,
            title=title,
            title_color=colors.BOLD,
            border_color=colors.DIM
        ))

        for i in range(visible_rows):
            idx = self._win_off + i
            if idx >= max_lines:
                break

            line_text, path, is_expandable, is_uneditable = self._pretty_content[idx]
            is_selected = (idx == self._current_line)
            is_create_new_sh = self._current_line == len(self._pretty_content) - 1

            if is_expandable:
                action = "expand" if path in self._collapsed_paths else "collapse"
                right_text = f" [Enter] to {action} " if is_selected else ""
            elif is_selected and is_create_new_sh:
                right_text = " [Enter] to create CONTRIBUTE.py "
            elif not is_uneditable:
                right_text = " [Enter] to edit " if is_selected else ""
            else:
                right_text = ""

            visible_len = cmn.visible_len(line_text)
            pad_len = self.width - visible_len - len(right_text) - 4
            cur.cur_goto(2, 2 + i)

            if pad_len < 0:
                max_vis = max(10, self.width - len(right_text) - 4)

                out = []
                vis_len = 0
                idx = 0
                while idx < len(line_text):
                    if line_text[idx] == '\x1b':
                        match = cmn.ANSI_ESCAPE.match(line_text, idx)
                        if match:
                            esc = match.group(0)
                            out.append(esc)
                            idx += len(esc)
                            continue
                    if vis_len >= max_vis - 3:
                        out.append(f"{colors.RESET}...")
                        break
                    out.append(line_text[idx])
                    vis_len += 1
                    idx += 1
                truncated_line = "".join(out)

                if is_selected:
                    safe_line = truncated_line.replace(colors.DIM, "")
                    safe_line = safe_line.replace(colors.RESET, colors.RESET + colors.REVERSE)
                    buf.buf_write(f"{colors.REVERSE} {safe_line}{right_text} {colors.RESET}")
                else:
                    buf.buf_write(f" {truncated_line}{right_text} ")
            else:
                padding = " " * pad_len
                if is_selected:
                    safe_line = line_text.replace(colors.DIM, "")
                    safe_line = safe_line.replace(colors.RESET, colors.RESET + colors.REVERSE)
                    buf.buf_write(f"{colors.REVERSE} {safe_line}{padding}{right_text} {colors.RESET}")
                else:
                    buf.buf_write(f" {line_text}{padding}{right_text} ")

        cur.cur_goto(2, self.height)
        sv_col = colors.DIM if self._format_file_path and (not self._save_file.changes) else ""
        buf.buf_write(f"{colors.BOLD}[ [Q]: return, [Esc]: exit, "
                      f"{sv_col}[Y]: save changes ]{colors.RESET}")
        buf.buf_flush()

    def update(self, key: str|None):
        self.width, self.height = os.get_terminal_size()
        max_lines = len(self._pretty_content)
        visible_rows = max(1, self.height - 2)

        if max_lines == 0:
            return

        if self.open_notifs:
            top_notif = self.open_notifs[-1]
            if top_notif.is_input:
                if top_notif.limit_choices:
                    if key in ("LEFT", "a", "A"):
                        top_notif.choice_index = (top_notif.choice_index - 1) % len(top_notif.limit_choices)

                        choice = top_notif.limit_choices[top_notif.choice_index]
                        input_text = f"{choice.display} {colors.DIM}({choice.name}){colors.RESET}"
                        top_notif.input_text = input_text
                        return
                    elif key in ("RIGHT", "d", "D"):
                        top_notif.choice_index = (top_notif.choice_index + 1) % len(top_notif.limit_choices)

                        choice = top_notif.limit_choices[top_notif.choice_index]
                        input_text = f"{choice.display} {colors.DIM}({choice.name}){colors.RESET}"
                        top_notif.input_text = input_text
                        return
                    elif key == "\r":
                        selected_item = top_notif.limit_choices[top_notif.choice_index]
                        original_value = self._save_file.GetFileEntryOriginalValue(top_notif.path)
                        orig_val = original_value.value if isinstance(original_value, MCDEnumItem) else original_value

                        if selected_item.value == orig_val:
                            self._save_file.changes.pop(top_notif.path, None)
                        else:
                            self._save_file.changes[top_notif.path] = selected_item

                        self._close_notif()
                        self._update_content()
                        return
                    elif key in ("q", "Q", "\x1B"):
                        self._close_notif()
                        return
                else:
                    if key == "\r":
                        if self._save_notification_input(top_notif):
                            self._close_notif()
                        self._update_content()
                        return
                    elif key == "\x1B":
                        self._close_notif()
                    elif key == "\x7F":
                        top_notif.input_text = top_notif.input_text[:-1]
                        return
                    elif key and len(key) == 1 and ord(key) >= 32:
                        top_notif.input_text += key
                        if top_notif.max_len != 0:
                            top_notif.input_text = top_notif.input_text[:top_notif.max_len]
                        return
            elif key in ("q", "Q", "\x1B"):
                self._close_notif()
        else:
            if key in ("q", "Q"):
                if self.open_notifs:
                    self._close_notif()
                else:
                    raise KeyboardInterrupt
            elif key == "\x1B":
                raise UserExitCommand
            elif key in ("UP", "w", "W"):
                if not self.open_notifs:
                    self._current_line -= 1
            elif key in ("DOWN", "s", "S"):
                if not self.open_notifs:
                    self._current_line += 1
            elif key in ("LEFT", "a", "A"):
                if not self.open_notifs:
                    _, path, is_expandable, _ = self._pretty_content[self._current_line]
                    if is_expandable and path not in self._collapsed_paths:
                        self._collapsed_paths.add(path)

                        self._update_content()
                        max_lines = len(self._pretty_content)
            elif key in ("RIGHT", "d", "D"):
                if not self.open_notifs:
                    _, path, is_expandable, _ = self._pretty_content[self._current_line]
                    if is_expandable and path in self._collapsed_paths:
                        self._collapsed_paths.remove(path)

                        self._update_content()
                        max_lines = len(self._pretty_content)
            elif key == "g":
                if not self.open_notifs:
                    self._current_line = 0
            elif key == "G":
                if not self.open_notifs:
                    self._current_line = max_lines - 1
            elif key in ("y", "Y"):
                if self._save_file.changes:
                    self._save_file.SerializeToFile(self._block, self._save_file.svedit_root)
            elif key == "\r":
                line_text, path, is_expandable, is_uneditable = self._pretty_content[self._current_line]
                is_create_new_sh = self._current_line == len(self._pretty_content) - 1
                if is_create_new_sh:
                    buf.buf_disable_alt()
                    mapped_fmt = cmn.get_mapped_format(self._frame.FormatID)
                    file_name = core.CONTRIB_FILE.replace("%fmt", mapped_fmt)
                    cmn.generate_contribute_sh(mapped_fmt)

                    core.info(f"Created {core.PARENT_PATH / file_name}.")
                    core.info(f"Run to clone the repository and open {mapped_fmt}.xml in your code editor!")
                    buf.buf_enable_alt()

                    raise UserExitCommand
                elif is_expandable:
                    if path in self._collapsed_paths:
                        self._collapsed_paths.remove(path)
                    else:
                        self._collapsed_paths.add(path)
                    self._update_content()
                    max_lines = len(self._pretty_content)
                elif not is_uneditable:
                    if not self.open_notifs:
                        value = self._save_file.GetFileEntryValue(path)
                        enum_choices = self._save_file.GetEnumChoices(path)

                        if enum_choices:
                            initial_idx = 0
                            for idx, choice in enumerate(enum_choices):
                                if isinstance(value, MCDEnumItem) and choice.value == value.value:
                                    initial_idx = idx
                                    break
                                elif not isinstance(value, MCDEnumItem) and choice.value == value:
                                    initial_idx = idx
                                    break

                            choice = enum_choices[initial_idx]
                            input_text = f"{choice.display} {colors.DIM}({choice.name}){colors.RESET}"

                            self._add_notif(Notification(
                                width=0,
                                height=0,
                                title=f" {str(path)} ",
                                hint=" [Left/Right]: cycle, [Enter]: save, [q]: cancel ",
                                is_input=True,
                                prompt=[f"Select Enum Value"],
                                path=path,
                                valid_choices=enum_choices,
                                choice_index=initial_idx,
                                initial_value=input_text
                            ))
                        else:
                            max_len = self._save_file.GetInputMaxLength(path)
                            self._add_notif(Notification(
                                width=0,
                                height=0,
                                title=f" {str(path)} ",
                                hint=" [Esc] to cancel, [Enter] to save changes ",
                                is_input=True,
                                prompt=[f"Edit '{path[-1]}' ({type(value).__name__})"],
                                path=path,
                                initial_value=str(value),
                                max_len=max_len
                            ))

        self._current_line = max(0, min(self._current_line, max_lines - 1))

        if self._current_line < self._win_off:
            self._win_off = self._current_line
        elif self._current_line >= self._win_off + visible_rows:
            self._win_off = self._current_line - visible_rows + 1

    def run(self):
        self.running = True
        self.width, self.height = os.get_terminal_size()

        buf.buf_enable_alt()
        buf.buf_clear()
        cur.cur_hide()

        if not core.YAML_PATH.exists() and not core.PKL_PATH.exists():
            message = f"Fetching game database... {colors.DIM}(This might take a sec...){colors.RESET}"
        elif not core.PKL_PATH.exists():
            message = f"Compiling game database... {colors.DIM}(This might take a sec...){colors.RESET}"
        else:
            message = f"Loading block {self._block.DirectoryFrame.FormatID}..."
        cur.cur_goto(self.width // 2 - cmn.visible_len(message) // 2, self.height // 2)
        buf.buf_write(message)
        buf.buf_flush()

        try:
            self.game_db = db.get_db()
        except db.IncompleteUpdateError:
            buf.buf_disable_alt()
            cur.cur_show()
            core.err("Download incomplete! Will retry on next launch!")
            return
        except cmn.NoInternetError:
            buf.buf_disable_alt()
            cur.cur_show()
            core.err("Check your internet connection! Will retry download on next launch!")
            core.err("Note: If you don't want svedit to download the game database for you:")
            core.err(f"      1. Download {core.DATABASE_URL};")
            core.err(f"      2. Place the downloaded file here: {core.YAML_PATH.absolute()};")
            core.err(f"      3. Launch svedit again;")
            return
        self._update_content()

        def _on_sigwinch(_, __):
            self.width, self.height = os.get_terminal_size()
            self._update_content()
        old_handler = signal.signal(signal.SIGWINCH, _on_sigwinch)

        try:
            while self.running:
                self.render()
                key = cmn.get_key()
                self.update(key)
        except KeyboardInterrupt:
            self.running = False
            return
        finally:
            signal.signal(signal.SIGWINCH, old_handler)
            buf.buf_disable_alt()
            cur.cur_show()