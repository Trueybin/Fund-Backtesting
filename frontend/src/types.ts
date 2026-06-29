export type Frequency = 'daily' | 'weekly' | 'monthly'
export type NonTradingDayPolicy = 'next_trading_day' | 'skip'

export interface BacktestRequest {
  fund_code: string
  start_date: string
  end_date: string
  investment_amount: number
  frequency: Frequency
  purchase_fee_rate: number
  non_trading_day_policy: NonTradingDayPolicy
}

export interface Transaction {
  scheduled_date: string
  trade_date: string
  unit_nav: number
  gross_amount: number
  net_subscription_amount: number
  purchased_shares: number
  cumulative_invested: number
  cumulative_shares: number
}

export interface CurvePoint {
  date: string
  cumulative_invested: number
  market_value: number
}

export interface BacktestResult {
  fund_code: string
  fund_name: string | null
  start_date: string
  end_date: string
  frequency: Frequency
  investment_amount: number
  purchase_fee_rate: number
  non_trading_day_policy: NonTradingDayPolicy
  investment_count: number
  total_invested: number
  total_shares: number
  valuation_date: string
  ending_nav: number
  final_value: number
  total_return: number
  total_return_rate: number
  annualized_return: number | null
  data_source: string
  transactions: Transaction[]
  curve: CurvePoint[]
}
