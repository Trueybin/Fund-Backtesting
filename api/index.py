from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Vercel Functions only provide ephemeral writable storage. This cache is a
# best-effort speedup; cold starts and redeploys can safely lose it.
os.environ.setdefault("FUND_CACHE_PATH", "/tmp/fund_backtesting_cache.db")

from app.main import app  # noqa: E402
