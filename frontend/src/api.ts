import type { BacktestRequest, BacktestResult } from './types'

function defaultApiBaseUrl(): string {
  if (typeof window !== 'undefined' && ['localhost', '127.0.0.1'].includes(window.location.hostname)) {
    return 'http://127.0.0.1:8000'
  }
  return ''
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? defaultApiBaseUrl()

export async function createBacktest(request: BacktestRequest): Promise<BacktestResult> {
  const response = await fetch(`${API_BASE_URL}/api/backtests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  const body: unknown = await response.json()
  if (!response.ok) {
    const message =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String(body.detail)
        : '回测请求失败，请检查后端服务。'
    throw new Error(message)
  }
  return body as BacktestResult
}
