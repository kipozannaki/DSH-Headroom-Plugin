#!/usr/bin/env python3
"""Make Headroom's `x-headroom-model` response header HTTP-legal.

Why this is needed
------------------
Headroom echoes the client's model id back in the ``x-headroom-model``
response header:

    forwarded_headers["x-headroom-model"] = model

The model id comes straight off the request body and is never validated. When
a client catalog carries an id with surrounding whitespace -- a trailing space
is common when a deployment pastes a display name into an ``id`` field, and
DeepSeek Harness's own model picker happily produces ``"deepseek-v4.1-flash "``
-- that value is written verbatim into the header. h11 (the HTTP/1.1 stack
uvicorn runs on) then rejects the *entire response*:

    h11._util.LocalProtocolError: Illegal header value b'deepseek-v4.1-flash '

The failure happens after upstream already answered 200 and after compression
already ran, so the whole turn dies at the last step with the client seeing
``Server disconnected without sending a response``. The model id itself is
valid upstream: both ``"deepseek-v4.1-flash "`` and ``"deepseek-v4.1-flash"``
return 200.

What this patch does
--------------------
Adds ``header_safe_model()`` to ``headroom/proxy/cost.py`` (next to the
existing ``header_safe_transforms()``, which solves the same class of problem
for transform tags) and routes all five assignment sites through it. The
sanitized value is used *only* for the metering header -- never for routing or
for the upstream request body -- so behaviour is unchanged apart from the
header being legal.

Usage
-----
    python patch_headroom_model_header.py --target <path/to/site-packages/headroom>
    python patch_headroom_model_header.py --target <...> --check

Idempotent: re-running on an already-patched tree reports ``already`` and
changes nothing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Files carrying an `x-headroom-model` assignment, relative to the package root.
HANDLER_FILES = (
    "proxy/handlers/streaming.py",
    "proxy/handlers/openai.py",
    "proxy/handlers/anthropic.py",
    "proxy/handlers/gemini.py",
)

# Matches `forwarded_headers["x-headroom-model"] = model` at any indentation.
ASSIGN_RE = re.compile(
    r'^(?P<ind>[ \t]*)(?P<dict>\w+)\["x-headroom-model"\] = model[ \t]*$',
    re.MULTILINE,
)

HELPER = "\n".join(
    [
        "",
        "",
        "# Characters that are legal in a model *id* but illegal in an HTTP header",
        "# *value*. The model id comes straight off the client request body, and some",
        "# providers' catalogs carry ids with surrounding whitespace (a trailing space",
        "# is common when a deployment pastes a display name into the id field). Writing",
        "# such a value into ``x-headroom-model`` makes h11 reject the whole response --",
        "# ``Illegal header value b'...'`` -- which kills an otherwise-successful request",
        "# at the last step. Collapsing the whitespace keeps the header legal without",
        "# changing what the client asked for, and the sanitized value is only ever used",
        "# for the metering header, never for routing or the upstream request.",
        r'_HEADER_UNSAFE_RE = re.compile(r"[\x00-\x1f\x7f]")',
        "",
        "",
        "def header_safe_model(model: Any) -> str:",
        '    """Return ``model`` as a value that is always legal in an HTTP header.',
        "",
        "    Surrounding whitespace is stripped and any remaining control characters are",
        "    replaced with ``?``. Non-string input (``None``, an int) becomes ``\"\"`` so",
        "    the caller can decide whether to emit the header at all.",
        '    """',
        "    if not isinstance(model, str):",
        '        return ""',
        r'    return _HEADER_UNSAFE_RE.sub("?", model.strip())',
        "",
        "",
    ]
)


def _next_toplevel_offset(src: str, start: int) -> int:
    """Offset of the first top-level statement after ``start``."""
    lines = src[start:].split("\n")
    offset = start
    for index, line in enumerate(lines):
        if index == 0:
            offset += len(line) + 1
            continue
        if line and not line[0].isspace():
            return offset
        offset += len(line) + 1
    raise SystemExit("could not locate the end of the anchor function")


def patch_cost(pkg: Path, check: bool) -> str:
    path = pkg / "proxy" / "cost.py"
    src = path.read_text(encoding="utf-8")

    if "def header_safe_model(" in src:
        return "already"
    if "def header_safe_transforms(" not in src:
        raise SystemExit(f"{path}: anchor `header_safe_transforms` not found")

    out = src
    if not re.search(r"^import re$", out, re.MULTILINE):
        if not re.search(r"^import math$", out, re.MULTILINE):
            raise SystemExit(f"{path}: anchor `import math` not found")
        out = out.replace("import math\n", "import math\nimport re\n", 1)

    anchor = out.index("def header_safe_transforms(")
    insert_at = _next_toplevel_offset(out, anchor)
    if check:
        return "would patch"
    out = out[:insert_at] + HELPER + out[insert_at:]
    path.write_text(out, encoding="utf-8")
    return "patched"


def patch_handler(pkg: Path, rel: str, check: bool) -> str:
    path = pkg / rel
    src = path.read_text(encoding="utf-8")

    matches = list(ASSIGN_RE.finditer(src))
    if not matches:
        if 'header_safe_model(model)' in src:
            return "already"
        raise SystemExit(f"{path}: no `x-headroom-model = model` assignment found")
    if 'header_safe_model(model)' in src:
        return "already"
    if check:
        return f"would patch ({len(matches)} site(s))"

    # Replace from the last match backwards so earlier offsets stay valid.
    for match in reversed(matches):
        ind = match.group("ind")
        target = match.group("dict")
        replacement = (
            f"{ind}from headroom.proxy.cost import header_safe_model\n"
            f"{ind}\n"
            f"{ind}if _model_header := header_safe_model(model):\n"
            f"{ind}    {target}[\"x-headroom-model\"] = _model_header"
        )
        src = src[: match.start()] + replacement + src[match.end() :]

    path.write_text(src, encoding="utf-8")
    return f"patched ({len(matches)} site(s))"


def verify(pkg: Path) -> None:
    """Fail loudly if the patched tree does not actually import."""
    import subprocess

    files = ["proxy/cost.py", *HANDLER_FILES]
    for rel in files:
        subprocess.run(
            [sys.executable, "-c", f"import ast,pathlib;ast.parse(pathlib.Path(r'{pkg / rel}').read_text(encoding='utf-8'))"],
            check=True,
        )
    print(f"  syntax OK for all {len(files)} files")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True, help="path to the headroom package directory")
    ap.add_argument("--check", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    pkg = Path(args.target).resolve()
    if not (pkg / "proxy" / "cost.py").is_file():
        raise SystemExit(f"{pkg} does not look like a headroom package (no proxy/cost.py)")

    print(f"target: {pkg}")
    print(f"  proxy/cost.py                 -> {patch_cost(pkg, args.check)}")
    for rel in HANDLER_FILES:
        print(f"  {rel:30}-> {patch_handler(pkg, rel, args.check)}")

    if not args.check:
        verify(pkg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
