"""MCP server: Rockoon functional test environment on MOSK nodes (SSH + kubectl on remote)."""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlsplit, urlunsplit

from mcp.server.fastmcp import FastMCP

from mosk_rockoon_functional_agent import config as _cfg
from mosk_rockoon_functional_agent import netpol
from mosk_rockoon_functional_agent.ssh_remote import resolved_ssh_user, scp_upload, ssh_run

mcp = FastMCP("MOSK Rockoon functional agent")


def _effective_ssh_identity(identity_file_arg: str) -> str:
    return (identity_file_arg or "").strip() or (_cfg.SSH_IDENTITY_FILE or "").strip()


def _effective_repo_url(override: str) -> str:
    return (override or "").strip() or (_cfg.ROCKOON_REPO_URL or "").strip()


def _effective_hook_url(override: str) -> str:
    return (override or "").strip() or (_cfg.ROCKOON_COMMIT_MSG_HOOK_URL or "").strip()


def _effective_gerrit_http_password(override: str) -> str:
    if (override or "").strip():
        return override.strip()
    return (
        getattr(_cfg, "gerrit_http_password", "")
        or getattr(_cfg, "GERRIT_HTTP_PASSWORD", "")
        or (os.environ.get("MOSK_ROCKOON_GERRIT_HTTP_PASSWORD") or "")
        or ""
    ).strip()


def _ssh_username_from_rockoon_repo_url() -> str:
    m = re.match(r"(?i)^ssh://([^@/?#]+)@", (_cfg.ROCKOON_REPO_URL or "").strip())
    return (m.group(1) if m else "").strip()


def _gerrit_https_clone_url_from_ssh(ssh_url: str) -> str | None:
    """Map ``ssh://user@host:port/proj`` to ``https://user@host/a/proj`` for Gerrit HTTP password auth."""
    s = (ssh_url or "").strip()
    m = re.match(r"(?i)^ssh://([^@/?#]+)@([^/:?#]+)(?::\d+)?(/[^?#]*)?", s)
    if not m:
        return None
    gerrit_user = m.group(1).strip()
    host = m.group(2).strip()
    path = (m.group(3) or "").strip()
    if not path or path == "/":
        return None
    path_body = path.lstrip("/")
    if path_body.lower().startswith("a/"):
        https_path = "/" + path_body
    else:
        https_path = "/a/" + path_body
    return f"https://{quote(gerrit_user, safe='')}@{host}{https_path}"


def _maybe_ssh_to_https_for_http_password(repo: str, http_password: str) -> str:
    """When an HTTP password is configured, map Gerrit ``ssh://`` clone URL to ``https://…/a/…``."""
    pw = (http_password or "").strip()
    if not pw or not repo.lower().startswith("ssh://"):
        return repo
    https_repo = _gerrit_https_clone_url_from_ssh(repo)
    return https_repo if https_repo else repo


def _https_clone_username_and_clean_url(repo: str) -> tuple[str, str]:
    """Return ``(gerrit_username, https_url_without_password)`` for Basic auth."""
    parts = urlsplit(repo)
    if parts.scheme != "https":
        return "", repo
    netloc = parts.netloc
    if not netloc or netloc.startswith("["):
        return "", repo
    if "@" not in netloc:
        username = _ssh_username_from_rockoon_repo_url()
        if not username:
            return "", repo
        clean_netloc = f"{quote(username, safe='')}@{netloc}"
        return username, urlunsplit((parts.scheme, clean_netloc, parts.path, parts.query, parts.fragment))
    userinfo, hostport = netloc.rsplit("@", 1)
    if ":" in userinfo and not userinfo.startswith("["):
        username = userinfo.split(":", 1)[0]
    else:
        username = userinfo
    username = (username or "").strip() or _ssh_username_from_rockoon_repo_url()
    if not username:
        return "", repo
    clean_netloc = f"{quote(username, safe='')}@{hostport}"
    return username, urlunsplit((parts.scheme, clean_netloc, parts.path, parts.query, parts.fragment))


