#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
PUBLIC_HOST="${PUBLIC_HOST:-127.0.0.1}"
PACKAGE_MANAGER="${PACKAGE_MANAGER:-auto}"
FORCE_INSTALL="${FORCE_INSTALL:-0}"

BACKEND_PID=""
FRONTEND_PID=""
FRONTEND_PM=""

log() {
  printf '\033[1;34m[fund-backtest]\033[0m %s\n' "$*"
}

fail() {
  printf '\033[1;31m[fund-backtest]\033[0m %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

stop_pid() {
  local pid="${1:-}"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    return
  fi

  if command_exists pkill; then
    pkill -TERM -P "$pid" 2>/dev/null || true
  fi
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  local exit_code=$?
  trap - INT TERM EXIT

  stop_pid "$FRONTEND_PID"
  stop_pid "$BACKEND_PID"

  if [ -n "$FRONTEND_PID" ]; then
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ]; then
    wait "$BACKEND_PID" 2>/dev/null || true
  fi

  exit "$exit_code"
}

trap cleanup INT TERM EXIT

ensure_port_available() {
  local port="$1"
  local label="$2"

  if command_exists lsof && lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    fail "$label 端口 $port 已被占用。可先关闭占用进程，或改端口运行：BACKEND_PORT=8010 FRONTEND_PORT=5174 ./start.sh"
  fi
}

select_python() {
  local candidate
  for candidate in python3 python; do
    if command_exists "$candidate" && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  fail "需要 Python 3.10+，但当前环境没有找到可用的 python3/python。"
}

ensure_backend_deps() {
  if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
    local python_cmd
    python_cmd="$(select_python)"

    log "首次准备后端 Python 环境..."
    (cd "$BACKEND_DIR" && "$python_cmd" -m venv .venv)
  fi

  if [ "$FORCE_INSTALL" = "1" ] || ! "$BACKEND_DIR/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

required = ("fastapi", "uvicorn", "akshare", "pandas")
missing = [name for name in required if importlib.util.find_spec(name) is None]
raise SystemExit(1 if missing else 0)
PY
  then
    log "安装/更新后端依赖..."
    (cd "$BACKEND_DIR" && .venv/bin/python -m pip install -r requirements.txt)
  fi
}

detect_package_manager() {
  if [ "$PACKAGE_MANAGER" != "auto" ]; then
    command_exists "$PACKAGE_MANAGER" || fail "找不到指定的前端包管理器：$PACKAGE_MANAGER"
    printf '%s\n' "$PACKAGE_MANAGER"
    return
  fi

  if command_exists pnpm; then
    printf '%s\n' "pnpm"
    return
  fi

  if command_exists npm; then
    printf '%s\n' "npm"
    return
  fi

  fail "需要 Node.js 20+ 和 npm；如果使用 pnpm，也可以直接安装 pnpm 后重试。"
}

install_frontend_deps() {
  case "$FRONTEND_PM" in
    pnpm)
      (cd "$FRONTEND_DIR" && pnpm install)
      ;;
    npm)
      if [ -f "$FRONTEND_DIR/package-lock.json" ]; then
        (cd "$FRONTEND_DIR" && npm ci)
      else
        (cd "$FRONTEND_DIR" && npm install)
      fi
      ;;
    *)
      fail "暂不支持的前端包管理器：$FRONTEND_PM"
      ;;
  esac
}

ensure_frontend_deps() {
  FRONTEND_PM="$(detect_package_manager)"

  if [ "$FORCE_INSTALL" = "1" ] || [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log "首次准备前端依赖（使用 $FRONTEND_PM）..."
    install_frontend_deps
  fi
}

run_frontend_dev() {
  case "$FRONTEND_PM" in
    pnpm)
      VITE_API_BASE_URL="http://$PUBLIC_HOST:$BACKEND_PORT" pnpm run dev --host "$BIND_HOST" --port "$FRONTEND_PORT"
      ;;
    npm)
      VITE_API_BASE_URL="http://$PUBLIC_HOST:$BACKEND_PORT" npm run dev -- --host "$BIND_HOST" --port "$FRONTEND_PORT"
      ;;
    *)
      fail "暂不支持的前端包管理器：$FRONTEND_PM"
      ;;
  esac
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts=30

  if ! command_exists curl; then
    return
  fi

  while [ "$attempts" -gt 0 ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$label 已就绪：$url"
      return
    fi
    attempts=$((attempts - 1))
    sleep 1
  done

  log "$label 还在启动中，可继续等待终端日志。"
}

main() {
  ensure_port_available "$BACKEND_PORT" "后端"
  ensure_port_available "$FRONTEND_PORT" "前端"

  ensure_backend_deps
  ensure_frontend_deps

  log "启动后端：http://$PUBLIC_HOST:$BACKEND_PORT"
  (cd "$BACKEND_DIR" && .venv/bin/python -m uvicorn app.main:app --reload --host "$BIND_HOST" --port "$BACKEND_PORT") &
  BACKEND_PID=$!

  log "启动前端：http://$PUBLIC_HOST:$FRONTEND_PORT"
  (cd "$FRONTEND_DIR" && run_frontend_dev) &
  FRONTEND_PID=$!

  wait_for_url "http://$PUBLIC_HOST:$BACKEND_PORT/api/health" "后端"
  wait_for_url "http://$PUBLIC_HOST:$FRONTEND_PORT" "前端"

  printf '\n'
  log "访问地址：http://$PUBLIC_HOST:$FRONTEND_PORT"
  log "按 Ctrl+C 停止前端和后端。"
  printf '\n'

  while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      fail "后端服务已退出，请查看上方日志。"
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      fail "前端服务已退出，请查看上方日志。"
    fi
    sleep 2
  done
}

main "$@"
