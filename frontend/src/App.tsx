import { useMemo, useRef, useState } from 'react'
import type { FormEvent, PointerEvent } from 'react'
import { createBacktest } from './api'
import type {
  AssetType,
  BacktestRequest,
  BacktestResult,
  CurvePoint,
  Frequency,
  NonTradingDayPolicy,
} from './types'

type FormState = Omit<BacktestRequest, 'investment_amount' | 'purchase_fee_rate'> & {
  investment_amount: string
  purchase_fee_rate_percent: string
}

const frequencyLabels: Record<Frequency, string> = {
  daily: '每日（交易日）',
  weekly: '每周',
  monthly: '每月',
}

const policyLabels: Record<NonTradingDayPolicy, string> = {
  next_trading_day: '顺延至下一交易日',
  skip: '跳过',
}

const assetOptions: Record<AssetType, {
  title: string
  shortTitle: string
  defaultCode: string
  defaultAmount: string
  codeLabel: string
  amountLabel: string
  codePlaceholder: string
  feeLabel: string
  loadingText: string
  footerText: string
}> = {
  cn_fund: {
    title: '国内场外基金',
    shortTitle: '场外基金',
    defaultCode: '710001',
    defaultAmount: '1000',
    codeLabel: '基金代码',
    amountLabel: '每次定投金额（元）',
    codePlaceholder: '如 710001',
    feeLabel: '申购费率（%）',
    loadingText: '正在拉取净值并回测…',
    footerText: '每日定投按有净值的可买入交易日执行；非交易日顺延/跳过用于每周、每月计划。投入金额按含费金额累计。',
  },
  us_stock: {
    title: '美股 ETF / 股票',
    shortTitle: '美股',
    defaultCode: 'VOO',
    defaultAmount: '59',
    codeLabel: 'ETF / 股票代码',
    amountLabel: '每次定投金额（美元）',
    codePlaceholder: '如 VOO、QQQM',
    feeLabel: '交易费率（%）',
    loadingText: '正在拉取美股价格并回测…',
    footerText: '美股定投按 AkShare 返回的实际行情日期执行；美国节假日没有行情数据，因此不会买入。',
  },
}

function dateInputValue(date: Date): string {
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return offsetDate.toISOString().slice(0, 10)
}

function initialForm(): FormState {
  const today = new Date()
  const threeYearsAgo = new Date(today)
  threeYearsAgo.setFullYear(today.getFullYear() - 3)
  return {
    asset_type: 'cn_fund',
    fund_code: '710001',
    start_date: dateInputValue(threeYearsAgo),
    end_date: dateInputValue(today),
    investment_amount: '1000',
    frequency: 'monthly',
    purchase_fee_rate_percent: '0',
    non_trading_day_policy: 'next_trading_day',
  }
}