def _git_clone_shell_fragment(repo: str, http_password: str) -> str:
    """Remote shell fragment: ``git clone …`` using ``http.extraHeader`` when password is set (HTTPS)."""
    pw = (http_password or "").strip()
    parts = urlsplit(repo)
    if parts.scheme != "https" or not pw:
        return f"git clone {shlex.quote(repo)}"
    username, clean_url = _https_clone_username_and_clean_url(repo)
    if not username:
        return f"git clone {shlex.quote(repo)}"
    token = base64.b64encode(f"{username}:{pw}".encode()).decode("ascii")
    header = f"Authorization: Basic {token}"
    return f"git -c {shlex.quote(f'http.extraHeader={header}')} clone {shlex.quote(clean_url)}"


def _result(proc, *, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[-200_000:],
        "stderr": (proc.stderr or "")[-200_000:],
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, indent=2)


def _require_ssh(identity_resolved: str) -> str | None:
    if not identity_resolved.strip():
        return (
            "SSH identity is required: pass identity_file on the tool and/or set SSH_IDENTITY_FILE in "
            "mosk_rockoon_functional_agent/config.py"
        )
    return None


def _default_rockoon_workdir(user: str, working_dir: str) -> str:
    wd = (working_dir or "").strip()
    if wd:
        return wd
    return f"/home/{user}/rockoon"


def _netpol_preview_payload(
    host: str,
    user: str,
    identity_file: str,
    policy_name: str,
    namespace: str,
    cidr: str,
    connect_timeout: int,
    ssh_options: str,
) -> dict[str, Any]:
    iden = _effective_ssh_identity(identity_file)
    err = _require_ssh(iden)
    if err:
        return {"ok": False, "error": err}
    if not policy_name.strip():
        return {"ok": False, "error": "policy_name is required"}
    get_cmd = f"kubectl get networkpolicy {policy_name} -n {namespace} -o json"
    proc = ssh_run(
        user,
        host,
        iden,
        get_cmd,
        ssh_options=ssh_options,
        timeout_seconds=120,
        connect_timeout=connect_timeout,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "phase": "kubectl_get",
            "exit_code": proc.returncode,
            "stderr": proc.stderr,
            "stdout": (proc.stdout or "")[:8000],
            "host": host,
            "policy_name": policy_name,
            "namespace": namespace,
            "suggested_next_command": (
                f"ssh -l {shlex.quote(user)} -i <identity_file> {shlex.quote(host)} "
                f"'kubectl get networkpolicy -n {shlex.quote(namespace)} | grep -i exporter'"
            ),
        }
    doc, parse_err = netpol.summarize_netpol_for_tool(proc.stdout or "")
    if parse_err or not doc:
        return {
            "ok": False,
            "error": parse_err or "empty document",
            "phase": "parse",
            "suggested_next_command": (
                f"ssh -l {shlex.quote(user)} -i <identity_file> {shlex.quote(host)} "
                f"'kubectl get networkpolicy {shlex.quote(policy_name)} -n {shlex.quote(namespace)} -o yaml'"
            ),
        }
    spec = (doc.get("spec") or {}) if isinstance(doc, dict) else {}
    if not netpol.first_ingress_from_path(spec):
        return {
            "ok": False,
            "error": "spec.ingress[0].from is missing; edit manually or adjust Helm values",
            "phase": "validate",
            "suggested_next_command": (
                f"kubectl edit networkpolicy {policy_name} -n {namespace}   # on the SSH target node"
            ),
        }
    if netpol.ingress_from_has_cidr(spec, cidr):
        return {
            "ok": True,
            "skipped": True,
            "reason": f"ipBlock with cidr {cidr!r} already present under ingress[].from",
            "policy_name": policy_name,
            "namespace": namespace,
            "host": host,
            "cidr": cidr,
        }
    patch = netpol.build_add_ipblock_patch(cidr)
    return {
        "ok": True,
        "dry_run": True,
        "patch_type": "json",
        "patch_body": patch,
        "policy_name": policy_name,
        "namespace": namespace,
        "host": host,
        "cidr": cidr,
        "suggested_next_command": (
            "remote_netpol_apply_ipblock(..., dry_run=false, confirm=true) after operator review, "
            "or remote_netpol_apply_ipblock(..., dry_run=true) to re-preview without writing"
        ),
    }


