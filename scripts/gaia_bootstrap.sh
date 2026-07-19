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
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
  sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
  sudo apt update && sudo apt install gh -y
fi
echo "    -> now run: echo \"\$GH_TOKEN\" | gh auth login --with-token"
echo "       (needs repo + workflow scopes; used for issue queries and the final push)"

echo "==> Claude Code CLI"
if ! command -v claude >/dev/null; then
  npm install -g @anthropic-ai/claude-code
fi
echo "    -> put your key in the shell profile or a systemd EnvironmentFile, NOT in this repo:"
echo "       export ANTHROPIC_API_KEY=\"sk-ant-...\""

echo "==> Quarto"
if ! command -v quarto >/dev/null; then
  curl -fsSL https://quarto.org/download/latest/quarto-linux-amd64.deb -o /tmp/quarto.deb
  sudo dpkg -i /tmp/quarto.deb
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

cat <<'EOF'

Bootstrap done. Before running scripts/gaia_run_queue.sh:
  1. gh auth login (above)
  2. export ANTHROPIC_API_KEY=...
  3. Confirm push access: git -C "$REPO_DIR" push --dry-run origin main
EOF