function formatMoney(value: number, currency = 'CNY'): string {
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatNumber(value: number, digits = 4): string {
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(value)
}

function formatRate(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(2)}%`
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function LineChart({ curve, currency }: { curve: CurvePoint[]; currency: string }) {
  const [zoomPercent, setZoomPercent] = useState(100)
  const [startIndex, setStartIndex] = useState(0)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const scrollbarDrag = useRef<{ thumbOffsetPercent: number } | null>(null)

  const minZoomPercent = curve.length > 0 ? Math.min(100, Math.ceil((Math.min(30, curve.length) / curve.length) * 100)) : 100
  const effectiveZoomPercent = clamp(zoomPercent, minZoomPercent, 100)
  const visibleCount = curve.length === 0
    ? 0
    : Math.max(1, Math.min(curve.length, Math.round((curve.length * effectiveZoomPercent) / 100)))
  const maxStartIndex = Math.max(curve.length - visibleCount, 0)
  const effectiveStartIndex = clamp(startIndex, 0, maxStartIndex)
  const visibleCurve = curve.slice(effectiveStartIndex, effectiveStartIndex + visibleCount)
  const effectiveHoverIndex = hoverIndex === null ? null : clamp(hoverIndex, 0, Math.max(visibleCurve.length - 1, 0))
  const activeIndex = effectiveHoverIndex ?? Math.max(visibleCurve.length - 1, 0)
  const activePoint = visibleCurve[activeIndex]

  const chart = useMemo(() => {
    if (visibleCurve.length === 0) return null
    const width = 960
    const height = 390
    const padding = { top: 26, right: 28, bottom: 52, left: 74 }
    const values = visibleCurve.flatMap((item) => [item.cumulative_invested, item.market_value])
    const minValue = Math.min(...values, 0)
    const maxValue = Math.max(...values)
    const range = maxValue - minValue || 1
    const x = (index: number) =>
      padding.left + (index / Math.max(visibleCurve.length - 1, 1)) * (width - padding.left - padding.right)
    const y = (value: number) =>
      height - padding.bottom - ((value - minValue) / range) * (height - padding.top - padding.bottom)
    const line = (field: 'cumulative_invested' | 'market_value') =>
      visibleCurve.map((point, index) => `${x(index)},${y(point[field])}`).join(' ')
    const yTicks = Array.from({ length: 5 }, (_, index) => minValue + (range * index) / 4)
    const plotLeft = padding.left
    const plotRight = width - padding.right
    const plotTop = padding.top
    const plotBottom = height - padding.bottom
    return { width, height, padding, x, y, line, yTicks, plotLeft, plotRight, plotTop, plotBottom }
  }, [visibleCurve])

  if (!chart) return null

  function setZoomAround(nextPercent: number, anchorIndex = Math.floor(visibleCount / 2)) {
    const nextZoomPercent = clamp(nextPercent, minZoomPercent, 100)
    const nextVisibleCount = Math.max(1, Math.min(curve.length, Math.round((curve.length * nextZoomPercent) / 100)))
    const absoluteAnchor = effectiveStartIndex + clamp(anchorIndex, 0, Math.max(visibleCount - 1, 0))
    const anchorRatio = visibleCount <= 1 ? 0 : anchorIndex / (visibleCount - 1)
    const nextMaxStartIndex = Math.max(curve.length - nextVisibleCount, 0)
    const nextStartIndex = clamp(Math.round(absoluteAnchor - anchorRatio * (nextVisibleCount - 1)), 0, nextMaxStartIndex)
    setZoomPercent(nextZoomPercent)
    setStartIndex(nextStartIndex)
  }

  const scrollbarThumbWidthPercent = curve.length === 0 ? 100 : clamp((visibleCount / curve.length) * 100, 6, 100)
  const scrollbarTravelPercent = Math.max(100 - scrollbarThumbWidthPercent, 0)
  const scrollbarThumbLeftPercent = maxStartIndex === 0
    ? 0
    : (effectiveStartIndex / maxStartIndex) * scrollbarTravelPercent

  function setWindowFromThumbLeft(leftPercent: number) {
    if (maxStartIndex === 0 || scrollbarTravelPercent === 0) {
      setStartIndex(0)
      return
    }
    const nextRatio = clamp(leftPercent, 0, scrollbarTravelPercent) / scrollbarTravelPercent
    setStartIndex(Math.round(nextRatio * maxStartIndex))
  }

  function trackPointerPercent(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    return ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100
  }

  function handleScrollbarTrackPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (maxStartIndex === 0) return
    const pointerPercent = trackPointerPercent(event)
    const thumbOffsetPercent = scrollbarThumbWidthPercent / 2
    scrollbarDrag.current = { thumbOffsetPercent }
    setWindowFromThumbLeft(pointerPercent - thumbOffsetPercent)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function handleScrollbarThumbPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (maxStartIndex === 0) return
    event.stopPropagation()
    const track = event.currentTarget.parentElement
    if (!track) return
    const rect = track.getBoundingClientRect()
    const pointerPercent = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100
    scrollbarDrag.current = {
      thumbOffsetPercent: clamp(pointerPercent - scrollbarThumbLeftPercent, 0, scrollbarThumbWidthPercent),
    }
    track.setPointerCapture(event.pointerId)
  }

  function handleScrollbarPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!scrollbarDrag.current || maxStartIndex === 0) return
    setWindowFromThumbLeft(trackPointerPercent(event) - scrollbarDrag.current.thumbOffsetPercent)
  }

  function endScrollbarDrag(event: PointerEvent<HTMLDivElement>) {
    scrollbarDrag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!chart) return
    const rect = event.currentTarget.getBoundingClientRect()
    const pointerX = ((event.clientX - rect.left) / rect.width) * chart.width
    const ratio = clamp((pointerX - chart.plotLeft) / Math.max(chart.plotRight - chart.plotLeft, 1), 0, 1)
    setHoverIndex(Math.round(ratio * Math.max(visibleCurve.length - 1, 0)))
  }

  const firstDate = visibleCurve[0].date
  const middleDate = visibleCurve[Math.floor((visibleCurve.length - 1) / 2)].date
  const lastDate = visibleCurve[visibleCurve.length - 1].date
  const activeX = chart.x(activeIndex)
  const activeMarketY = chart.y(activePoint.market_value)
  const activeInvestedY = chart.y(activePoint.cumulative_invested)
  const dateLabelWidth = 108
  const valueLabelWidth = 116
  const dateLabelX = clamp(activeX - dateLabelWidth / 2, chart.plotLeft, chart.plotRight - dateLabelWidth)
  const valueLabelY = clamp(activeMarketY - 12, chart.plotTop, chart.plotBottom - 24)
  const tooltipWidth = 190
  const tooltipHeight = 92
  const tooltipX = activeX > chart.width - tooltipWidth - 26 ? activeX - tooltipWidth - 14 : activeX + 14
  const tooltipY = clamp(activeMarketY - tooltipHeight / 2, chart.plotTop + 6, chart.plotBottom - tooltipHeight - 6)
  const activeReturn = activePoint.market_value - activePoint.cumulative_invested
  const isZoomed = effectiveZoomPercent < 100

  return (
    <div className="chart-wrap" aria-label="累计投入和资产市值曲线">
      <div className="chart-toolbar">
        <div className="chart-readout">
          <strong>{activePoint.date}</strong>
          <span>资产市值 {formatMoney(activePoint.market_value, currency)}</span>
          <span>累计投入 {formatMoney(activePoint.cumulative_invested, currency)}</span>
          <span className={activeReturn >= 0 ? 'positive' : 'negative'}>浮动收益 {formatMoney(activeReturn, currency)}</span>
        </div>
        <div className="legend">
          <span><i className="legend-line invested" />累计投入</span>
          <span><i className="legend-line value" />资产市值</span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${chart.width} ${chart.height}`}
        role="img"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverIndex(null)}
      >
        {chart.yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={chart.plotLeft}
              x2={chart.plotRight}
              y1={chart.y(tick)}
              y2={chart.y(tick)}
              className="grid-line"
            />
            <text x={chart.padding.left - 9} y={chart.y(tick) + 4} className="axis-label" textAnchor="end">
              {formatNumber(tick, 0)}
            </text>
          </g>
        ))}
        <rect
          x={chart.plotLeft}
          y={chart.plotTop}
          width={chart.plotRight - chart.plotLeft}
          height={chart.plotBottom - chart.plotTop}
          className="chart-hit-area"
        />
        <polyline points={chart.line('cumulative_invested')} className="chart-line invested-line" />
        <polyline points={chart.line('market_value')} className="chart-line value-line" />
        {activePoint && (
          <g className={effectiveHoverIndex === null ? 'crosshair idle' : 'crosshair'}>
            <line x1={activeX} x2={activeX} y1={chart.plotTop} y2={chart.plotBottom} className="crosshair-line" />
            <line x1={chart.plotLeft} x2={chart.plotRight} y1={activeMarketY} y2={activeMarketY} className="crosshair-line" />
            <circle cx={activeX} cy={activeMarketY} r="4.2" className="market-dot" />
            <circle cx={activeX} cy={activeInvestedY} r="3.6" className="invested-dot" />
            <rect x={chart.plotLeft - valueLabelWidth - 8} y={valueLabelY} width={valueLabelWidth} height="24" rx="5" className="value-badge" />
            <text x={chart.plotLeft - 14} y={valueLabelY + 16} className="value-badge-text" textAnchor="end">
              {formatMoney(activePoint.market_value, currency)}
            </text>
            <rect x={dateLabelX} y={chart.plotBottom + 12} width={dateLabelWidth} height="27" rx="6" className="date-badge" />
            <text x={dateLabelX + dateLabelWidth / 2} y={chart.plotBottom + 30} className="date-badge-text" textAnchor="middle">
              {activePoint.date}
            </text>
            <g className="chart-tooltip">
              <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="8" />
              <text x={tooltipX + 12} y={tooltipY + 22} className="tooltip-title">{activePoint.date}</text>
              <text x={tooltipX + 12} y={tooltipY + 45}>资产市值</text>
              <text x={tooltipX + tooltipWidth - 12} y={tooltipY + 45} textAnchor="end">{formatMoney(activePoint.market_value, currency)}</text>
              <text x={tooltipX + 12} y={tooltipY + 67}>累计投入</text>
              <text x={tooltipX + tooltipWidth - 12} y={tooltipY + 67} textAnchor="end">{formatMoney(activePoint.cumulative_invested, currency)}</text>
            </g>
          </g>
        )}
        {[firstDate, middleDate, lastDate].map((date, index) => (
          <text
            key={`${date}-${index}`}
            x={chart.x(index === 0 ? 0 : index === 1 ? Math.floor((visibleCurve.length - 1) / 2) : visibleCurve.length - 1)}
            y={chart.height - 12}
            className="axis-label"
            textAnchor={index === 0 ? 'start' : index === 2 ? 'end' : 'middle'}
          >
            {date}
          </text>
        ))}
      </svg>
      <div className="chart-window-scrollbar">
        <div
          className={`chart-scrollbar-track${maxStartIndex === 0 ? ' disabled' : ''}`}
          role="scrollbar"
          aria-label="时间窗口滚动条"
          aria-orientation="horizontal"
          aria-valuemin={0}
          aria-valuemax={maxStartIndex}
          aria-valuenow={effectiveStartIndex}
          tabIndex={maxStartIndex === 0 ? -1 : 0}
          onPointerDown={handleScrollbarTrackPointerDown}
          onPointerMove={handleScrollbarPointerMove}
          onPointerUp={endScrollbarDrag}
          onPointerCancel={endScrollbarDrag}
        >
          <div
            className="chart-scrollbar-thumb"
            style={{ left: `${scrollbarThumbLeftPercent}%`, width: `${scrollbarThumbWidthPercent}%` }}
            onPointerDown={handleScrollbarThumbPointerDown}
          />
        </div>
        <span>{firstDate} 至 {lastDate}</span>
      </div>
      <div className="chart-controls" aria-label="图表显示范围">
        <button type="button" className="chart-control-button" onClick={() => setZoomAround(effectiveZoomPercent - 15, activeIndex)}>
          ＋ 放大
        </button>
        <button type="button" className="chart-control-button" onClick={() => setZoomAround(effectiveZoomPercent + 15, activeIndex)} disabled={!isZoomed}>
          － 缩小
        </button>
        <label className="range-control">
          显示范围
          <input
            type="range"
            min={minZoomPercent}
            max="100"
            step="1"
            value={effectiveZoomPercent}
            onChange={(event) => setZoomAround(Number(event.target.value), activeIndex)}
          />
          <span>{visibleCount} 个交易点</span>
        </label>
      </div>
    </div>
  )
}

