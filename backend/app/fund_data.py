from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd

from .cache import NavCache


class FundDataError(RuntimeError):
    """Raised when a fund's net asset value history cannot be used."""


class FundDataService:
    def __init__(self, cache: NavCache | None = None) -> None:
        self.cache = cache or NavCache()

    def get_history(self, fund_code: str, start_date: date, end_date: date) -> tuple[pd.DataFrame, str]:
        if self.cache.is_fresh_and_covers(fund_code, start_date, end_date):
            cached = self.cache.get_navs(fund_code, start_date, end_date)
            if not cached.empty:
                return self._normalize_dates(cached), "cache"

        try:
            raw = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            navs = self._normalize_akshare_history(raw)
        except Exception as exc:  # AkShare wraps a remote Eastmoney data source.
            cached = self.cache.get_navs(fund_code, start_date, end_date)
            if not cached.empty:
                return self._normalize_dates(cached), "cache (stale)"
            raise FundDataError(f"无法获取基金 {fund_code} 的历史净值：{exc}") from exc

        if navs.empty:
            raise FundDataError(f"基金 {fund_code} 未返回可用的单位净值数据")
        self.cache.put_navs(fund_code, navs)
        selected = navs[(navs["nav_date"].dt.date >= start_date) & (navs["nav_date"].dt.date <= end_date)]
        if selected.empty:
            raise FundDataError("所选回测区间内没有可用净值数据，请检查基金代码和日期")
        return selected.reset_index(drop=True), "akshare"

    def get_name(self, fund_code: str) -> str | None:
        cached_name = self.cache.get_fund_name(fund_code)
        if cached_name:
            return cached_name
        try:
            names = ak.fund_name_em()
            code_column = self._find_column(names, ("基金代码", "代码"))
            name_column = self._find_column(names, ("基金简称", "基金名称", "名称"))
            matches = names[names[code_column].astype(str).str.zfill(6) == fund_code.zfill(6)]
            fund_name = str(matches.iloc[0][name_column]) if not matches.empty else None
        except Exception:
            # Fund name is display metadata. A valid net-value backtest should not fail without it.
            fund_name = None
        self.cache.put_fund_name(fund_code, fund_name)
        return fund_name

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
