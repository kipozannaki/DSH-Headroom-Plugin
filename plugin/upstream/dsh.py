"""DeepSeek Harness (DSH) MCP registrar.

DSH discovers MCP servers through its Cordis Loader patch layer: a YAML *list*
of patch entries at ``<profile>/cordis.patch.yml``. The list form is
positional, so there is no addressable key to delete by name — an entry is
identified by its ``id``, and an MCP client entry by the ``serverName`` inside
its ``config`` block.

One patch entry mounts one MCP server::

    - id: headroom-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: headroom
        transport: stdio
        command: headroom
        args: [mcp, serve]
        env: {}
        failOnStartupError: true

The profile directory comes from ``$DSH_PROFILE_DIR``; when unset we fall back
to ``~/.dsh/profiles`` (the parent of every named profile), which only lets us
*detect* DSH — there is no profile to write into without the variable.

Unlike the JSON/TOML registrars, the whole file is deserialized and re-emitted.
``yaml.safe_dump`` cannot preserve comments or key order, so the safety net is
the refusal below: a file we cannot parse as a list is never overwritten.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from headroom import fsutil

from .base import (
    MCPRegistrar,
    RegisterResult,
    RegisterStatus,
    ServerSpec,
    _diff_specs,
    _specs_equivalent,
)

logger = logging.getLogger(__name__)

#: Cordis plugin that provides an MCP client connection in DSH.
_CLIENT_PLUGIN = "@deepseek-ai/dsh-mcp-client"

#: Stable id for the row we own, so a re-register can find and replace it even
#: if its config block was hand-edited into something we no longer recognize.
_ENTRY_ID = "headroom-mcp"

#: DSH's default profile location, used only for :meth:`DshRegistrar.detect`.
_DEFAULT_PROFILES_DIR = Path.home() / ".dsh" / "profiles"


class _MalformedConfigError(Exception):
    """The patch file exists with content we cannot safely rewrite.

    Raised on the write path so we refuse to clobber a file we can't parse
    instead of replacing a user's Cordis composition with our own entry.
    """


def _read_patch_entries(path: Path) -> list[Any] | None:
    """Parse ``cordis.patch.yml``, returning ``None`` if unusable.

    Safe for READ-ONLY callers only: an unparseable file yields ``None`` here,
    and a caller that went on to write an empty list back would destroy the
    user's patch layer. The write path uses :func:`_read_patch_for_write`.
    """
    if not path.exists():
        return []
    try:
        raw = fsutil.read_text(path)
    except OSError:
        return None
    if not raw.strip():
        return []
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, list) else None


def _read_patch_for_write(path: Path) -> list[Any]:
    """Read the patch list for a subsequent full-file rewrite.

    Returns ``[]`` only when the file is absent or empty (safe to start a fresh
    list). If the file exists with content but does not parse as a YAML list,
    raise :class:`_MalformedConfigError` so the caller aborts — the same file
    holds every other plugin, preset and ``!!js`` patch the profile mounts.
    """
    if not path.exists():
        return []
    try:
        raw = fsutil.read_text(path)  # OSError propagates to the caller
    except UnicodeDecodeError as exc:
        raise _MalformedConfigError(f"not valid UTF-8: {exc}") from exc
    if not raw.strip():
        return []
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise _MalformedConfigError(f"not valid YAML: {exc}") from exc
    if not isinstance(data, list):
        raise _MalformedConfigError(
            f"top level is {type(data).__name__}, expected a YAML list"
        )
    return data


def _write_patch(path: Path, entries: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        entries, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    fsutil.write_text(path, body)


def _config_of(entry: Any) -> dict[str, Any] | None:
    """Return the ``config`` mapping of a client patch entry, else ``None``."""
    if not isinstance(entry, dict):
        return None
    if entry.get("name") != _CLIENT_PLUGIN:
        return None
    config = entry.get("config")
    if not isinstance(config, dict):
        return None
    return config


def _entry_to_spec(server_name: str, entry: dict[str, Any]) -> ServerSpec:
    config = _config_of(entry) or {}
    args_value = config.get("args", [])
    args = tuple(str(x) for x in args_value) if isinstance(args_value, list) else ()
    env_value = config.get("env", {})
    env: dict[str, str] = {}
    if isinstance(env_value, dict):
        env = {str(k): str(v) for k, v in env_value.items()}
    command_value = config.get("command")
    return ServerSpec(
        name=server_name,
        command=str(command_value) if command_value else "",
        args=args,
        env=env,
    )


def _spec_to_entry(spec: ServerSpec) -> dict[str, Any]:
    return {
        "id": _ENTRY_ID,
        "name": _CLIENT_PLUGIN,
        "config": {
            "serverName": spec.name,
            "transport": "stdio",
            "command": spec.command,
            "args": list(spec.args),
            "env": dict(spec.env),
            "failOnStartupError": True,
        },
    }


def _entry_matches(entry: Any, server_name: str) -> bool:
    """True when ``entry`` is an MCP client row for ``server_name``."""
    config = _config_of(entry)
    return config is not None and config.get("serverName") == server_name


def _is_our_entry(entry: Any) -> bool:
    """True when ``entry`` is a row we own, matched by id or serverName."""
    if _entry_matches(entry, "headroom"):
        return True
    return isinstance(entry, dict) and entry.get("id") == _ENTRY_ID


class DshRegistrar(MCPRegistrar):
    """Register MCP servers with DeepSeek Harness."""

    name = "dsh"
    display_name = "DeepSeek Harness"

    def __init__(self, *, profile_dir: Path | None = None) -> None:
        env_dir = os.environ.get("DSH_PROFILE_DIR")
        if profile_dir is not None:
            self._profile_dir: Path | None = profile_dir
        elif env_dir:
            self._profile_dir = Path(env_dir).expanduser()
        else:
            self._profile_dir = None

    @property
    def patch_path(self) -> Path | None:
        """The Cordis patch layer for this profile, or ``None`` if unknown."""
        if self._profile_dir is None:
            return None
        return self._profile_dir / "cordis.patch.yml"

    def detect(self) -> bool:
        if self._profile_dir is not None:
            return True
        return _DEFAULT_PROFILES_DIR.is_dir()

    def get_server(self, server_name: str) -> ServerSpec | None:
        path = self.patch_path
        if path is None:
            return None
        entries = _read_patch_entries(path)
        if entries is None:
            return None
        for entry in entries:
            if _entry_matches(entry, server_name):
                return _entry_to_spec(server_name, entry)
        return None

    def register_server(self, spec: ServerSpec, *, force: bool = False) -> RegisterResult:
        path = self.patch_path
        if path is None:
            return RegisterResult(
                RegisterStatus.FAILED,
                "DSH_PROFILE_DIR is not set, so there is no profile to write "
                "cordis.patch.yml into",
            )

        try:
            entries = _read_patch_for_write(path)
        except _MalformedConfigError as exc:
            # Refuse to overwrite: this one file mounts every other plugin the
            # profile loads, and we cannot merge into what we cannot parse.
            return RegisterResult(
                RegisterStatus.FAILED,
                f"{path} exists but is not a YAML list ({exc}); refusing to "
                "overwrite. Fix or remove the file, then re-run.",
            )
        except OSError as exc:
            return RegisterResult(RegisterStatus.FAILED, f"could not read {path}: {exc}")

        # The read path is the tolerated one — it turns a malformed file into
        # ``None`` — so it can only run after the write-path parse above.
        existing = self.get_server(spec.name)
        if existing is not None and _specs_equivalent(existing, spec):
            return RegisterResult(RegisterStatus.ALREADY, "matches current configuration")

        if existing is not None and not force:
            return RegisterResult(RegisterStatus.MISMATCH, _diff_specs(existing, spec))

        # Replace our own row in place so the profile keeps its patch order;
        # a stale row for the same serverName under another id is dropped
        # rather than left to shadow ours.
        kept = [
            e for e in entries if not (_entry_matches(e, spec.name) or _is_our_entry(e))
        ]
        removed = len(entries) - len(kept)
        kept.append(_spec_to_entry(spec))

        try:
            _write_patch(path, kept)
        except OSError as exc:
            return RegisterResult(RegisterStatus.FAILED, f"could not write {path}: {exc}")

        if removed:
            detail = f"wrote {_ENTRY_ID} to {path} (replaced {removed} existing row(s))"
        else:
            detail = f"added {_ENTRY_ID} to {path}"
        return RegisterResult(RegisterStatus.REGISTERED, detail)

    def unregister_server(self, server_name: str) -> bool:
        path = self.patch_path
        if path is None:
            return False
        try:
            entries = _read_patch_for_write(path)
        except (_MalformedConfigError, OSError):
            return False
        kept = [e for e in entries if not _entry_matches(e, server_name)]
        if len(kept) == len(entries):
            return False
        try:
            _write_patch(path, kept)
        except OSError as exc:
            logger.warning("could not unregister %s from %s: %s", server_name, path, exc)
            return False
        return True
