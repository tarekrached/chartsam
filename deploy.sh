#!/usr/bin/env bash
# deploy.sh — Push public/ (including tiles) to the gh-pages branch.
#
# Run after regenerating tiles:
#   export PATH=/opt/homebrew/bin:$PATH
#   gdal2tiles.py --xyz --tilesize=512 -z 5-13 -r bilinear \
#     --tiledriver=JPEG --processes=4 chart_mercator_crop.tif public/tiles/
#   python3 scripts/write_manifest.py
#   ./deploy.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PUBLIC_DIR="$REPO_ROOT/public"
WORKTREE_DIR="$REPO_ROOT/.gh-pages-worktree"

echo "▶ Checking tiles exist..."
tile_count=$(find "$PUBLIC_DIR/tiles" -name "*.jpg" 2>/dev/null | wc -l | tr -d ' ')
if [ "$tile_count" -eq 0 ]; then
  echo "ERROR: No tiles found in public/tiles/. Regenerate them first."
  exit 1
fi
echo "  Found $tile_count tiles."

echo "▶ Preparing gh-pages worktree..."
# Remove any stale worktree
if [ -d "$WORKTREE_DIR" ]; then
  git worktree remove --force "$WORKTREE_DIR" 2>/dev/null || true
fi

# Create or switch to gh-pages branch
if git show-ref --quiet refs/heads/gh-pages; then
  git worktree add "$WORKTREE_DIR" gh-pages
else
  # Create orphan gh-pages branch (no history), then attach worktree
  git checkout --orphan gh-pages
  git reset --hard
  git commit --allow-empty -m "Init gh-pages"
  git checkout main
  git worktree add "$WORKTREE_DIR" gh-pages
fi

echo "▶ Syncing public/ into worktree..."
# Clear worktree contents (keep .git)
find "$WORKTREE_DIR" -mindepth 1 -not -name '.git' -not -path '*/.git/*' -delete 2>/dev/null || true

# Copy everything from public/ including tiles
cp -r "$PUBLIC_DIR"/. "$WORKTREE_DIR/"

echo "▶ Committing..."
cd "$WORKTREE_DIR"
git add -A
if git diff --cached --quiet; then
  echo "  Nothing changed — gh-pages is already up to date."
else
  git commit -m "Deploy $(date '+%Y-%m-%d %H:%M') — $tile_count tiles"
  echo "▶ Pushing gh-pages..."
  git push origin gh-pages
  echo "✓ Done. Enable GitHub Pages at:"
  echo "  https://github.com/tarekrached/chartsam/settings/pages"
  echo "  → Source: Deploy from branch → gh-pages → / (root)"
fi

cd "$REPO_ROOT"
git worktree remove --force "$WORKTREE_DIR"
