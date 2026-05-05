# MOSK Rockoon functional agent (MCP)

Python MCP server for the **remote MOSK node** workflow: non-interactive **SSH** to a **kubectl-capable** host (see deployment recommendation below), **kubectl** NetworkPolicy patch for exporter ingress **ipBlock**, **apt** prerequisites for `tox -e functional`, **clone** `mcp/rockoon` with the Gerrit hook, **`/var/lib/tests`** layout, and optional **`remote_tox_functional`**.

**Deployment recommendation:** It is **highly recommended** to use a **standalone seed node** (often named **`test_srv`** in lab layouts) as the SSH target for package installs, the Rockoon clone, and `tox` runs. That keeps functional-test prep and CPU/disk load off the **cluster master** and other control-plane or customer-critical nodes, and gives you a disposable environment that matches how many teams run MOSK QA.

## Install

```bash
cd /path/to/mosk-rockoon-functional-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Configuration (`config.py`)

Edit **[`src/mosk_rockoon_functional_agent/config.py`](src/mosk_rockoon_functional_agent/config.py)** (tracked in git with safe defaults):

| Constant | Meaning |
|----------|--------|
| **`SSH_IDENTITY_FILE`** | Default path to the **private key on the MCP host** (same as passing `identity_file` on each tool). |
| **`SSH_REMOTE_USER`** | Remote **``ssh -l``** login; default **`ubuntu`**. Used when a tool is called with an empty **`user`** argument. |
| **`ROCKOON_REPO_URL`** | `git clone` URL for Rockoon (default: Gerrit authenticated HTTPS `/a/…`; set **`gerrit_http_password`** for non-interactive clone). |
| **`ROCKOON_COMMIT_MSG_HOOK_URL`** | URL for the Gerrit `commit-msg` hook. |
| **`gerrit_http_password`** | Gerrit HTTP password for HTTPS clones: the server runs `git -c http.extraHeader='Authorization: Basic …' clone …` (no password in the URL). If the effective URL is Gerrit `ssh://…`, it is mapped to `https://<user>@<host>/a/<project>` when a password is set. Legacy **`GERRIT_HTTP_PASSWORD`** in a local `config.py` is still read if this is empty. Alternatively set env **`MOSK_ROCKOON_GERRIT_HTTP_PASSWORD`** on the MCP server process (see Cursor MCP server `env`). |
| **`USE_SUDO_LOGIN_SHELL`** | When **true** (default), remote commands run as **`sudo -i bash -lc '…'`** so clone/apt/tox/kubectl match the manual **root** session after SSH. Set **false** if you must stay the SSH user (e.g. only that user has `kubectl` kubeconfig). |

Non-empty tool arguments still override: **`identity_file`**, **`repo_url`**, **`hook_url`**, **`gerrit_http_password`** on **`remote_clone_rockoon`**.


## Cursor MCP config

See [agent/mcp.json](agent/mcp.json) and adjust paths.

## Tools (plan-aligned)

| Tool | Purpose |
|------|---------|
| `remote_discover_exporter_netpols` | JSON + **`-o wide`** + table + **`grep -i <keyword>`** slice; **`name_keyword`** defaults to **`exporter`** (matches **NAME** like `rockoon-exporter-netpol-openstack`) |
| `remote_netpol_preview_ipblock` | JSON patch body only (`dry_run` must stay **true**); duplicate CIDR → no-op |
| `remote_netpol_apply_ipblock` | **`dry_run=true`**: same as preview; **`dry_run=false`**: needs **`confirm=true`** + `kubectl patch --type=json` |
| `remote_apt_install_functional_prereqs` | `python3.12`, `pip`, `tox`, `gcc`, headers, `python3-dev` in one shot |
| `remote_clone_rockoon` | Gerrit clone + hook (URLs from **`config.py`** or **`repo_url`** / **`hook_url`** overrides); optional fetch / `reset_hard` + **`confirm_reset`** |
| `remote_prepare_functional_dirs` | `/var/lib/tests/parallel` + `pytest.log` |
| `remote_tox_functional` | `tox [-r] -e functional`; **`working_dir`** defaults to **`/home/<user>/rockoon`** if empty |

Optional on all SSH tools: **`ssh_options`** — extra OpenSSH tokens (e.g. `-p 2222`, `-J bastion`).

## Finding the exporter NetworkPolicy

On a node with **`kubectl`**, list policies in **`osh-system`** and spot the functional-test exporter netpol by the **`exporter`** substring in **NAME** (same idea as piping through **`grep exporter`**):

```bash
kubectl -n osh-system get networkpolicy
kubectl -n osh-system get networkpolicy | grep -i exporter
```

Example (names and selectors vary by release):

```text
NAME                                 POD-SELECTOR
rockoon-exporter-netpol-openstack    application=rockoon,component=exporter
```

**`remote_discover_exporter_netpols`** applies the same rule in JSON: **`candidates`** are policies whose **`metadata.name`** contains **`name_keyword`** (default **`exporter`**), so both **`rockoon-exporter-netpol-openstack`** and **`openstack-controller-exporter-netpol-openstack`** match. Never patch until you pass an explicit **`policy_name`** from that list (or operator choice).

## Safety

- **`remote_netpol_apply_ipblock`**: use **`dry_run=true`** to preview; set **`dry_run=false`** and **`confirm=true`** only after review.
- **`remote_tox_functional`**: **`recreate=true`** requires **`confirm_recreate=true`**.
- **`remote_clone_rockoon`**: **`reset_hard=true`** requires **`confirm_reset=true`**.
- Responses echo **host**, **policy_name**, **cidr** where relevant; never log private key material.

## Lab verification (plan)

1. **Discover**: run **`remote_discover_exporter_netpols`** (default **`name_keyword=exporter`**); confirm **`candidates`** / **`kubectl_grep_keyword_stdout`** shows the exporter netpol for your MOSK version (e.g. `rockoon-exporter-netpol-openstack`).
2. **Dry-run patch**: **`remote_netpol_preview_ipblock`** (or **`remote_netpol_apply_ipblock`** with **`dry_run=true`**) for the chosen **`policy_name`**; inspect **`patch_body`** / skip reason.
3. **Apply**: **`remote_netpol_apply_ipblock`** with **`dry_run=false`**, **`confirm=true`**; on the node, `kubectl get networkpolicy -n osh-system <name> -o yaml` shows the new **`ipBlock`** under **`spec.ingress[].from`**.
4. **Tox smoke**: after **`remote_apt_install_functional_prereqs`**, **`remote_clone_rockoon`**, **`remote_prepare_functional_dirs`**, run **`remote_tox_functional`** with **`tox_extra_args`** like `-k <single_test>`; expect **`exit_code`** 0 and **`/var/lib/tests/parallel/pytest.log`** present on the node.
