"""Shared helper for SOURCE pins (greps against frontend/src/*.jsx).

A source-grep pin that matches a COMMENT is not a pin. These modules carry
comments that NAME the very endpoints and components being pinned, so a naive
substring search matches the prose instead of the call site — the `786b610`
comment-trap class, which recurred on 2026-07-30 when three pins survived
deletion of the code they claimed to protect.

`code()` strips BOTH comment forms. Stripping only `//` is not enough: these
modules are commented predominantly with `/* */` block headers.

Discipline for any new source pin (see the memory note "source pins must bite"):
  1. assert against `code(src)`, never raw source;
  2. assert STRUCTURE, not a substring an unrelated pre-existing line satisfies;
  3. when claiming two sides agree, parse BOTH and compare;
  4. mutation-check it — delete the line and confirm the assertion flips.
"""
from __future__ import annotations


def code(src: str) -> str:
    """Executable source only — `/* … */` and `//` comment bodies removed.

    Order matters: block comments first (they can contain `//`), then line
    comments. Newlines inside stripped blocks are preserved so line-oriented
    reasoning still works. Textual, so it assumes neither delimiter appears
    inside a string literal — pinned for the files it runs on by
    `TestCodeStripper::test_real_sources_have_no_delimiters_inside_strings`.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        j = src.find("/*", i)
        if j < 0:
            out.append(src[i:])
            break
        out.append(src[i:j])
        k = src.find("*/", j + 2)
        if k < 0:
            break
        out.append("\n" * src.count("\n", j, k))
        i = k + 2
    stripped = "".join(out)
    return "\n".join(
        (ln if ln.find("//") < 0 else ln[:ln.find("//")])
        for ln in stripped.splitlines()
    )
