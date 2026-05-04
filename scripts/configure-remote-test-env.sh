#!/usr/bin/env bash
# Configure Rockoon functional-test style env on a remote MOSK/test node (apt, dirs, gerrit clone+hook).
# Run from your laptop:  ./scripts/configure-remote-test-env.sh 172.19.33.82
# Optional: SSH_IDENTITY_FILE=/path/to/key ./scripts/configure-remote-test-env.sh 172.19.33.82
set -euo pipefail

HOST="${1:?Usage: $0 <host> [path-to-ssh-private-key]}"
KEY="${2:-${SSH_IDENTITY_FILE:-$HOME/.ssh/id_rsa}}"
USER="${SSH_REMOTE_USER:-ubuntu}"

if [[ ! -f "$KEY" ]]; then
  echo "SSH key not found: $KEY" >&2
  exit 1
fi

REMOTE_SCRIPT=$(cat <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y python3.12 python3-pip tox gcc libc6-dev linux-libc-dev gcc-multilib python3-dev
mkdir -p /var/lib/tests/parallel && touch /var/lib/tests/parallel/pytest.log
chmod -R a+rwX /var/lib/tests || true
cd /home/ubuntu
if [[ ! -d rockoon ]]; then
  git clone https://gerrit.mcp.mirantis.com/mcp/rockoon
  (
    cd rockoon
    mkdir -p "$(git rev-parse --git-dir)/hooks/"
    curl -fsSL -o "$(git rev-parse --git-dir)/hooks/commit-msg" \
      https://gerrit.mcp.mirantis.com/tools/hooks/commit-msg
    chmod +x "$(git rev-parse --git-dir)/hooks/commit-msg"
  )
else
  echo "rockoon already exists under /home/ubuntu; skipping clone"
fi
echo "=== apt/clone/dirs done ==="
REMOTE
)

OUTER="sudo -i bash -lc $(printf '%q' "$REMOTE_SCRIPT")"

exec ssh -o BatchMode=yes -o ConnectTimeout=30 -o StrictHostKeyChecking=accept-new \
  -l "$USER" -i "$KEY" "$HOST" "bash -lc $(printf '%q' "$OUTER")"