@mcp.tool()
def remote_discover_exporter_netpols(
    host: Annotated[str, "SSH hostname or IP of MOSK master (or node with kubectl)"],
    user: Annotated[str, "SSH login user; default ubuntu (see SSH_REMOTE_USER in config.py)"] = "ubuntu",
    identity_file: Annotated[
        str,
        "Path to SSH private key on the MCP host; omit if SSH_IDENTITY_FILE is set in config.py",
    ] = "",
    namespace: Annotated[str, "Namespace for NetworkPolicies"] = "osh-system",
    name_keyword: Annotated[
        str,
        "Substring to match in NetworkPolicy **metadata.name** (case-insensitive); default **exporter** "
        "matches manual ``kubectl … get networkpolicy | grep exporter`` style discovery.",
    ] = "exporter",
    ssh_options: Annotated[
        str,
        "Extra ssh/scp argv tokens, e.g. '-p 2222' or '-J bastion' (shell-quoted string)",
    ] = "",
    connect_timeout: Annotated[int, "SSH connect timeout seconds"] = 30,
) -> str:
    """
    Over SSH: ``kubectl get networkpolicy -n <namespace>`` (table, **-o wide**, JSON). **Candidates** are
    policies whose **NAME** contains ``name_keyword`` (default **exporter**), same idea as:

    ``kubectl -n osh-system get networkpolicy | grep exporter``

    Example row: ``rockoon-exporter-netpol-openstack`` with pod selector ``application=rockoon``,
    ``component=exporter``.
    """
    iden = _effective_ssh_identity(identity_file)
    err = _require_ssh(iden)
    if err:
        return json.dumps({"ok": False, "error": err}, indent=2)
    cmd_json = f"kubectl get networkpolicy -n {namespace} -o json"
    proc = ssh_run(
        user,
        host,
        iden,
        cmd_json,
        ssh_options=ssh_options,
        timeout_seconds=120,
        connect_timeout=connect_timeout,
    )
    if proc.returncode != 0:
        return _result(
            proc,
            extra={
                "ok": False,
                "phase": "kubectl_json",
                "suggested_next_command": f"Verify kubectl on remote: ssh … '{cmd_json}'",
            },
        )
    doc, parse_err = netpol.summarize_netpol_for_tool(proc.stdout or "")
    if parse_err:
        return json.dumps({"ok": False, "error": parse_err, "raw": (proc.stdout or "")[:4000]}, indent=2)
    nk = (name_keyword or "exporter").strip() or "exporter"
    candidates = netpol.list_exporter_candidate_netpols(doc or {}, name_keyword=nk)
    ns_q = shlex.quote(namespace)
    cmd_grep = (
        f"kubectl get networkpolicy -n {ns_q} 2>/dev/null | grep -i {shlex.quote(nk)} || true"
    )
    grep_proc = ssh_run(
        user,
        host,
        iden,
        cmd_grep,
        ssh_options=ssh_options,
        timeout_seconds=60,
        connect_timeout=connect_timeout,
    )
    cmd_wide = f"kubectl get networkpolicy -n {namespace} -o wide"
    tbl_wide = ssh_run(
        user,
        host,
        iden,
        cmd_wide,
        ssh_options=ssh_options,
        timeout_seconds=60,
        connect_timeout=connect_timeout,
    )
    cmd_list = f"kubectl get networkpolicy -n {namespace}"
    tbl = ssh_run(
        user,
        host,
        iden,
        cmd_list,
        ssh_options=ssh_options,
        timeout_seconds=60,
        connect_timeout=connect_timeout,
    )
    return json.dumps(
        {
            "ok": True,
            "host": host,
            "namespace": namespace,
            "name_keyword": nk,
            "discovery_note": (
                "Policies are selected when NAME contains the keyword (default: exporter). "
                "See kubectl_grep_keyword_stdout for a table slice matching: "
                f"kubectl -n {namespace} get networkpolicy | grep -i {nk!r}"
            ),
            "candidates": candidates,
            "kubectl_grep_keyword_command": cmd_grep,
            "kubectl_grep_keyword_stdout": (grep_proc.stdout or "").strip(),
            "kubectl_grep_keyword_exit_code": grep_proc.returncode,
            "kubectl_list_wide_stdout": (tbl_wide.stdout or "").strip(),
            "kubectl_list_wide_exit_code": tbl_wide.returncode,
            "kubectl_list_stdout": (tbl.stdout or "").strip(),
            "kubectl_list_exit_code": tbl.returncode,
        },
        indent=2,
    )


