#!/usr/bin/env python3
"""Install the DeepSeek Harness registrar into a Headroom source tree.

Why this exists
---------------
Headroom's ``mcp_registry`` teaches ``headroom mcp install`` how to write the
config of each supported client (Claude Code, Codex, Cursor, OpenCode, ...).
This patch adds DeepSeek Harness as one more client, so that

    headroom mcp install

can register Headroom's own MCP server into a DSH profile without any
DSH-specific tooling on the DSH side.

That is a *second*, independent integration path from the Cordis bundle in
``plugin/``. The bundle is what actually ships and needs no upstream release;
this registrar is the change we would like to land upstream, and it is what
lets Headroom install itself the same way it already does for other clients.

What it does
------------
1. Copies ``dsh.py`` (this repository's own code, shipped beside this script)
   into ``<target>/mcp_registry/dsh.py``.
2. Adds the two-line registration to the registry's import list and to the
   registrar fleet -- one line in ``__init__.py``, one in ``install.py``.

All three edits are idempotent: re-running reports ``already`` and changes
nothing, so it is safe to apply on every checkout or upgrade.

Usage
-----
    python patch_headroom_mcp_registry.py --target <path/to/.../headroom>
    python patch_headroom_mcp_registry.py --target <...> --check

``--target`` is a Headroom *package* directory -- the folder containing
``mcp_registry/``. Point it at whichever Headroom tree you have; this repository
does not vendor one, so the usual targets are the environment built by
``bin/setup-proxy-venv.cmd``:

    .proxy-venv/Lib/site-packages/headroom          (Windows)
    .proxy-venv/lib/python3.12/site-packages/headroom   (POSIX)

or your own checkout of ``headroom-ai``. Patching the installed package is the
minimal change: it needs no re-install and leaves the wheel metadata alone.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# The registrar module, shipped next to this script.
SOURCE = Path(__file__).resolve().parent / "upstream" / "dsh.py"
MODULE_NAME = "dsh.py"
CLASS_NAME = "DshRegistrar"

# (file, anchor line that must exist, line to insert after it)
#
# Both integrations are a single import plus a single fleet entry. Anchoring on
# the *Grok* registrar keeps this working when upstream adds clients, instead of
# pinning brittle absolute line numbers. The registrars are kept alphabetical and
# `dsh` sorts between `codex` and `grok`, so inserting after `grok` keeps the
# file readable while staying independent of how many clients exist above it.
#
# Verified against released Headroom 0.41.0, where mcp_registry/ contains
# antigravity, base, claude, codex, display, grok, install, opencode and
# server_json -- note there is no cursor registrar in that release.
IMPORT_ANCHOR = "from .grok import GrokRegistrar"
IMPORT_LINE = "from .dsh import DshRegistrar"

REGISTRY_ENTRY_ANCHOR = "GrokRegistrar(),"
REGISTRY_ENTRY_LINE = "DshRegistrar(),"

# __init__.py re-exports every registrar by name.
INIT_ANCHOR = '"GrokRegistrar",'
INIT_LINE = '"DshRegistrar",'

EDITS = (
    ("mcp_registry/__init__.py", IMPORT_ANCHOR, IMPORT_LINE, "after"),
    ("mcp_registry/__init__.py", INIT_ANCHOR, INIT_LINE, "after"),
    ("mcp_registry/install.py", IMPORT_ANCHOR, IMPORT_LINE, "after"),
    ("mcp_registry/install.py", REGISTRY_ENTRY_ANCHOR, REGISTRY_ENTRY_LINE, "after"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _insert_after_line(text: str, anchor: str, line: str, where: str) -> str | None:
    """Return `text` with `line` inserted beside the first line matching `anchor`.

    Returns None when the anchor is missing, so the caller can report a skip
    rather than corrupting the file.
    """
    lines = text.splitlines(keepends=True)
    for index, existing in enumerate(lines):
        if existing.strip() != anchor:
            continue
        indent = existing[: len(existing) - len(existing.lstrip())]
        newline = "\n" if existing.endswith("\n") else ""
        inserted = f"{indent}{line}{newline}"
        at = index + 1 if where == "after" else index
        lines.insert(at, inserted)
        return "".join(lines)
    return None


def _patch_file(path: Path, edits, check: bool) -> str:
    """Apply every edit for one file. Returns a status word for reporting."""
    text = _read(path)
    original = text

    for _rel, anchor, line, where in edits:
        if line.strip() in text:
            continue  # already applied
        updated = _insert_after_line(text, anchor, line, where)
        if updated is None:
            return f"ANCHOR-MISSING ({anchor!r})"
        text = updated

    if text == original:
        return "already"
    if check:
        return "would patch"
    path.write_text(text, encoding="utf-8")
    return "patched"


def _install_module(target: Path, check: bool) -> str:
    destination = target / "mcp_registry" / MODULE_NAME
    if destination.exists() and destination.read_bytes() == SOURCE.read_bytes():
        return "already"
    if check:
        return "would patch"
    shutil.copyfile(SOURCE, destination)
    return "patched"


def verify(target: Path) -> bool:
    """Confirm the module exists and imports cleanly from the patched tree."""
    module = target / "mcp_registry" / MODULE_NAME
    if not module.exists():
        print(f"  MISSING {module}")
        return False

    # Parse rather than import: the target may be a tree whose dependencies are
    # not installed in the interpreter running this script.
    import ast

    try:
        ast.parse(_read(module))
    except SyntaxError as error:
        print(f"  SYNTAX ERROR in {module}: {error}")
        return False

    # Both integration points must reference the class.
    for relative in ("mcp_registry/__init__.py", "mcp_registry/install.py"):
        text = _read(target / relative)
        if IMPORT_LINE not in text:
            print(f"  {relative}: missing {IMPORT_LINE!r}")
            return False

    install = _read(target / "mcp_registry" / "install.py")
    if REGISTRY_ENTRY_LINE not in install:
        print(f"  mcp_registry/install.py: missing {REGISTRY_ENTRY_LINE!r}")
        return False

    print(f"  {MODULE_NAME} parses; registered in __init__.py and install.py")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the DeepSeek Harness registrar into a Headroom tree."
    )
    parser.add_argument(
        "--target",
        required=True,
        type=Path,
        help="Headroom package directory (the one containing mcp_registry/)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change without writing",
    )
    args = parser.parse_args(argv)

    target: Path = args.target
    if not (target / "mcp_registry").is_dir():
        print(f"error: {target} has no mcp_registry/ directory", file=sys.stderr)
        return 2
    if not SOURCE.exists():
        print(f"error: registrar source not found at {SOURCE}", file=sys.stderr)
        return 2

    print(f"target: {target}")
    print(f"  {'mcp_registry/' + MODULE_NAME:<34} -> {_install_module(target, args.check)}")

    # Group the four line edits by file so each file is read and written once.
    by_file: dict[str, list] = {}
    for edit in EDITS:
        by_file.setdefault(edit[0], []).append(edit)

    for relative, edits in by_file.items():
        path = target / relative
        if not path.exists():
            print(f"  {relative:<34} -> MISSING FILE")
            return 1
        print(f"  {relative:<34} -> {_patch_file(path, edits, args.check)}")

    if args.check:
        print("\ncheck only; nothing written")
        return 0

    if not verify(target):
        return 1
    print("registrar integration OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
