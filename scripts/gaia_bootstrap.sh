#!/usr/bin/env bash
# One-time setup on a fresh remote Linux box. Run once as the user that will
# own the automation (not root). Re-run is safe (idempotent-ish).
set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:gaia-hazlab/gwl-space-time-smooth.git}"
REPO_DIR="${REPO_DIR:-$HOME/gwl-space-time-smooth}"

echo "==> pixi (pinned env, matches CI)"
curl -fsSL https://pixi.sh/install.sh | bash
export PATH="$HOME/.pixi/bin:$PATH"

echo "==> gh CLI"
if ! command -v gh >/dev/null; then
  sudo install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo tee /usr/share/keyrings/githubcli-archive-keyring.gpg > /dev/null
  sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  sudo install -d -m 0755 /etc/apt/sources.list.d
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
  sudo apt update && sudo apt install gh -y
fi
echo "    -> now run: echo \"\$GH_TOKEN\" | gh auth login --with-token"
echo "       (needs repo + workflow scopes; used for issue queries and the final push)"

echo "==> Node.js (>=22, required by @anthropic-ai/claude-code)"
# A fresh box's SYSTEM node (apt's default `nodejs` package is often years out of date, e.g.
# v10/npm 6) is too old for the CLI's engine requirement and its global prefix is root-owned to
# boot. Rather than sudo apt install a newer nodejs (fights the system package manager) or sudo
# npm install -g (root ends up owning every future global install), use nvm: a user-owned,
# per-user Node that needs no sudo anywhere in this section.
node_major() { command -v node >/dev/null && node -e 'console.log(process.versions.node.split(".")[0])' || echo 0; }
if [ "$(node_major)" -lt 22 ]; then
  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] || curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  nvm install --lts
  nvm use --lts
fi

echo "==> Claude Code CLI"
if ! command -v claude >/dev/null; then
  npm install -g @anthropic-ai/claude-code
fi
echo "    -> put your key in the shell profile or a systemd EnvironmentFile, NOT in this repo:"
echo "       export ANTHROPIC_API_KEY=\"sk-ant-...\""

echo "==> Quarto"
if ! command -v quarto >/dev/null; then
  curl -fsSL https://quarto.org/download/latest/quarto-linux-amd64.deb -o /tmp/quarto.deb
  sudo dpkg -i /tmp/quarto.deb || sudo apt-get install -f -y   # pull in missing deps, then retry
fi

echo "==> Clone + build the pinned pixi env"
if [ ! -d "$REPO_DIR" ]; then
  git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"
pixi install --frozen

echo "==> Register + install the gaia agent plugin"
claude plugin marketplace add ./.claude/gaia
claude plugin install gaia@gaia

NODE_BIN_DIR="$(dirname "$(command -v node)")"
cat <<EOF

Bootstrap done. Before running scripts/gaia_run_queue.sh:
  1. gh auth login (above)
  2. export ANTHROPIC_API_KEY=...
  3. Confirm push access: git -C "$REPO_DIR" push --dry-run origin main
  4. If running unattended via cron (docs/gaia-automation.md): cron does not source
     .bashrc/.zshrc, so its minimal default PATH won't see pixi/gh/claude/quarto or
     nvm's node. Put an explicit PATH line in the crontab, e.g.:
       PATH=$NODE_BIN_DIR:$HOME/.pixi/bin:/usr/local/bin:/usr/bin:/bin
EOF