@mcp.tool()
def remote_netpol_preview_ipblock(
    host: Annotated[str, "SSH hostname or IP"],
    user: Annotated[str, "SSH login user; default ubuntu (see SSH_REMOTE_USER in config.py)"] = "ubuntu",
    identity_file: Annotated[
        str,
        "Path to SSH private key; omit if SSH_IDENTITY_FILE is set in config.py",
    ] = "",
    policy_name: Annotated[
        str,
        "Exact NetworkPolicy metadata.name (e.g. from kubectl get netpol | grep exporter, or candidates list)",
    ] = "",
    namespace: Annotated[str, "NetworkPolicy namespace"] = "osh-system",
    cidr: Annotated[str, "CIDR for ipBlock, e.g. 192.168.0.0/16"] = "192.168.0.0/16",
    dry_run: Annotated[
        bool,
        "When true (default), return JSON patch only (no cluster writes). Same as apply with dry_run=true.",
    ] = True,
    ssh_options: Annotated[str, "Extra ssh argv tokens (see remote_discover_exporter_netpols)"] = "",
    connect_timeout: Annotated[int, "SSH connect timeout seconds"] = 30,
) -> str:
    """
    Compute a JSON patch that adds ``ipBlock: {cidr}`` to ``spec.ingress[0].from`` (append ``-``).
    Does not mutate the cluster. Duplicate **ipBlock.cidr** under any **ingress[].from** → skip.
    """
    if not dry_run:
        return json.dumps(
            {
                "ok": False,
                "error": "preview is always non-mutating; keep dry_run=true or use remote_netpol_apply_ipblock(dry_run=true)",
            },
            indent=2,
        )
    payload = _netpol_preview_payload(
        host, user, identity_file, policy_name, namespace, cidr, connect_timeout, ssh_options
    )
    return json.dumps(payload, indent=2)


