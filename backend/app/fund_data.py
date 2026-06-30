from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd

from .cache import NavCache
from .schemas import AssetType


class FundDataError(RuntimeError):
    """Raised when a fund's net asset value history cannot be used."""


class FundDataService:
    def __init__(self, cache: NavCache | None = None) -> None:
        self.cache = cache or NavCache()

    def get_history(
        self, fund_code: str, start_date: date, end_date: date, asset_type: AssetType = AssetType.CN_FUND
    ) -> tuple[pd.DataFrame, str]:
        cache_key = self._cache_key(asset_type, fund_code)
        if self.cache.is_fresh_and_covers(cache_key, start_date, end_date):
            cached = self.cache.get_navs(cache_key, start_date, end_date)
            if not cached.empty:
                return self._normalize_dates(cached), "cache"

        try:
            if asset_type == AssetType.US_STOCK:
                navs, data_source = self._get_us_stock_history(fund_code, start_date, end_date)
            else:
                raw = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
                navs = self._normalize_akshare_history(raw)
                data_source = "akshare"
        except Exception as exc:  # AkShare wraps remote data sources.
            cached = self.cache.get_navs(cache_key, start_date, end_date)
            if not cached.empty:
                return self._normalize_dates(cached), "cache (stale)"
            label = "美股 ETF/股票" if asset_type == AssetType.US_STOCK else "基金"
            raise FundDataError(f"无法获取{label} {fund_code} 的历史数据：{exc}") from exc

        if navs.empty:
            label = "价格" if asset_type == AssetType.US_STOCK else "单位净值"
            raise FundDataError(f"{fund_code} 未返回可用的{label}数据")
        self.cache.put_navs(cache_key, navs)
        selected = navs[(navs["nav_date"].dt.date >= start_date) & (navs["nav_date"].dt.date <= end_date)]
        if selected.empty:
            label = "价格" if asset_type == AssetType.US_STOCK else "净值"
            raise FundDataError(f"所选回测区间内没有可用{label}数据，请检查代码和日期")
        return selected.reset_index(drop=True), data_source

    def get_name(self, fund_code: str, asset_type: AssetType = AssetType.CN_FUND) -> str | None:
        cache_key = self._cache_key(asset_type, fund_code)
        cached_name = self.cache.get_fund_name(cache_key)
        if cached_name:
            return cached_name
        if asset_type == AssetType.US_STOCK:
            fund_name = fund_code.upper()
        else:
            try:
                names = ak.fund_name_em()
                code_column = self._find_column(names, ("基金代码", "代码"))
                name_column = self._find_column(names, ("基金简称", "基金名称", "名称"))
                matches = names[names[code_column].astype(str).str.zfill(6) == fund_code.zfill(6)]
                fund_name = str(matches.iloc[0][name_column]) if not matches.empty else None
            except Exception:
                # Fund name is display metadata. A valid net-value backtest should not fail without it.
                fund_name = None
        self.cache.put_fund_name(cache_key, fund_name)
        return fund_name

    @staticmethod
    def _cache_key(asset_type: AssetType, fund_code: str) -> str:
        if asset_type == AssetType.US_STOCK:
            return f"us_stock:{fund_code.upper()}"
        return fund_code

    @staticmethod
    def _find_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str:
        for candidate in candidates:
            if candidate in frame.columns:
                return candidate
        raise FundDataError(f"AkShare 返回字段不符合预期，实际字段：{list(frame.columns)}")

    def _normalize_akshare_history(self, frame: pd.DataFrame) -> pd.DataFrame:
        date_column = self._find_column(frame, ("净值日期", "日期"))
        nav_column = self._find_column(frame, ("单位净值", "单位净值(元)"))
        change_column = next((c for c in ("日增长率", "日增长率(%)") if c in frame.columns), None)
        normalized = pd.DataFrame(
            {
                "nav_date": pd.to_datetime(frame[date_column], errors="coerce"),
                "unit_nav": pd.to_numeric(frame[nav_column], errors="coerce"),
                "change_rate": pd.to_numeric(frame[change_column], errors="coerce")
                if change_column
                else None,
            }
        )
        return self._clean_history(normalized)

    def _get_us_stock_history(self, symbol: str, start_date: date, end_date: date) -> tuple[pd.DataFrame, str]:
        try:
            raw = ak.stock_us_daily(symbol=symbol.upper(), adjust="qfq")
            navs = self._normalize_us_stock_history(raw)
            if not navs.empty:
                return navs, "akshare stock_us_daily qfq"
        except Exception:
            pass

        formatted_start = start_date.strftime("%Y%m%d")
        formatted_end = end_date.strftime("%Y%m%d")
        errors: list[str] = []
        for market_code in ("105", "106", "107"):
            eastmoney_symbol = f"{market_code}.{symbol.upper()}"
            try:
                raw = ak.stock_us_hist(
                    symbol=eastmoney_symbol,
                    period="daily",
                    start_date=formatted_start,
                    end_date=formatted_end,
                    adjust="qfq",
                )
                navs = self._normalize_us_stock_history(raw)
                if not navs.empty:
                    return navs, f"akshare stock_us_hist qfq ({eastmoney_symbol})"
            except Exception as exc:
                errors.append(f"{eastmoney_symbol}: {exc}")

        detail = "；".join(errors) if errors else "未返回数据"
        raise FundDataError(detail)

    def _normalize_us_stock_history(self, frame: pd.DataFrame) -> pd.DataFrame:
        date_column = self._find_column(frame, ("date", "日期", "时间"))
        close_column = self._find_column(frame, ("close", "收盘", "收盘价"))
        change_column = next((c for c in ("涨跌幅", "change_rate", "pct_chg") if c in frame.columns), None)
        normalized = pd.DataFrame(
            {
                "nav_date": pd.to_datetime(frame[date_column], errors="coerce"),
                "unit_nav": pd.to_numeric(frame[close_column], errors="coerce"),
                "change_rate": pd.to_numeric(frame[change_column], errors="coerce")
                if change_column
                else None,
            }
        )
        return self._clean_history(normalized)

    @staticmethod
    def _normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
        copied = frame.copy()
        copied["nav_date"] = pd.to_datetime(copied["nav_date"], errors="coerce")
        copied["unit_nav"] = pd.to_numeric(copied["unit_nav"], errors="coerce")
        if "change_rate" not in copied:
            copied["change_rate"] = None
        return FundDataService._clean_history(copied)

    @staticmethod
    def _clean_history(frame: pd.DataFrame) -> pd.DataFrame:
        cleaned = frame.dropna(subset=["nav_date", "unit_nav"])
        cleaned = cleaned[cleaned["unit_nav"] > 0]
        return cleaned.drop_duplicates("nav_date", keep="last").sort_values("nav_date").reset_index(drop=True)