function App() {
  const [form, setForm] = useState<FormState>(initialForm)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const currentAsset = assetOptions[form.asset_type]

  function updateField<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [field]: value }))
  }

  function switchAssetType(assetType: AssetType) {
    setForm((previous) => {
      if (previous.asset_type === assetType) return previous
      const previousDefaults = assetOptions[previous.asset_type]
      const nextDefaults = assetOptions[assetType]
      const looksLikeCnFundCode = /^\d{1,6}$/.test(previous.fund_code.trim())
      const looksLikeUsTicker = /^[A-Za-z][A-Za-z.:-]{0,19}$/.test(previous.fund_code.trim())
      const shouldReplaceCode =
        previous.fund_code === previousDefaults.defaultCode ||
        (assetType === 'us_stock' && looksLikeCnFundCode) ||
        (assetType === 'cn_fund' && looksLikeUsTicker)
      return {
        ...previous,
        asset_type: assetType,
        fund_code: shouldReplaceCode ? nextDefaults.defaultCode : previous.fund_code,
        investment_amount:
          previous.investment_amount === previousDefaults.defaultAmount
            ? nextDefaults.defaultAmount
            : previous.investment_amount,
        purchase_fee_rate_percent: assetType === 'us_stock' ? '0' : previous.purchase_fee_rate_percent,
      }
    })
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsLoading(true)
    setShowDetails(false)
    try {
      const request: BacktestRequest = {
        asset_type: form.asset_type,
        fund_code: form.fund_code,
        start_date: form.start_date,
        end_date: form.end_date,
        investment_amount: Number(form.investment_amount),
        frequency: form.frequency,
        purchase_fee_rate: Number(form.purchase_fee_rate_percent || 0) / 100,
        non_trading_day_policy: form.non_trading_day_policy,
      }
      const nextResult = await createBacktest(request)
      setResult(nextResult)
    } catch (requestError) {
      setResult(null)
      setError(requestError instanceof Error ? requestError.message : '回测失败，请稍后重试。')
    } finally {
      setIsLoading(false)
    }
  }

  const gainClass = result && result.total_return >= 0 ? 'positive' : 'negative'
  const resultCurrency = result?.currency ?? (result?.asset_type === 'us_stock' ? 'USD' : 'CNY')
  const resultPriceLabel = result?.price_label ?? (result?.asset_type === 'us_stock' ? '复权收盘价' : '单位净值')
  const resultShareLabel = result?.share_label ?? (result?.asset_type === 'us_stock' ? '股' : '份')

  return (
    <main className="page-shell">
      <header className="hero">
        <p className="eyebrow">本地假设回测</p>
        <h1>资产定投回测</h1>
        <p>支持国内场外基金和美股 ETF / 股票，按历史净值或价格测算固定金额定投表现。</p>
      </header>

      <section className="panel form-panel" aria-labelledby="form-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">回测参数</p>
            <h2 id="form-title">设置定投计划</h2>
          </div>
          <span className="data-tag">数据来源：AkShare</span>
        </div>
        <form onSubmit={submit}>
          <div className="asset-switch" aria-label="选择回测资产类型">
            {(Object.keys(assetOptions) as AssetType[]).map((assetType) => (
              <button
                key={assetType}
                type="button"
                className={form.asset_type === assetType ? 'active' : ''}
                onClick={() => switchAssetType(assetType)}
              >
                {assetOptions[assetType].title}
              </button>
            ))}
          </div>
          <div className="form-grid">
            <label>
              {currentAsset.codeLabel}
              <input
                value={form.fund_code}
                onChange={(event) => updateField('fund_code', event.target.value)}
                inputMode={form.asset_type === 'cn_fund' ? 'numeric' : 'text'}
                placeholder={currentAsset.codePlaceholder}
                required
              />
            </label>
            <label>
              {currentAsset.amountLabel}
              <input
                type="number"
                value={form.investment_amount}
                min="0.01"
                step="0.01"
                onChange={(event) => updateField('investment_amount', event.target.value)}
                required
              />
            </label>
            <label>
              开始日期
              <input
                type="date"
                value={form.start_date}
                onChange={(event) => updateField('start_date', event.target.value)}
                required
              />
            </label>
            <label>
              结束日期
              <input
                type="date"
                value={form.end_date}
                onChange={(event) => updateField('end_date', event.target.value)}
                required
              />
            </label>
            <label>
              定投频率
              <select
                value={form.frequency}
                onChange={(event) => updateField('frequency', event.target.value as Frequency)}
              >
                <option value="daily">每日（交易日）</option>
                <option value="weekly">每周</option>
                <option value="monthly">每月</option>
              </select>
            </label>
            <label>
              {currentAsset.feeLabel}
              <input
                type="number"
                value={form.purchase_fee_rate_percent}
                min="0"
                max="99.99"
                step="0.01"
                onChange={(event) => updateField('purchase_fee_rate_percent', event.target.value)}
              />
            </label>
            <label className="span-two">
              非交易日处理
              <select
                value={form.non_trading_day_policy}
                onChange={(event) =>
                  updateField('non_trading_day_policy', event.target.value as NonTradingDayPolicy)
                }
              >
                <option value="next_trading_day">顺延至下一交易日</option>
                <option value="skip">跳过本次定投</option>
              </select>
            </label>
          </div>
          <div className="form-footer">
            <p>{currentAsset.footerText}</p>
            <button type="submit" disabled={isLoading}>
              {isLoading ? currentAsset.loadingText : '开始回测'}
            </button>
          </div>
        </form>
      </section>

      {error && <div className="error-box" role="alert">{error}</div>}

      {result && (
        <section className="results" aria-live="polite">
          <div className="result-title">
            <div>
              <p className="eyebrow">回测结果</p>
              <h2>{result.fund_name ?? (result.asset_type === 'us_stock' ? result.fund_code : '未识别基金名称')} <span>{result.fund_code}</span></h2>
              <p>
                {assetOptions[result.asset_type].shortTitle} · {result.start_date} 至 {result.end_date} · {frequencyLabels[result.frequency]}定投 · 共 {result.investment_count} 笔
              </p>
            </div>
            <span className="source-tag">{resultPriceLabel}：{result.data_source}</span>
          </div>

          <div className="metric-grid">
            <article className="metric primary-metric">
              <p>最终市值</p>
              <strong>{formatMoney(result.final_value, resultCurrency)}</strong>
              <small>估值日 {result.valuation_date}</small>
            </article>
            <article className="metric">
              <p>累计投入</p>
              <strong>{formatMoney(result.total_invested, resultCurrency)}</strong>
              <small>每次 {formatMoney(result.investment_amount, resultCurrency)}</small>
            </article>
            <article className="metric">
              <p>总收益</p>
              <strong className={gainClass}>{formatMoney(result.total_return, resultCurrency)}</strong>
              <small className={gainClass}>{formatRate(result.total_return_rate)}</small>
            </article>
            <article className="metric">
              <p>年化收益率（XIRR）</p>
              <strong className={gainClass}>{formatRate(result.annualized_return)}</strong>
              <small>按实际现金流计算</small>
            </article>
          </div>

          <div className="result-layout">
            <article className="panel chart-panel">
              <div className="section-heading compact">
                <div>
                  <p className="eyebrow">资产变化</p>
                  <h3>累计投入与资产市值</h3>
                </div>
              </div>
              <LineChart curve={result.curve} currency={resultCurrency} />
            </article>
            <article className="panel summary-panel">
              <p className="eyebrow">持仓摘要</p>
              <dl>
                <div><dt>累计持有{resultShareLabel}</dt><dd>{formatNumber(result.total_shares)} {resultShareLabel}</dd></div>
                <div><dt>结束日{resultPriceLabel}</dt><dd>{formatNumber(result.ending_nav, 4)}</dd></div>
                <div><dt>{result.asset_type === 'us_stock' ? '交易费率' : '申购费率'}</dt><dd>{formatRate(result.purchase_fee_rate)}</dd></div>
                <div><dt>非交易日</dt><dd>{policyLabels[result.non_trading_day_policy]}</dd></div>
              </dl>
            </article>
          </div>

          <div className="details-section">
            <button className="secondary-button" onClick={() => setShowDetails((current) => !current)}>
              {showDetails ? '收起定投明细' : `查看定投明细（${result.transactions.length} 笔）`}
            </button>
            {showDetails && (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>计划日期</th>
                      <th>买入日期</th>
                      <th>{resultPriceLabel}</th>
                      <th>定投金额</th>
                      <th>买入{resultShareLabel}</th>
                      <th>累计{resultShareLabel}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.transactions.map((transaction, index) => (
                      <tr key={`${transaction.scheduled_date}-${transaction.trade_date}-${index}`}>
                        <td>{transaction.scheduled_date}</td>
                        <td>{transaction.trade_date}</td>
                        <td>{formatNumber(transaction.unit_nav, 4)}</td>
                        <td>{formatMoney(transaction.gross_amount, resultCurrency)}</td>
                        <td>{formatNumber(transaction.purchased_shares, 4)}</td>
                        <td>{formatNumber(transaction.cumulative_shares, 4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  )
}

export default App
