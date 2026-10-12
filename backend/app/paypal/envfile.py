"""Reading and updating the repo-root `.env` file (used by the setup and smoke scripts)."""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from app.config import ENV_FILE, REPO_ROOT

EXAMPLE_FILE = REPO_ROOT / ".env.example"

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_SHOP_EMAIL = re.compile(r"^PAYPAL_SHOP_([A-Z0-9_]+)_EMAIL$")


def _format(value: str) -> str:
    if re.fullmatch(r"[^\s#\"'\\]*", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_env_text(text: str, updates: Mapping[str, str]) -> str:
    """Set `KEY=value` lines in place, keeping every comment and the order of the file.

    Keys the file doesn't have yet are added at the end.
    """
    remaining = dict(updates)
    lines = []
    for line in text.splitlines():
        match = _ASSIGNMENT.match(line)
        if match and match.group(1) in updates:
            key = match.group(1)
            lines.append(f"{key}={_format(updates[key])}")
            remaining.pop(key, None)
        else:
            lines.append(line)
    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(f"{key}={_format(value)}" for key, value in remaining.items())
    return "\n".join(lines) + "\n"


def write_env(path: Path, updates: Mapping[str, str]) -> None:
    """Apply `updates` to the file through a temporary file, readable only by its owner."""
    text = update_env_text(path.read_text(), updates)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    """The values set in the file. Empty ones count as unset."""
    if not path.exists():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v}


def ensure_env(path: Path = ENV_FILE, example: Path = EXAMPLE_FILE) -> bool:
    """Create `.env` from `.env.example` if it is missing, and give it a SECRET_KEY.

    Returns True if the file was created.
    """
    created = not path.exists()
    if created:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(example.read_text())
    if not read_env(path).get("SECRET_KEY"):
        write_env(path, {"SECRET_KEY": secrets.token_urlsafe(32)})
    return created


def adopt_smoke_vault(state: Mapping[str, Any], path: Path = ENV_FILE) -> str | None:
    """Give the PayPal saved by the smoke test to the shop whose owner approved it.

    The smoke test remembers the vault ID and the buyer's email. If that email is one of
    the `PAYPAL_SHOP_<CODE>_EMAIL` values and the shop has no vault ID yet, write it, so the
    demo can place that shop's holds. Returns the shop code if something was written.
    """
    vault_id, payer = state.get("vault_id"), state.get("payer_email")
    if not vault_id or not payer or not path.exists():
        return None
    values = read_env(path)
    for key, email in values.items():
        match = _SHOP_EMAIL.match(key)
        if not match or email.lower() != str(payer).lower():
            continue
        vault_key = f"PAYPAL_SHOP_{match.group(1)}_VAULT_ID"
        if values.get(vault_key):
            return None
        write_env(path, {vault_key: str(vault_id)})
        return match.group(1).lower().replace("_", "-")
    return None
