#!/usr/bin/env bash
set -Eeuo pipefail

REMOTE_URL="${REMOTE_URL:-https://github.com/Trueybin/Fund-Backtesting.git}"
BRANCH="${BRANCH:-main}"
MESSAGE="${1:-Update fund backtesting project}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
  printf '\033[1;34m[github-sync]\033[0m %s\n' "$*"
}

fail() {
  printf '\033[1;31m[github-sync]\033[0m %s\n' "$*" >&2
  exit 1
}

cd "$ROOT_DIR"

command -v git >/dev/null 2>&1 || fail "未找到 git，请先安装 Git。"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "初始化 Git 仓库..."
  git init
fi

if ! git config user.name >/dev/null 2>&1; then
  fail "请先设置 Git 用户名：git config --global user.name \"你的名字\""
fi

if ! git config user.email >/dev/null 2>&1; then
  fail "请先设置 Git 邮箱：git config --global user.email \"你的邮箱\""
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

git rm -r --cached --ignore-unmatch \
  .pnpm-store \
  frontend/node_modules \
  frontend/dist \
  backend/.venv \
  backend/data \
  backend/app/__pycache__ \
  >/dev/null 2>&1 || true

git add .

if git diff --cached --quiet; then
  log "没有需要提交的新变更。"
else
  git commit -m "$MESSAGE"
fi

git branch -M "$BRANCH"
log "推送到 $REMOTE_URL 的 $BRANCH 分支..."
git push -u origin "$BRANCH"
