"""End-to-end verification for Headroom behind DeepSeek Harness.

Run this against a live proxy to prove the whole chain works. It is the script
that caught the one real bug in this integration, so it is kept as a runnable
regression check rather than deleted.

    1. header safety   -- h11 must accept every sanitized x-headroom-model value
    2. streaming       -- a real SSE completion survives the proxy round trip
    3. compression     -- a big tool result is actually shrunk, FATAL row intact
    4. discovery       -- GET /v1/models passes through for the provider picker

Usage (Windows, from the workspace root):

    .proxy-venv\\Scripts\\python.exe plugin\\verify\\verify_headroom.py

The provider key is read from HEADROOM_TEST_API_KEY, or from the DSH credentials
file via --credentials. Nothing is written anywhere; the proxy's own state lives
under HEADROOM_WORKSPACE_DIR.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

PROXY_BASE = os.environ.get("HEADROOM_PROXY_URL", "http://127.0.0.1:8787").rstrip("/")
PROXY_CHAT = f"{PROXY_BASE}/v1/chat/completions"
PROXY_MODELS = f"{PROXY_BASE}/v1/models"

# Deliberately carries a trailing space: this is the id the DSH picker produced,
# and the exact value that used to kill every response with `Illegal header value`.
MODEL = "deepseek-v4.1-flash "


def load_key(args) -> str:
    key = os.environ.get("HEADROOM_TEST_API_KEY")
    if key:
        return key
    if not args.credentials:
        sys.exit(
            "No key. Set HEADROOM_TEST_API_KEY, or pass "
            "--credentials <path to .credentials.yaml> --credential-ref <NAME>."
        )
    import yaml

    with open(args.credentials, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    try:
        return doc["refs"][args.credential_ref]
    except KeyError:
        sys.exit(f"credential {args.credential_ref!r} not found in {args.credentials}")


def check_header_safety() -> bool:
    """Prove h11 accepts the sanitizer's output for every hostile input."""
    print("=" * 74)
    print("1. header safety (the bug this integration exists to fix)")
    print("=" * 74)

    import h11

    from headroom.proxy.cost import header_safe_model

    def h11_accepts(value: str) -> str:
        try:
            conn = h11.Connection(h11.SERVER)
            conn.send(
                h11.Response(
                    status_code=200,
                    headers=[("content-length", "2"), ("x-headroom-model", value)],
                )
            )
            conn.send(h11.Data(data=b"{}"))
            conn.send(h11.EndOfMessage())
            return "h11-OK"
        except Exception as exc:  # noqa: BLE001 - reporting the reason is the point
            return f"REJECTED {type(exc).__name__}: {str(exc)[:48]}"

    print("  raw model id straight into the header (the shape that used to fail):")
    raw_verdicts = {}
    for raw in (MODEL, MODEL.strip()):
        raw_verdicts[raw] = h11_accepts(raw)
        print(f"    {raw!r:26} -> {raw_verdicts[raw]}")

    print("  routed through header_safe_model:")
    ok = True
    for case in (MODEL, "  x  ", "ok-model", "a\tb", "", "line\nbreak", "a\x00b", None, 5):
        value = header_safe_model(case)
        verdict = h11_accepts(value) if value else "(omitted)"
        if value and verdict != "h11-OK":
            ok = False
        print(f"    {case!r:26} -> {value!r:16} {verdict}")

    if raw_verdicts[MODEL] == "h11-OK":
        print("\n  NOTE: h11 accepted the raw trailing-space value on this build, so the")
        print("  patch is belt-and-braces here rather than strictly required.")
    else:
        print("\n  Reproduced the historical failure on the raw value; the sanitizer fixes it.")
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} - sanitizer output is always header-legal")
    return ok


def _stream_chat(key: str, body: dict, label: str):
    """POST a streaming completion; return (status, headers, text, chunks)."""
    import httpx

    text_parts: list[str] = []
    chunks = 0
    with httpx.stream(
        "POST",
        PROXY_CHAT,
        json=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=180.0,
    ) as resp:
        headers = dict(resp.headers)
        if resp.status_code != 200:
            return resp.status_code, headers, resp.read()[:600].decode("utf-8", "replace"), 0
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            chunks += 1
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for choice in obj.get("choices", []):
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    text_parts.append(piece)
    return 200, headers, "".join(text_parts), chunks


def check_streaming(key: str) -> bool:
    """A streaming completion must survive end to end."""
    print()
    print("=" * 74)
    print("2. streaming round trip")
    print("=" * 74)

    rows = [
        {"id": i, "severity": "info", "msg": f"routine log line {i}", "pad": "x" * 40}
        for i in range(1, 401)
    ]
    rows[66] = {"id": 67, "severity": "FATAL", "msg": "disk failure on /dev/sda", "pad": "y" * 40}

    body = {
        "model": MODEL,
        "stream": True,
        "max_tokens": 64,
        "messages": [
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "Log dump:\n" + json.dumps(rows)},
            {"role": "assistant", "content": "I see the log dump. What should I check?"},
            {
                "role": "user",
                "content": "Of the rows above, which one is the most severe? One short line.",
            },
        ],
    }

    try:
        status, headers, text, chunks = _stream_chat(key, body, "stream")
    except Exception as exc:  # noqa: BLE001 - this is exactly the symptom to report
        print(f"  TRANSPORT FAILURE: {type(exc).__name__}: {exc}")
        print("  A RemoteProtocolError here means the proxy died mid-response.")
        print("RESULT: FAIL")
        return False

    print(f"  HTTP {status}   chunks={chunks}")
    print(f"  x-headroom-model        : {headers.get('x-headroom-model')}")
    print(f"  x-headroom-tokens-before: {headers.get('x-headroom-tokens-before')}")
    print(f"  x-headroom-transforms   : {headers.get('x-headroom-transforms')}")
    print(f"  answer: {text[:160]!r}")

    if status != 200:
        print(f"RESULT: FAIL - body: {text}")
        return False
    # The header must be HTTP-legal, which is exactly `model` with whitespace trimmed.
    if headers.get("x-headroom-model") != MODEL.strip():
        print(f"RESULT: FAIL - header was not sanitized to {MODEL.strip()!r}")
        return False
    if chunks == 0:
        print("RESULT: FAIL - no chunks streamed")
        return False
    print(f"RESULT: PASS - {chunks} chunks streamed, header sanitized")
    return True


