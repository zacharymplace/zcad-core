"""A small reader for KiCad's s-expression files: no CAD, no dependency.

``parse`` turns the text into nested lists. Each list is one parenthesised
form: its first item is the token's name and the rest are its arguments, which
are strings (a quoted string loses its quotes) or further lists. Numbers stay
strings until ``number`` reads them, so a reader takes only the tokens it needs
and skips the many it does not.
"""

from __future__ import annotations

from typing import Any

Node = list[Any]


class SexpError(ValueError):
    """The text is not a well-formed s-expression."""


def _tokens(text: str) -> list[tuple[str, str]]:
    """``("(", "")``, ``(")", "")``, ``("string", s)`` or ``("atom", s)``."""

    found: list[tuple[str, str]] = []
    position, end = 0, len(text)

    while position < end:
        char = text[position]

        if char in " \t\r\n":
            position += 1
        elif char in "()":
            found.append((char, ""))
            position += 1
        elif char == '"':
            position += 1
            chars: list[str] = []

            while position < end and text[position] != '"':
                if text[position] == "\\" and position + 1 < end:
                    position += 1

                chars.append(text[position])
                position += 1

            if position >= end:
                raise SexpError("a quoted string is never closed")

            position += 1
            found.append(("string", "".join(chars)))
        else:
            start = position

            while position < end and text[position] not in ' \t\r\n()"':
                position += 1

            found.append(("atom", text[start:position]))

    return found


def parse(text: str) -> Node:
    """The one top-level form in ``text``."""

    stack: list[Node] = []
    top: Node | None = None

    for kind, value in _tokens(text):
        if kind == "(":
            stack.append([])
        elif kind == ")":
            if not stack:
                raise SexpError("a closing parenthesis has no opening one")

            done = stack.pop()

            if stack:
                stack[-1].append(done)
            elif top is None:
                top = done
            else:
                raise SexpError("more than one top-level form")
        elif stack:
            stack[-1].append(value)
        else:
            raise SexpError("text outside the top-level form")

    if stack:
        raise SexpError("a parenthesis is never closed")

    if top is None:
        raise SexpError("the file is empty")

    return top


def name(node: Node) -> str:
    """A form's token name, or an empty string for an empty form."""

    return node[0] if node and isinstance(node[0], str) else ""


def children(node: Node, token: str) -> list[Node]:
    """The direct sub-forms of ``node`` named ``token``."""

    return [item for item in node[1:] if isinstance(item, list) and name(item) == token]


def child(node: Node, token: str) -> Node | None:
    """The first direct sub-form named ``token``, if any."""

    found = children(node, token)

    return found[0] if found else None


def number(value: Any) -> float:
    """A token's argument as a number."""

    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise SexpError(f"{value!r} is not a number") from error


def numbers(node: Node, count: int) -> tuple[float, ...]:
    """The first ``count`` arguments of a form as numbers, e.g. ``(at x y)``."""

    arguments = node[1:]

    if len(arguments) < count:
        raise SexpError(f"({name(node)}) needs {count} numbers")

    return tuple(number(value) for value in arguments[:count])
