"""Run commands on a remote host over SSH (non-interactive)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from mosk_rockoon_functional_agent import config as _cfg


def resolved_ssh_user(user: str) -> str:
    """Non-empty ``user`` wins; else ``SSH_REMOTE_USER`` from ``config.py``; else ``ubuntu``."""
    u = (user or "").strip()
    if u:
        return u
    return (getattr(_cfg, "SSH_REMOTE_USER", "") or "ubuntu").strip() or "ubuntu"


def split_ssh_options(ssh_options: str) -> list[str]:
    """Split extra OpenSSH flags (e.g. ``-p 2222`` or ``-o ProxyJump=bastion``) for argv insertion."""
    s = (ssh_options or "").strip()
    if not s:
        return []
    return shlex.split(s)


def _ssh_base(
    user: str,
    host: str,
    identity_file: str,
    *,
    connect_timeout: int = 30,
    ssh_options: str = "",
) -> list[str]:
    extra = split_ssh_options(ssh_options)
    return (
        ["ssh"]
        + extra
        + [
            "-o",
            f"ConnectTimeout={connect_timeout}",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-l",
            user,
            "-i",
            identity_file,
            host,
        ]
    )


def _wrap_remote_for_root_login(remote_command: str) -> str:
    """Match manual ``sudo -i`` then run steps: run the script inside ``sudo -i bash -lc``."""
    if not getattr(_cfg, "USE_SUDO_LOGIN_SHELL", True):
        return remote_command
    inner = shlex.quote(remote_command)
    return f"sudo -i bash -lc {inner}"


def ssh_run(
    user: str,
    host: str,
    identity_file: str,
    remote_command: str,
    *,
    ssh_options: str = "",
    timeout_seconds: int = 3600,
    connect_timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """
    Execute ``remote_command`` on the remote host.

    ``user``: SSH login; if empty, ``SSH_REMOTE_USER`` from ``config.py`` is used (default **ubuntu**).

    By default (see ``USE_SUDO_LOGIN_SHELL`` in ``config.py``), the command is wrapped as
    ``sudo -i bash -lc '<script>'`` so work runs in a **root** login context after SSH, matching
    ``sudo -i`` then clone/apt/tox on the test node. The outer ``bash -lc`` is still used as the
    non-interactive remote entrypoint.

    ``ssh_options``: extra ``ssh`` argv tokens (quoted string), e.g. ``-p 2222`` or ``-J bastion``.
    """
    ru = resolved_ssh_user(user)
    payload = _wrap_remote_for_root_login(remote_command)
    cmd = _ssh_base(ru, host, identity_file, connect_timeout=connect_timeout, ssh_options=ssh_options) + [
        f"bash -lc {shlex.quote(payload)}",
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def scp_upload(
    user: str,
    host: str,
    identity_file: str,
    local_path: Path,
    remote_path: str,
    *,
    ssh_options: str = "",
    timeout_seconds: int = 300,
    connect_timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    ru = resolved_ssh_user(user)
    dest = f"{ru}@{host}:{remote_path}"
    extra = split_ssh_options(ssh_options)
    cmd = (
        ["scp"]
        + extra
        + [
            "-o",
            f"ConnectTimeout={connect_timeout}",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-i",
            identity_file,
            str(local_path),
            dest,
        ]
    )
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