@mcp.tool()
def remote_netpol_apply_ipblock(
    host: Annotated[str, "SSH hostname or IP"],
    user: Annotated[str, "SSH login user; default ubuntu (see SSH_REMOTE_USER in config.py)"] = "ubuntu",
    identity_file: Annotated[
        str,
        "Path to SSH private key; omit if SSH_IDENTITY_FILE is set in config.py",
    ] = "",
    policy_name: Annotated[
        str,
        "Exact NetworkPolicy metadata.name (e.g. rockoon-exporter-netpol-openstack from discovery)",
    ] = "",
    namespace: Annotated[str, "NetworkPolicy namespace"] = "osh-system",
    cidr: Annotated[str, "CIDR for ipBlock"] = "192.168.0.0/16",
    dry_run: Annotated[
        bool,
        "When true, return the same payload as preview (no kubectl patch). When false, require confirm=true to patch.",
    ] = False,
    confirm: Annotated[
        bool,
        "Must be true when dry_run is false to apply a patch. Responses include host, policy_name, cidr.",
    ] = False,
    ssh_options: Annotated[str, "Extra ssh/scp argv tokens"] = "",
    connect_timeout: Annotated[int, "SSH connect timeout seconds"] = 30,
) -> str:
    """
    Apply JSON patch via ``kubectl patch --type=json`` on the **remote** host, or preview only when
    ``dry_run=true``. When ``dry_run=false``, requires ``confirm=true`` after operator review.
    """
    iden = _effective_ssh_identity(identity_file)
    preview = _netpol_preview_payload(
        host, user, identity_file, policy_name, namespace, cidr, connect_timeout, ssh_options
    )
    if dry_run:
        preview["tool_note"] = "dry_run mode: no kubectl patch executed"
        return json.dumps(preview, indent=2)

    if not confirm:
        return json.dumps(
            {
                "ok": False,
                "error": "confirm must be true when dry_run is false",
                "host": host,
                "policy_name": policy_name,
                "namespace": namespace,
                "cidr": cidr,
                "suggested_next_command": "remote_netpol_apply_ipblock(..., dry_run=true) to preview, then confirm=true",
            },
            indent=2,
        )
    if not preview.get("ok"):
        return json.dumps(preview, indent=2)
    if preview.get("skipped"):
        return json.dumps(preview, indent=2)
    patch = preview.get("patch_body")
    if not patch:
        return json.dumps({"ok": False, "error": "no patch_body from preview", "preview": preview}, indent=2)

    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in policy_name)
    remote_patch = f"/tmp/mcp_rfa_netpol_{safe}.json"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        tmp.write(json.dumps(patch))
        local_path = Path(tmp.name)
    try:
        up = scp_upload(
            user,
            host,
            iden,
            local_path,
            remote_patch,
            ssh_options=ssh_options,
            timeout_seconds=120,
        )
        if up.returncode != 0:
            return _result(
                up,
                extra={
                    "ok": False,
                    "phase": "scp_patch",
                    "host": host,
                    "policy_name": policy_name,
                    "suggested_next_command": "Check ssh_options / disk space on remote /tmp",
                },
            )
        patch_cmd = (
            f"kubectl patch networkpolicy {policy_name} -n {namespace} "
            f"--type=json --patch-file={remote_patch} && rm -f {remote_patch}"
        )
        patched = ssh_run(
            user,
            host,
            iden,
            patch_cmd,
            ssh_options=ssh_options,
            timeout_seconds=120,
            connect_timeout=connect_timeout,
        )
        return _result(
            patched,
            extra={
                "ok": patched.returncode == 0,
                "phase": "kubectl_patch",
                "host": host,
                "policy_name": policy_name,
                "namespace": namespace,
                "cidr": cidr,
                "suggested_next_command": (
                    f"ssh … 'kubectl get networkpolicy {policy_name} -n {namespace} -o yaml' | grep -A2 ipBlock"
                ),
            },
        )
    finally:
        local_path.unlink(missing_ok=True)


@mcp.tool()
def remote_apt_install_functional_prereqs(
    host: Annotated[str, "SSH hostname or IP"],
    user: Annotated[str, "SSH login user; default ubuntu (see SSH_REMOTE_USER in config.py)"] = "ubuntu",
    identity_file: Annotated[
        str,
        "Path to SSH private key; omit if SSH_IDENTITY_FILE is set in config.py",
    ] = "",
    ssh_options: Annotated[str, "Extra ssh argv tokens"] = "",
    connect_timeout: Annotated[int, "SSH connect timeout seconds"] = 30,
) -> str:
    """
    One-shot ``apt-get install`` for functional tox: ``python3.12``, ``python3-pip``, ``tox``, and the
    documented native-build chain ``gcc``, ``libc6-dev``, ``linux-libc-dev``, ``gcc-multilib``, ``python3-dev``.
    """
    iden = _effective_ssh_identity(identity_file)
    err = _require_ssh(iden)
    if err:
        return json.dumps({"ok": False, "error": err}, indent=2)
    script = (
        "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
        "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "
        "python3.12 python3-pip tox gcc libc6-dev linux-libc-dev gcc-multilib python3-dev"
    )
    proc = ssh_run(
        user,
        host,
        iden,
        script,
        ssh_options=ssh_options,
        timeout_seconds=3600,
        connect_timeout=connect_timeout,
    )
    return _result(proc, extra={"ok": proc.returncode == 0, "host": host})


