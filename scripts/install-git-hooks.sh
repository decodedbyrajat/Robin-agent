#!/bin/sh
# Install Robin's git hooks into this clone. Run once after cloning:
#   sh scripts/install-git-hooks.sh
set -e
repo_root=$(git rev-parse --show-toplevel)
hooks_src="$repo_root/scripts/git-hooks"
hooks_dst=$(git rev-parse --git-path hooks)

for hook in "$hooks_src"/*; do
    name=$(basename "$hook")
    dst="$hooks_dst/$name"
    if [ -e "$dst" ] && ! grep -q "Robin pre-commit guard" "$dst" 2>/dev/null; then
        echo "⚠ $dst already exists and is not ours — not overwriting." >&2
        echo "  Chain it manually or remove it, then re-run this script." >&2
        continue
    fi
    cp "$hook" "$dst"
    chmod +x "$dst"
    echo "installed $name -> $dst"
done
