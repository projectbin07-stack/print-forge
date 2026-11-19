"""Read TOML: ``tomllib`` on Python 3.11+, and a small subset parser on Python 3.10.

The subset covers what a parts file needs: comments, ``[table]``, ``[[array.of.tables]]``,
``[parent.child]`` (resolved against the last array element), dotted keys, basic and literal
strings, integers, floats, booleans, arrays of scalars and inline tables. The tests run both
parsers on the same documents and compare the results.
"""

from __future__ import annotations

import importlib
import re
from typing import Any


class TomlError(ValueError):
    pass


def _stdlib() -> Any:
    try:
        return importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        return None


def loads(text: str) -> dict[str, Any]:
    lib = _stdlib()
    if lib is None:  # pragma: no cover - Python 3.10
        return loads_subset(text)
    try:
        result: dict[str, Any] = lib.loads(text)
    except lib.TOMLDecodeError as exc:
        raise TomlError(str(exc)) from None
    return result


_BARE = re.compile(r"[A-Za-z0-9_-]+")
_NUM = re.compile(r"[+-]?(\d[\d_]*)(\.\d[\d_]*)?([eE][+-]?\d+)?$")


def loads_subset(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current = root
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        try:
            if line.startswith("[["):
                if not line.endswith("]]"):
                    raise TomlError("unclosed [[ header")
                path = _split_key(line[2:-2])
                parent = _resolve(root, path[:-1])
                arr = parent.setdefault(path[-1], [])
                if not isinstance(arr, list):
                    raise TomlError(f"{path[-1]!r} is not an array of tables")
                current = {}
                arr.append(current)
            elif line.startswith("["):
                if not line.endswith("]"):
                    raise TomlError("unclosed [ header")
                path = _split_key(line[1:-1])
                current = _resolve(root, path)
            else:
                key, sep, value = line.partition("=")
                if not sep:
                    raise TomlError("expected key = value")
                keys = _split_key(key)
                target = _resolve(current, keys[:-1])
                if keys[-1] in target:
                    raise TomlError(f"duplicate key {keys[-1]!r}")
                parsed, rest = _value(value.strip())
                if rest.strip():
                    raise TomlError(f"unexpected text after value: {rest.strip()!r}")
                target[keys[-1]] = parsed
        except TomlError as exc:
            raise TomlError(f"line {line_no}: {exc}") from None
    return root


def _strip_comment(line: str) -> str:
    out = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                out.append(line[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
        i += 1
    return "".join(out)


def _split_key(text: str) -> list[str]:
    parts = []
    for piece in text.split("."):
        piece = piece.strip()
        if len(piece) >= 2 and piece[0] == piece[-1] and piece[0] in "\"'":
            piece = piece[1:-1]
        elif not _BARE.fullmatch(piece):
            raise TomlError(f"invalid key {text.strip()!r}")
        parts.append(piece)
    return parts


def _resolve(table: dict[str, Any], path: list[str]) -> dict[str, Any]:
    node = table
    for key in path:
        nxt = node.setdefault(key, {})
        if isinstance(nxt, list):
            if not nxt:
                raise TomlError(f"{key!r} is an empty array")
            nxt = nxt[-1]
        if not isinstance(nxt, dict):
            raise TomlError(f"{key!r} is not a table")
        node = nxt
    return node


def _value(s: str) -> tuple[Any, str]:
    if not s:
        raise TomlError("missing value")
    if s.startswith('"'):
        return _basic_string(s)
    if s.startswith("'"):
        end = s.find("'", 1)
        if end < 0:
            raise TomlError("unterminated string")
        return s[1:end], s[end + 1 :]
    if s.startswith("["):
        items: list[Any] = []
        rest = s[1:].lstrip()
        while True:
            if rest.startswith("]"):
                return items, rest[1:]
            val, rest = _value(rest)
            items.append(val)
            rest = rest.lstrip()
            if rest.startswith(","):
                rest = rest[1:].lstrip()
            elif not rest.startswith("]"):
                raise TomlError("expected , or ] in array")
    if s.startswith("{"):
        table: dict[str, Any] = {}
        rest = s[1:].lstrip()
        if rest.startswith("}"):
            return table, rest[1:]
        while True:
            key, sep, after = rest.partition("=")
            if not sep:
                raise TomlError("expected key = value in inline table")
            keys = _split_key(key)
            val, rest = _value(after.strip())
            _resolve(table, keys[:-1])[keys[-1]] = val
            rest = rest.lstrip()
            if rest.startswith(","):
                rest = rest[1:].lstrip()
            elif rest.startswith("}"):
                return table, rest[1:]
            else:
                raise TomlError("expected , or } in inline table")
    m = re.match(r"[^,\]}\s]+", s)
    token = m.group(0) if m else s
    rest = s[len(token) :]
    if token == "true":
        return True, rest
    if token == "false":
        return False, rest
    if _NUM.match(token):
        clean = token.replace("_", "")
        if any(c in clean for c in ".eE"):
            return float(clean), rest
        return int(clean), rest
    raise TomlError(f"cannot parse value {token!r}")


_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


def _basic_string(s: str) -> tuple[str, str]:
    out = []
    i = 1
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            nxt = s[i + 1 : i + 2]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "u":
                out.append(chr(int(s[i + 2 : i + 6], 16)))
                i += 6
                continue
            raise TomlError(f"unsupported escape \\{nxt}")
        if ch == '"':
            return "".join(out), s[i + 1 :]
        out.append(ch)
        i += 1
    raise TomlError("unterminated string")
