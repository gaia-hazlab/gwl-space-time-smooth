#!/usr/bin/env bash
# One-time setup on a fresh remote Linux box. Run once as the user that will
# own the automation (not root). Re-run is safe (idempotent-ish).
set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:gaia-hazlab/gwl-space-time-smooth.git}"
REPO_DIR="${REPO_DIR:-$HOME/gwl-space-time-smooth}"

# gh and Quarto below install as portable, per-user tarballs into ~/.local -- no apt/dnf/pacman,
# no sudo, no assumption about which package manager (or whether one) is on the box. This is the
# same "user-owned, no sudo" reasoning as the pixi/nvm installs.
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"
export PATH="$LOCAL_BIN:$PATH"
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  [ -f "$rc" ] && ! grep -qF '.local/bin' "$rc" && echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
done

# uname -m -> the arch suffix gh/Quarto's release assets use.
case "$(uname -m)" in
  x86_64|amd64) PKG_ARCH=amd64 ;;
  aarch64|arm64) PKG_ARCH=arm64 ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

echo "==> pixi (pinned env, matches CI)"
curl -fsSL https://pixi.sh/install.sh | bash
export PATH="$HOME/.pixi/bin:$PATH"

echo "==> gh CLI"
if ! command -v gh >/dev/null; then
  GH_TARBALL_URL=$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest \
    | grep -o "https://[^\"]*linux_${PKG_ARCH}\.tar\.gz" | head -1)
  [ -n "$GH_TARBALL_URL" ] || { echo "Could not find a gh release asset for linux_${PKG_ARCH}" >&2; exit 1; }
  curl -fsSL "$GH_TARBALL_URL" -o /tmp/gh.tar.gz
  rm -rf /tmp/gh-extract && mkdir -p /tmp/gh-extract
  tar -xzf /tmp/gh.tar.gz -C /tmp/gh-extract --strip-components=1
  install -m 0755 /tmp/gh-extract/bin/gh "$LOCAL_BIN/gh"
  rm -rf /tmp/gh.tar.gz /tmp/gh-extract
fi
echo "    -> now run: echo \"\$GH_TOKEN\" | gh auth login --with-token"
echo "       (needs repo + workflow scopes; used for issue queries and the final push)"

echo "==> Node.js (>=22, required by @anthropic-ai/claude-code)"
# A fresh box's SYSTEM node (apt's default `nodejs` package is often years out of date, e.g.
# v10/npm 6) is too old for the CLI's engine requirement, and even a new-enough system node's
# global npm prefix is often root-owned. Rather than sudo apt install a newer nodejs (fights the
# system package manager) or sudo npm install -g (root ends up owning every future global
# install), use nvm: a user-owned, per-user Node that needs no sudo anywhere in this section.
# `nvm install --lts` is NOT pinned to 22 -- it tracks whatever the current LTS is, which can
# drift below 22 over time -- so pin the major explicitly instead.
NODE_MIN_MAJOR=22
node_major() { command -v node >/dev/null && node -e 'console.log(process.versions.node.split(".")[0])' || echo 0; }
npm_prefix_writable() { command -v npm >/dev/null && [ -w "$(npm config get prefix)/lib" ] 2>/dev/null; }
if [ "$(node_major)" -lt "$NODE_MIN_MAJOR" ] || ! npm_prefix_writable; then
  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] || curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  nvm install "$NODE_MIN_MAJOR"
  nvm use "$NODE_MIN_MAJOR"
fi

echo "==> Claude Code CLI"
if ! command -v claude >/dev/null; then
  npm install -g @anthropic-ai/claude-code
fi
echo "    -> put your key in the shell profile or a systemd EnvironmentFile, NOT in this repo:"
echo "       export ANTHROPIC_API_KEY=\"sk-ant-...\""

echo "==> Quarto"
if ! command -v quarto >/dev/null; then
  curl -fsSL "https://quarto.org/download/latest/quarto-linux-${PKG_ARCH}.tar.gz" -o /tmp/quarto.tar.gz
  rm -rf "$HOME/.local/quarto" && mkdir -p "$HOME/.local/quarto"
  tar -xzf /tmp/quarto.tar.gz -C "$HOME/.local/quarto" --strip-components=1
  ln -sf "$HOME/.local/quarto/bin/quarto" "$LOCAL_BIN/quarto"
  rm -f /tmp/quarto.tar.gz
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

NODE_BIN_DIR="$(dirname "$(command -v node)" 2>/dev/null || true)"
cat <<EOF

Bootstrap done. Before running scripts/gaia_run_queue.sh:
  1. gh auth login (above)
  2. export ANTHROPIC_API_KEY=...
  3. Confirm push access: git -C "$REPO_DIR" push --dry-run origin main
  4. If running unattended via cron (docs/gaia-automation.md): cron does not source
     .bashrc/.zshrc, so its minimal default PATH won't see anything this script
     installed (pixi, gh, quarto, and nvm's node/claude are all per-user, not system
     paths). Put an explicit PATH line in the crontab, e.g.:
       PATH=${NODE_BIN_DIR:-\$HOME/.nvm/versions/node/*/bin}:$HOME/.pixi/bin:$LOCAL_BIN:/usr/local/bin:/usr/bin:/bin
EOF
