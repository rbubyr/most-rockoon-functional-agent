"""
User-editable string defaults for the MCP server.

Edit this file for your environment, or pass tool arguments (identity_file, repo_url, hook_url,
gerrit_http_password) which override these values when non-empty.
"""

# Path to SSH private key on the machine running this MCP (Cursor host / stdio server).
SSH_IDENTITY_FILE = "/Users/rbubyr/.ssh/id_rsa"

# Remote SSH login on the test / MOSK node (``ssh -l <user>``). Used when a tool passes an empty user.
SSH_REMOTE_USER = "ubuntu"

# Rockoon ``git clone`` URL (Gerrit authenticated HTTPS, ``/a/`` project path).
ROCKOON_REPO_URL = "https://rbubyr@gerrit.mcp.mirantis.com/a/mcp/rockoon"

# Gerrit ``commit-msg`` hook (same as ``curl …/tools/hooks/commit-msg`` in your clone snippet).
ROCKOON_COMMIT_MSG_HOOK_URL = "https://gerrit.mcp.mirantis.com/tools/hooks/commit-msg"

# Gerrit HTTP password (Settings → HTTP Credentials in Gerrit). Required for non-interactive ``git clone``
# when ``ROCKOON_REPO_URL`` is ``https://…``: the MCP sends ``git -c http.extraHeader=Authorization: Basic …``.
# If the URL is ``ssh://…`` on Gerrit, the server maps it to ``https://user@host/a/…`` first when a password
# is set. You may set ``MOSK_ROCKOON_GERRIT_HTTP_PASSWORD`` in the MCP server env instead of this field.
# Do not commit real secrets.
gerrit_http_password = ""

# When true, every remote shell command runs as ``sudo -i bash -lc '<script>'`` (root login context on
# the test node), matching the manual ``sudo -i`` then clone/apt/tox flow. Set false only if you rely on
# the SSH user's kubeconfig without root equivalents.
USE_SUDO_LOGIN_SHELL = True
