---
name: mosk-rockoon-functional-remote
description: >-
  MOSK SSH setup for Rockoon functional tox (prefer standalone seed node test_srv): osh-system exporter
  NetworkPolicy ipBlock, apt, Gerrit mcp/rockoon clone, /var/lib/tests, tox -e functional. Use when the
  user mentions Rockoon functional tests on MOSK, test_srv, kubectl get networkpolicy exporter,
  rockoon-exporter-netpol, openstack-controller-exporter-netpol, or Gerrit mcp/rockoon over SSH.
---

# MOSK Rockoon functional (remote)

## Where to run (highly recommended)

Use a **standalone seed node**—commonly **`test_srv`** in lab topologies—as the **`host`** for SSH-based tools (apt, clone, tox). **Do not** default to the cluster **master** for heavy functional prep unless you have no alternative: a dedicated seed node isolates package churn, disk use, and long `tox` runs from control-plane and production-sensitive workloads.

## Relationship to Tempest

- **MOSK Tempest agent** (personal skill `mosk-tempest-agent`): OSDPL-driven **in-cluster** Tempest.
- **This skill**: **Rockoon** repo **`tox -e functional`** on a **node shell** over **SSH**, plus **remote kubectl** for exporter **NetworkPolicy** in **`osh-system`**.

Keep workflows separate.

## MCP tool order

1. **`remote_discover_exporter_netpols`** — Same discovery idea as on the node: **`kubectl -n osh-system get networkpolicy`** and pick rows whose **NAME** contains **`exporter`** (or run **`… | grep -i exporter`**). The tool defaults **`name_keyword=exporter`**, returns JSON **`candidates`** (plus a grep-sliced table), and includes **`pod_selector_match_labels`** when present. Example name: **`rockoon-exporter-netpol-openstack`** (`application=rockoon`, `component=exporter`). Pick an explicit **`policy_name`**; do not guess.
2. **`remote_netpol_preview_ipblock`** — review **`patch_body`** and **host** / **cidr** (always non-mutating; keep **`dry_run=true`**).
3. **`remote_netpol_apply_ipblock`** — use **`dry_run=true`** to re-preview without writes; apply with **`dry_run=false`** and **`confirm=true`** only after approval.
4. **`remote_apt_install_functional_prereqs`**
5. **`remote_clone_rockoon`** (`target_parent_dir`, optional fetch / destructive reset with **`confirm_reset`**)
6. **`remote_prepare_functional_dirs`**
7. **`remote_tox_functional`** — **`working_dir`** defaults to **`/home/<user>/rockoon`** when empty. Use **`recreate=true`** + **`confirm_recreate=true`** for `tox -r -e functional`.

Optional **`ssh_options`** on tools (e.g. `-J bastion`, `-p 2222`) for non-standard SSH paths.

Defaults for **SSH private key**, **remote login user** (**`SSH_REMOTE_USER`**, default **`ubuntu`**), and **Gerrit clone/hook URLs** live in **`src/mosk_rockoon_functional_agent/config.py`**; tool parameters override when provided.

Remote commands are executed as **`sudo -i bash -lc '…'`** by default (**`USE_SUDO_LOGIN_SHELL`** in **`config.py`**), matching the operator flow: SSH to the test node, **`sudo -i`**, then clone/apt/tox. If **`kubectl`** only works for the SSH user, set **`USE_SUDO_LOGIN_SHELL = false`** or fix root’s **`KUBECONFIG`** on the node.

Mutating tools require **explicit confirms** where the MCP schema says so. Cursor still needs **user approval** to run tools (org no-auto-run policy).

Lab check sequence: see project **README** section *Lab verification (plan)*.

## Verbatim manual (reference)

SSH:

```text
ssh -l ubuntu -i <ssh-key> <ip-of-node>
```

Then become root (the MCP tools wrap this automatically with ``sudo -i bash -lc`` when ``USE_SUDO_LOGIN_SHELL`` is true):

```text
sudo -i
```

Packages and clone:

```text
apt install python3.12 python3-pip
apt install tox
git clone "https://gerrit.mcp.mirantis.com/mcp/rockoon" && (cd "rockoon" && mkdir -p `git rev-parse --git-dir`/hooks/ && curl -Lo `git rev-parse --git-dir`/hooks/commit-msg https://gerrit.mcp.mirantis.com/tools/hooks/commit-msg && chmod +x `git rev-parse --git-dir`/hooks/commit-msg)
```

Discover exporter netpol **NAME** on the node (keyword **`exporter`**):

```text
kubectl -n osh-system get networkpolicy
kubectl -n osh-system get networkpolicy | grep -i exporter
```

NetworkPolicy: add under **`spec.ingress[].from`** (use exact **`metadata.name`** from the list above, e.g. **`rockoon-exporter-netpol-openstack`**):

```yaml
- ipBlock:
    cidr: 192.168.0.0/16
```

Tox:

```text
cd rockoon
tox -e functional
tox -e functional -- -k parallel
```

Recreate venv after env changes:

```text
tox -r -e functional
```

Build / header fixes (covered by **`remote_apt_install_functional_prereqs`** one-shot, or manually): `gcc`, `libc6-dev`, `linux-libc-dev`, `gcc-multilib`, `python3-dev`. Parallel log path: `/var/lib/tests/parallel/pytest.log`.

## Out of scope here

- Replacing SSH with an in-cluster Job for tox.
- Remote **vim** / **pdb** sessions — document only; operator runs interactively.
- Patching NetworkPolicies other than the exporter functional-test path chosen via discovery.
