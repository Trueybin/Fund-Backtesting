from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .backtest import NoInvestmentError, run_backtest
from .fund_data import FundDataError, FundDataService
from .schemas import BacktestRequest, BacktestResult


app = FastAPI(title="场外基金定投回测 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
fund_data_service = FundDataService()


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/backtests", response_model=BacktestResult)
def create_backtest(request: BacktestRequest) -> BacktestResult:
    try:
        navs, data_source = fund_data_service.get_history(
            request.fund_code, request.start_date, request.end_date
        )
        fund_name = fund_data_service.get_name(request.fund_code)
        return run_backtest(request, navs, fund_name, data_source)
    except (FundDataError, NoInvestmentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