def check_compression(key: str) -> bool:
    """A bulky tool result must actually shrink, with the critical row preserved."""
    print()
    print("=" * 74)
    print("3. transparent compression of a tool result")
    print("=" * 74)

    rows = [
        {
            "ts": f"2026-10-16T09:{i // 60:02d}:{i % 60:02d}Z",
            "level": "INFO",
            "service": "checkout",
            "msg": f"request handled ok id={i}",
            "latency_ms": 20 + (i % 37),
            "pad": "filler " * 12,
        }
        for i in range(1, 501)
    ]
    rows[66] = {
        "ts": "2026-10-16T09:01:06Z",
        "level": "FATAL",
        "service": "storage",
        "msg": "disk failure on /dev/sda, array degraded",
        "latency_ms": 9001,
        "pad": "filler " * 12,
    }

    body = {
        "model": MODEL,
        "stream": True,
        "max_tokens": 80,
        "messages": [
            {"role": "system", "content": "You are a log triage assistant. Be terse."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "query_logs", "arguments": '{"range":"1h"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": json.dumps(rows)},
            {"role": "user", "content": "Which single row above is most severe? One short line."},
        ],
    }

    try:
        status, headers, text, chunks = _stream_chat(key, body, "tool")
    except Exception as exc:  # noqa: BLE001
        print(f"  TRANSPORT FAILURE: {type(exc).__name__}: {exc}")
        print("RESULT: FAIL")
        return False

    before = int(headers.get("x-headroom-tokens-before") or 0)
    after = int(headers.get("x-headroom-tokens-after") or 0)
    saved = int(headers.get("x-headroom-tokens-saved") or 0)

    print(f"  HTTP {status}   chunks={chunks}")
    print(f"  tokens before/after/saved: {before} / {after} / {saved}")
    print(f"  transforms: {headers.get('x-headroom-transforms')}")
    print(f"  answer: {text[:160]!r}")

    if status != 200:
        print(f"RESULT: FAIL - body: {text}")
        return False
    if saved <= 0:
        print("RESULT: FAIL - no savings")
        print("  If transforms shows router:protected:user_message only, the bulk sat in")
        print("  the newest user turn, which Headroom protects by design. Move it into a")
        print("  tool result, or confirm --mode token (not the default `cache`).")
        return False
    if "67" not in text and "FATAL" not in text.upper():
        print("RESULT: FAIL - the FATAL row did not survive compression")
        return False
    print(f"RESULT: PASS - saved {saved} tokens ({before} -> {after}, {saved / before:.1%});"
          " FATAL row survived")
    return True


def check_discovery(key: str) -> bool:
    """The provider picker probes /v1/models; it must pass through unchanged."""
    print()
    print("=" * 74)
    print("4. model discovery passthrough")
    print("=" * 74)

    import httpx

    try:
        resp = httpx.get(PROXY_MODELS, headers={"Authorization": f"Bearer {key}"}, timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        print(f"  TRANSPORT FAILURE: {type(exc).__name__}: {exc}")
        print("RESULT: FAIL")
        return False

    print(f"  HTTP {resp.status_code}   {resp.text[:200]}")
    if resp.status_code != 200:
        print("RESULT: FAIL")
        return False
    try:
        ids = [m["id"] for m in resp.json().get("data", [])]
    except Exception as exc:  # noqa: BLE001
        print(f"  RESULT: FAIL - unparseable body: {exc}")
        return False
    print(f"  models advertised: {ids}")
    print("RESULT: PASS")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", help="path to the DSH .credentials.yaml")
    parser.add_argument("--credential-ref", default="TEST_API_KEY", help="ref name inside it")
    parser.add_argument(
        "--only",
        choices=["header", "stream", "compress", "discovery"],
        action="append",
        help="run only these checks (repeatable)",
    )
    args = parser.parse_args()

    print(f"proxy: {PROXY_BASE}")
    print(f"model: {MODEL!r}  (trailing space is intentional)")
    print()

    wanted = set(args.only) if args.only else {"header", "stream", "compress", "discovery"}
    results: dict[str, bool] = {}

    # header safety needs no key or network
    if "header" in wanted:
        results["header"] = check_header_safety()

    needs_key = wanted & {"stream", "compress", "discovery"}
    if needs_key:
        key = load_key(args)
        if "discovery" in wanted:
            results["discovery"] = check_discovery(key)
        if "stream" in wanted:
            results["stream"] = check_streaming(key)
        if "compress" in wanted:
            results["compress"] = check_compression(key)

    print()
    print("=" * 74)
    print("summary")
    print("=" * 74)
    for name, ok in results.items():
        print(f"  {name:10} {'PASS' if ok else 'FAIL'}")

    failed = [n for n, ok in results.items() if not ok]
    print()
    if failed:
        print(f"OVERALL: FAIL ({', '.join(failed)})")
        return 1
    print("OVERALL: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
