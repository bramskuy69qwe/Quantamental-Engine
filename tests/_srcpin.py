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

import re


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



def args(src: str, fn: str) -> list[list[str]]:
    """Every call to `fn(...)` in `src`, as a list of its top-level arguments.

    Balanced-paren, not a regex. The first draft of this file used
    `fn\\((.*?)\\)` and it reported ZERO calls in two modules and the wrong
    argument in two more — `_ptJson(url, qePollDeadline(everyMs))` stops the
    lazy match at the INNER `)`. A coverage pin that silently parses nothing
    passes vacuously, which is the exact failure mode `_srcpin` exists to warn
    about, so `test_the_call_parser_is_not_blind` checks it finds what it
    should before anything reasons with it.
    """
    out = []
    # `(?<![\w$.])`: without it, args(src, "load") also matches
    # `reload(` / `upload(` / `_mdlUpload(`, and args(src, "get")
    # matches `params.get(` — a future `preload(a, b, c, SOME_MS)` would
    # then satisfy the drift pin for a constant that feeds no read.
    for m in re.finditer(r"(?<![\w$.])" + re.escape(fn) + r"\(", src):
        i, depth, arg, args = m.end(), 1, [], []
        while i < len(src) and depth:
            ch = src[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if not depth:
                    break
            if depth == 1 and ch == ",":
                args.append("".join(arg).strip())
                arg = []
            else:
                arg.append(ch)
            i += 1
        args.append("".join(arg).strip())
        out.append([a for a in args if a != ""])
    return out


def phantom_openers(src: str) -> list[int]:
    """1-based line numbers where a `//` comment contains a block-comment
    opener — see TestTheCommentStripperTrap for what that costs.

    A FUNCTION, not two lines inlined in the test: the self-check below has to
    exercise the same code the parametrized test runs, or it proves only that
    its own copy works (which is exactly how the first draft passed while the
    real assertion was neutered).
    """
    out = []
    for n, line in enumerate(src.splitlines(), 1):
        i = line.find("//")
        if i >= 0 and "/" + "*" in line[i:]:
            out.append(n)
    return out


def scheduled_delays(src: str) -> list[str]:
    """The delay argument of every setInterval/setTimeout call."""
    return [a[-1] for fn in ("setInterval", "setTimeout")
            for a in args(src, fn) if len(a) >= 2]


def const(src: str, name: str) -> int:
    """The numeric value of a `const NAME = 1234;` declaration."""
    m = re.search(rf"const {re.escape(name)} = ([0-9_]+);", src)
    assert m, f"{name} is not a numeric const"
    return int(m.group(1).replace("_", ""))
