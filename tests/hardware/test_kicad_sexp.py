"""The KiCad s-expression reader."""

from __future__ import annotations

import pytest

from zcad_core.hardware.electronics import kicad_sexp
from zcad_core.hardware.electronics.kicad_sexp import SexpError


def test_nested_forms_become_nested_lists() -> None:
    root = kicad_sexp.parse("(a (b 1 2.5) (c) d)")

    assert root == ["a", ["b", "1", "2.5"], ["c"], "d"]
    assert kicad_sexp.name(root) == "a"
    assert kicad_sexp.child(root, "b") == ["b", "1", "2.5"]
    assert kicad_sexp.child(root, "missing") is None
    assert kicad_sexp.numbers(["b", "1", "2.5"], 2) == (1.0, 2.5)


def test_a_quoted_string_keeps_spaces_parentheses_and_escapes() -> None:
    root = kicad_sexp.parse(r'(x "a (b) c" "say \"hi\"" "")')

    assert root == ["x", "a (b) c", 'say "hi"', ""]


def test_children_lists_every_form_of_a_name_and_skips_atoms() -> None:
    root = kicad_sexp.parse("(a (p 1) q (p 2) (r))")

    assert kicad_sexp.children(root, "p") == [["p", "1"], ["p", "2"]]


def test_a_very_deep_file_does_not_overflow_the_stack() -> None:
    depth = 5000
    root = kicad_sexp.parse("(a " * depth + "1" + ")" * depth)

    assert kicad_sexp.name(root) == "a"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("(a (b)", "never closed"),
        ("a)", "text outside|no opening"),
        ("(a) (b)", "more than one"),
        ('(a "open)', "quoted string"),
        ("hello", "outside"),
    ],
)
def test_malformed_text_is_refused(text: str, message: str) -> None:
    with pytest.raises(SexpError, match=message):
        kicad_sexp.parse(text)


def test_a_non_number_is_refused() -> None:
    with pytest.raises(SexpError, match="not a number"):
        kicad_sexp.number("abc")

    with pytest.raises(SexpError, match="needs 2 numbers"):
        kicad_sexp.numbers(["at", "1"], 2)
