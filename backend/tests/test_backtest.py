from datetime import date
import unittest

import pandas as pd

from app.backtest import run_backtest, scheduled_dates
from app.schemas import AssetType, BacktestRequest, Frequency, NonTradingDayPolicy


class BacktestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.navs = pd.DataFrame(
            {
                "nav_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05", "2024-02-05"]),
                "unit_nav": [1.0, 1.1, 1.2, 1.3],
                "change_rate": [None, None, None, None],
            }
        )

    def test_monthly_schedule_keeps_original_day_after_short_month(self) -> None:
        self.assertEqual(
            scheduled_dates(date(2024, 1, 31), date(2024, 4, 30), Frequency.MONTHLY),
            [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)],
        )

    def test_non_trading_day_can_be_shifted_to_next_nav_date(self) -> None:
        request = BacktestRequest(
            fund_code="000001",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            investment_amount=100,
            frequency="weekly",
            non_trading_day_policy="next_trading_day",
        )
        result = run_backtest(request, self.navs, "测试基金", "test")
        self.assertEqual(result.investment_count, 1)
        self.assertEqual(result.transactions[0].trade_date, date(2024, 1, 2))
        self.assertAlmostEqual(result.total_shares, 100)
        self.assertAlmostEqual(result.final_value, 120)

    def test_daily_frequency_only_buys_on_purchase_dates(self) -> None:
        navs = pd.DataFrame(
            {
                "nav_date": pd.to_datetime(["2025-10-09", "2025-10-10", "2025-10-13"]),
                "unit_nav": [1.0, 1.0, 1.0],
                "change_rate": [None, None, None],
            }
        )
        request = BacktestRequest(
            fund_code="000307",
            start_date=date(2025, 10, 9),
            end_date=date(2025, 10, 13),
            investment_amount=100,
            frequency="daily",
            non_trading_day_policy="next_trading_day",
        )
        result = run_backtest(request, navs, "测试基金", "test")
        self.assertEqual(result.investment_count, 3)
        self.assertEqual(
            [transaction.scheduled_date for transaction in result.transactions],
            [date(2025, 10, 9), date(2025, 10, 10), date(2025, 10, 13)],
        )
        self.assertEqual(
            [transaction.trade_date for transaction in result.transactions],
            [date(2025, 10, 9), date(2025, 10, 10), date(2025, 10, 13)],
        )

    def test_daily_frequency_skips_adjusted_working_saturday(self) -> None:
        navs = pd.DataFrame(
            {
                "nav_date": pd.to_datetime(["2025-10-10", "2025-10-11", "2025-10-13"]),
                "unit_nav": [1.0, 1.0, 1.0],
                "change_rate": [None, None, None],
            }
        )
        request = BacktestRequest(
            fund_code="000307",
            start_date=date(2025, 10, 10),
            end_date=date(2025, 10, 13),
            investment_amount=100,
            frequency="daily",
            non_trading_day_policy="next_trading_day",
        )
        result = run_backtest(request, navs, "测试基金", "test")
        self.assertEqual(
            [transaction.scheduled_date for transaction in result.transactions],
            [date(2025, 10, 10), date(2025, 10, 13)],
        )
        self.assertEqual(result.asset_type, AssetType.CN_FUND)
        self.assertEqual(result.currency, "CNY")
        self.assertEqual(result.price_label, "单位净值")

    def test_us_stock_daily_frequency_uses_market_price_dates(self) -> None:
        prices = pd.DataFrame(
            {
                "nav_date": pd.to_datetime(["2024-07-03", "2024-07-05", "2024-07-08"]),
                "unit_nav": [10.0, 11.0, 12.0],
                "change_rate": [None, None, None],
            }
        )
        request = BacktestRequest(
            asset_type="us_stock",
            fund_code="voo",
            start_date=date(2024, 7, 3),
            end_date=date(2024, 7, 8),
            investment_amount=59,
            frequency="daily",
            non_trading_day_policy="next_trading_day",
        )
        result = run_backtest(request, prices, "VOO", "test")
        self.assertEqual(result.fund_code, "VOO")
        self.assertEqual(result.asset_type, AssetType.US_STOCK)
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.price_label, "复权收盘价")
        self.assertEqual(result.share_label, "股")
        self.assertEqual(
            [transaction.trade_date for transaction in result.transactions],
            [date(2024, 7, 3), date(2024, 7, 5), date(2024, 7, 8)],
        )
        self.assertNotIn(date(2024, 7, 4), [transaction.trade_date for transaction in result.transactions])
        self.assertAlmostEqual(result.transactions[0].purchased_shares, 5.9)

    def test_us_stock_weekly_holiday_can_shift_to_next_market_date(self) -> None:
        prices = pd.DataFrame(
            {
                "nav_date": pd.to_datetime(["2024-07-03", "2024-07-05", "2024-07-08"]),
                "unit_nav": [10.0, 11.0, 12.0],
                "change_rate": [None, None, None],
            }
        )
        request = BacktestRequest(
            asset_type="us_stock",
            fund_code="QQQM",
            start_date=date(2024, 7, 4),
            end_date=date(2024, 7, 8),
            investment_amount=59,
            frequency="weekly",
            non_trading_day_policy="next_trading_day",
        )
        result = run_backtest(request, prices, "QQQM", "test")
        self.assertEqual(result.investment_count, 1)
        self.assertEqual(result.transactions[0].scheduled_date, date(2024, 7, 4))
        self.assertEqual(result.transactions[0].trade_date, date(2024, 7, 5))
        self.assertAlmostEqual(result.transactions[0].purchased_shares, 59 / 11)

    def test_purchase_fee_reduces_purchased_shares(self) -> None:
        request = BacktestRequest(
            fund_code="000001",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            investment_amount=101,
            frequency="weekly",
            purchase_fee_rate=0.01,
            non_trading_day_policy=NonTradingDayPolicy.SKIP,
        )
        result = run_backtest(request, self.navs, "测试基金", "test")
        self.assertAlmostEqual(result.total_shares, 100)
        self.assertAlmostEqual(result.total_invested, 101)

    def test_xirr_is_undefined_for_a_same_day_backtest(self) -> None:
        request = BacktestRequest(
            fund_code="000001",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
            investment_amount=100,
            frequency="daily",
        )
        result = run_backtest(request, self.navs, "测试基金", "test")
        self.assertIsNone(result.annualized_return)


if __name__ == "__main__":
    unittest.main()
