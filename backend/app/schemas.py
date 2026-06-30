from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class Frequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class NonTradingDayPolicy(str, Enum):
    NEXT_TRADING_DAY = "next_trading_day"
    SKIP = "skip"


class AssetType(str, Enum):
    CN_FUND = "cn_fund"
    US_STOCK = "us_stock"


class BacktestRequest(BaseModel):
    asset_type: AssetType = AssetType.CN_FUND
    fund_code: str = Field(..., min_length=1, max_length=20, examples=["710001"])
    start_date: date
    end_date: date
    investment_amount: float = Field(..., gt=0, examples=[1000])
    frequency: Frequency
    purchase_fee_rate: float = Field(default=0, ge=0, lt=1)
    non_trading_day_policy: NonTradingDayPolicy = NonTradingDayPolicy.NEXT_TRADING_DAY

    @field_validator("fund_code")
    @classmethod
    def normalize_fund_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("基金代码不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_date_range(self) -> "BacktestRequest":
        if self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class Transaction(BaseModel):
    scheduled_date: date
    trade_date: date
    unit_nav: float
    gross_amount: float
    net_subscription_amount: float
    purchased_shares: float
    cumulative_invested: float
    cumulative_shares: float


class CurvePoint(BaseModel):
    date: date
    cumulative_invested: float
    market_value: float


class BacktestResult(BaseModel):
    asset_type: AssetType = AssetType.CN_FUND
    fund_code: str
    fund_name: str | None
    currency: str = "CNY"
    price_label: str = "单位净值"
    share_label: str = "份"
    start_date: date
    end_date: date
    frequency: Frequency
    investment_amount: float
    purchase_fee_rate: float
    non_trading_day_policy: NonTradingDayPolicy
    investment_count: int
    total_invested: float
    total_shares: float
    valuation_date: date
    ending_nav: float
    final_value: float
    total_return: float
    total_return_rate: float
    annualized_return: float | None
    data_source: str
    transactions: list[Transaction]
    curve: list[CurvePoint]
