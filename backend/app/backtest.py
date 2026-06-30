from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd

from .schemas import (
    AssetType,
    BacktestRequest,
    BacktestResult,
    CurvePoint,
    Frequency,
    NonTradingDayPolicy,
    Transaction,
)


class NoInvestmentError(ValueError):
    """Raised when the selected schedule does not execute any purchase."""


def scheduled_dates(start_date: date, end_date: date, frequency: Frequency) -> list[date]:
    if frequency == Frequency.DAILY:
        dates: list[date] = []
        current = start_date
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    if frequency == Frequency.WEEKLY:
        dates = []
        current = start_date
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=7)
        return dates

    # Recalculate from the original day each month, so Jan 31 -> Feb 28 -> Mar 31.
    dates = []
    index = 0
    while True:
        month_index = start_date.month - 1 + index
        year = start_date.year + month_index // 12
        month = month_index % 12 + 1
        current = date(year, month, min(start_date.day, calendar.monthrange(year, month)[1]))
        if current > end_date:
            break
        dates.append(current)
        index += 1
    return dates


def supported_purchase_dates(nav_dates: list[date], asset_type: AssetType = AssetType.CN_FUND) -> list[date]:
    """Return dates that can be used for OTC fund purchases.

    AkShare NAV dates are the primary trading-day source. A weekday guard is kept
    because Chinese OTC funds generally do not accept subscriptions on weekends,
    including adjusted working Saturdays.

    US stocks and ETFs use AkShare's actual daily market-price dates directly.
    US holidays have no price row, so they are naturally excluded without a
    hand-maintained holiday table.
    """
    if asset_type == AssetType.US_STOCK:
        return nav_dates
    return [nav_date for nav_date in nav_dates if nav_date.weekday() < 5]


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Return annualized money-weighted return using bisection, or None when undefined."""
    if len(cashflows) < 2 or not any(amount < 0 for _, amount in cashflows) or not any(
        amount > 0 for _, amount in cashflows
    ):
        return None
    first_date = min(flow_date for flow_date, _ in cashflows)
    if max(flow_date for flow_date, _ in cashflows) == first_date:
        return None

    def npv(rate: float) -> float:
        return sum(
            amount / ((1 + rate) ** ((flow_date - first_date).days / 365.0))
            for flow_date, amount in cashflows
        )

    low, high = -0.9999, 10.0
    low_value, high_value = npv(low), npv(high)
    while low_value * high_value > 0 and high < 1_000_000:
        high *= 2
        high_value = npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(100):
        mid = (low + high) / 2
        mid_value = npv(mid)
        if abs(mid_value) < 1e-9:
            return mid
        if low_value * mid_value <= 0:
            high = mid
        else:
            low, low_value = mid, mid_value
    return (low + high) / 2


def run_backtest(request: BacktestRequest, navs: pd.DataFrame, fund_name: str | None, data_source: str) -> BacktestResult:
    history = navs.copy().sort_values("nav_date").reset_index(drop=True)
    history["nav_date"] = pd.to_datetime(history["nav_date"])
    nav_dates = [value.date() for value in history["nav_date"]]
    nav_by_date = dict(zip(nav_dates, history["unit_nav"].astype(float)))
    purchase_dates = supported_purchase_dates(nav_dates, request.asset_type)
    purchase_dates_set = set(purchase_dates)

    valuation_candidates = [value for value in nav_dates if value <= request.end_date]
    if not valuation_candidates:
        raise NoInvestmentError("结束日及之前没有可用净值，无法估值")
    valuation_date = valuation_candidates[-1]
    ending_nav = nav_by_date[valuation_date]

    cumulative_invested = 0.0
    cumulative_shares = 0.0
    transactions: list[Transaction] = []

    if request.frequency == Frequency.DAILY:
        planned_dates = [nav_date for nav_date in purchase_dates if request.start_date <= nav_date <= valuation_date]
    else:
        planned_dates = scheduled_dates(request.start_date, request.end_date, request.frequency)

    for scheduled_date in planned_dates:
        eligible_dates = [
            nav_date for nav_date in purchase_dates if nav_date >= scheduled_date and nav_date <= valuation_date
        ]
        if request.non_trading_day_policy == NonTradingDayPolicy.SKIP:
            trade_date = scheduled_date if scheduled_date in purchase_dates_set else None
        else:
            trade_date = eligible_dates[0] if eligible_dates else None
        if trade_date is None:
            continue
        nav = nav_by_date[trade_date]
        net_amount = request.investment_amount / (1 + request.purchase_fee_rate)
        purchased_shares = net_amount / nav
        cumulative_invested += request.investment_amount
        cumulative_shares += purchased_shares
        transactions.append(
            Transaction(
                scheduled_date=scheduled_date,
                trade_date=trade_date,
                unit_nav=nav,
                gross_amount=request.investment_amount,
                net_subscription_amount=net_amount,
                purchased_shares=purchased_shares,
                cumulative_invested=cumulative_invested,
                cumulative_shares=cumulative_shares,
            )
        )

    if not transactions:
        raise NoInvestmentError("所选日期和定投规则没有产生有效买入记录")

    transactions_by_date: dict[date, list[Transaction]] = {}
    for transaction in transactions:
        transactions_by_date.setdefault(transaction.trade_date, []).append(transaction)
    running_invested = 0.0
    running_shares = 0.0
    curve: list[CurvePoint] = []
    for row in history.itertuples(index=False):
        nav_date = row.nav_date.date()
        if nav_date > valuation_date:
            break
        for transaction in transactions_by_date.get(nav_date, []):
            running_invested += transaction.gross_amount
            running_shares += transaction.purchased_shares
        if running_invested:
            curve.append(
                CurvePoint(
                    date=nav_date,
                    cumulative_invested=running_invested,
                    market_value=running_shares * float(row.unit_nav),
                )
            )

    final_value = cumulative_shares * ending_nav
    total_return = final_value - cumulative_invested
    cashflows = [(transaction.trade_date, -transaction.gross_amount) for transaction in transactions]
    cashflows.append((valuation_date, final_value))
    return BacktestResult(
        asset_type=request.asset_type,
        fund_code=request.fund_code,
        fund_name=fund_name,
        currency="USD" if request.asset_type == AssetType.US_STOCK else "CNY",
        price_label="复权收盘价" if request.asset_type == AssetType.US_STOCK else "单位净值",
        share_label="股" if request.asset_type == AssetType.US_STOCK else "份",
        start_date=request.start_date,
        end_date=request.end_date,
        frequency=request.frequency,
        investment_amount=request.investment_amount,
        purchase_fee_rate=request.purchase_fee_rate,
        non_trading_day_policy=request.non_trading_day_policy,
        investment_count=len(transactions),
        total_invested=cumulative_invested,
        total_shares=cumulative_shares,
        valuation_date=valuation_date,
        ending_nav=ending_nav,
        final_value=final_value,
        total_return=total_return,
        total_return_rate=total_return / cumulative_invested,
        annualized_return=xirr(cashflows),
        data_source=data_source,
        transactions=transactions,
        curve=curve,
    )