@mcp.tool()
def remote_clone_rockoon(
    host: Annotated[str, "SSH hostname or IP"],
    user: Annotated[str, "SSH login user; default ubuntu (see SSH_REMOTE_USER in config.py)"] = "ubuntu",
    identity_file: Annotated[
        str,
        "Path to SSH private key; omit if SSH_IDENTITY_FILE is set in config.py",
    ] = "",
    target_parent_dir: Annotated[str, "Remote directory where ``rockoon/`` is created"] = "",
    repo_url: Annotated[
        str,
        "Override Rockoon clone URL; omit to use ROCKOON_REPO_URL from config.py",
    ] = "",
    hook_url: Annotated[
        str,
        "Override commit-msg hook URL; omit to use ROCKOON_COMMIT_MSG_HOOK_URL from config.py",
    ] = "",
    gerrit_http_password: Annotated[
        str,
        "Gerrit HTTP password; omit to use gerrit_http_password from config.py",
    ] = "",
    git_fetch_if_exists: Annotated[
        bool,
        "If true and ``rockoon`` already exists, run ``git -C rockoon fetch --all`` (no reset).",
    ] = False,
    reset_hard: Annotated[
        bool,
        "If true, run ``git reset --hard`` to match remote default branch (destructive).",
    ] = False,
    confirm_reset: Annotated[
        bool,
        "Must be true when reset_hard is true (safety).",
    ] = False,
    ssh_options: Annotated[str, "Extra ssh argv tokens"] = "",
    connect_timeout: Annotated[int, "SSH connect timeout seconds"] = 30,
) -> str:
    """
    Clone the configured Gerrit ``mcp/rockoon`` repo and install the ``commit-msg`` hook (URLs from
    ``config.py`` / tool overrides; defaults match the MOSK functional manual).
    If ``rockoon`` exists: skip clone by default; optional ``git_fetch_if_exists``; optional destructive reset
    with ``reset_hard`` + ``confirm_reset``.
    """
    iden = _effective_ssh_identity(identity_file)
    err = _require_ssh(iden)
    if err:
        return json.dumps({"ok": False, "error": err}, indent=2)
    if not target_parent_dir.strip():
        return json.dumps({"ok": False, "error": "target_parent_dir is required"}, indent=2)
    if reset_hard and not confirm_reset:
        return json.dumps(
            {
                "ok": False,
                "error": "confirm_reset must be true when reset_hard is true",
                "host": host,
                "suggested_next_command": "remote_clone_rockoon(..., confirm_reset=true) if reset is intended",
            },
            indent=2,
        )
    http_pw = _effective_gerrit_http_password(gerrit_http_password)
    repo = _effective_repo_url(repo_url)
    repo = _maybe_ssh_to_https_for_http_password(repo, http_pw)
    clone_cmd = _git_clone_shell_fragment(repo, http_pw)
    hook = _effective_hook_url(hook_url)
    hq = shlex.quote(hook)
    parent = shlex.quote(target_parent_dir)
    fetch_part = "git fetch --all" if git_fetch_if_exists else ":"
    reset_part = "git reset --hard" if reset_hard else ":"
    script = (
        f"set -euo pipefail; cd {parent}; "
        f"if [ -d rockoon ]; then "
        f"  cd rockoon && {fetch_part} && {reset_part}; "
        f"  echo 'rockoon directory existed; fetch/reset per flags'; "
        f"  exit 0; "
        f"fi; "
        f"export GIT_TERMINAL_PROMPT=0; "
        f"{clone_cmd} && (cd rockoon && mkdir -p \"$(git rev-parse --git-dir)/hooks/\" && "
        f"curl -Lo \"$(git rev-parse --git-dir)/hooks/commit-msg\" {hq} && "
        f"chmod +x \"$(git rev-parse --git-dir)/hooks/commit-msg\")"
    )
    proc = ssh_run(
        user,
        host,
        iden,
        script,
        ssh_options=ssh_options,
        timeout_seconds=3600,
        connect_timeout=connect_timeout,
    )
    return _result(
        proc,
        extra={
            "ok": proc.returncode == 0,
            "host": host,
            "gerrit_http_auth_configured": bool(http_pw),
        },
    )


@mcp.tool()
def remote_prepare_functional_dirs(
    host: Annotated[str, "SSH hostname or IP"],
    user: Annotated[str, "SSH login user; default ubuntu (see SSH_REMOTE_USER in config.py)"] = "ubuntu",
    identity_file: Annotated[
        str,
        "Path to SSH private key; omit if SSH_IDENTITY_FILE is set in config.py",
    ] = "",
    ssh_options: Annotated[str, "Extra ssh argv tokens"] = "",
    connect_timeout: Annotated[int, "SSH connect timeout seconds"] = 30,
) -> str:
    """``mkdir -p /var/lib/tests/parallel`` and ``touch /var/lib/tests/parallel/pytest.log`` (sudo)."""
    iden = _effective_ssh_identity(identity_file)
    err = _require_ssh(iden)
    if err:
        return json.dumps({"ok": False, "error": err}, indent=2)
    script = (
        "sudo mkdir -p /var/lib/tests/parallel && "
        "sudo touch /var/lib/tests/parallel/pytest.log && "
        "sudo chmod -R a+rwX /var/lib/tests || true"
    )
    proc = ssh_run(
        user,
        host,
        iden,
        script,
        ssh_options=ssh_options,
        timeout_seconds=120,
        connect_timeout=connect_timeout,
    )
    return _result(proc, extra={"ok": proc.returncode == 0, "host": host})


@mcp.tool()
def remote_tox_functional(
    host: Annotated[str, "SSH hostname or IP"],
    user: Annotated[str, "SSH login user; default ubuntu (see SSH_REMOTE_USER in config.py)"] = "ubuntu",
    identity_file: Annotated[
        str,
        "Path to SSH private key; omit if SSH_IDENTITY_FILE is set in config.py",
    ] = "",
    working_dir: Annotated[
        str,
        "Remote rockoon repo root (tox.ini). If empty, defaults to /home/<user>/rockoon",
    ] = "",
    tox_extra_args: Annotated[str, "Args after ``tox ... --``, e.g. ``-k parallel``"] = "",
    recreate: Annotated[bool, "If true, run ``tox -r -e functional`` (recreates virtualenvs)"] = False,
    confirm_recreate: Annotated[bool, "Must be true when recreate is true (safety)."] = False,
    ssh_options: Annotated[str, "Extra ssh argv tokens"] = "",
    connect_timeout: Annotated[int, "SSH connect timeout seconds"] = 30,
) -> str:
    """
    Run ``tox -e functional`` under ``working_dir`` (default ``/home/<user>/rockoon``). Long runs may hit MCP
    timeouts; use narrow ``-k`` or tmux on the node. Output is capped in the JSON stdout field.
    """
    iden = _effective_ssh_identity(identity_file)
    err = _require_ssh(iden)
    if err:
        return json.dumps({"ok": False, "error": err}, indent=2)
    wd = _default_rockoon_workdir(resolved_ssh_user(user), working_dir)
    if recreate and not confirm_recreate:
        return json.dumps(
            {
                "ok": False,
                "error": "confirm_recreate must be true when recreate is true",
                "host": host,
                "working_dir": wd,
                "suggested_next_command": "remote_tox_functional(..., confirm_recreate=true) if venv recreate is intended",
            },
            indent=2,
        )
    r = "-r " if recreate else ""
    extra = tox_extra_args.strip()
    tox_cmd = f"tox {r}-e functional"
    if extra:
        tox_cmd += f" -- {extra}"
    script = f"set -euo pipefail; cd {shlex.quote(wd)}; {tox_cmd}"
    proc = ssh_run(
        user,
        host,
        iden,
        script,
        ssh_options=ssh_options,
        timeout_seconds=7200,
        connect_timeout=connect_timeout,
    )
    return _result(
        proc,
        extra={
            "ok": proc.returncode == 0,
            "host": host,
            "working_dir": wd,
            "remote_command": tox_cmd,
            "suggested_next_command": "On failure: remote_apt_install_functional_prereqs then remote_prepare_functional_dirs; re-run with narrow tox_extra_args=-k <id>",
        },
    )
