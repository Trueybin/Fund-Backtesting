# 资产定投回测工具

本项目是一个本地运行的定投测算 MVP。它使用 AkShare 获取历史数据，按固定金额、日/周/月频率模拟定投，并展示收益和每日资产曲线。

当前支持两类资产：

- 国内场外基金：使用开放式基金历史单位净值。
- 美股 ETF / 股票：使用美股历史价格，适合测试 VOO、QQQM 等标的。

第一版仅用于假设回测：不连接券商、不读取账户、不下单，也暂未处理基金分红与赎回费。

## 启动

需要 Python 3.10+、Node.js 24+ 和 npm。

推荐直接使用根目录的一键启动脚本：

```bash
./start.sh
```

脚本会自动准备后端虚拟环境、安装缺失依赖，并同时启动后端和前端。启动完成后打开：

```text
http://127.0.0.1:5173
```

停止服务时，在启动脚本所在终端按 `Ctrl+C`。

如果端口被占用，可以这样改端口：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=5174 ./start.sh
```

如需重新安装依赖：

```bash
FORCE_INSTALL=1 ./start.sh
```

也可以手动分别启动：

```bash
# 终端 1：后端
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
# 终端 2：前端
cd frontend
npm install
npm run dev
```

然后在浏览器打开 Vite 显示的本地地址（通常是 `http://localhost:5173`）。

## API

`POST /api/backtests`

请求示例：

```json
{
  "asset_type": "cn_fund",
  "fund_code": "710001",
  "start_date": "2021-01-01",
  "end_date": "2025-12-31",
  "investment_amount": 1000,
  "frequency": "monthly",
  "purchase_fee_rate": 0,
  "non_trading_day_policy": "next_trading_day"
}
```

美股 ETF / 股票请求示例：

```json
{
  "asset_type": "us_stock",
  "fund_code": "VOO",
  "start_date": "2021-01-01",
  "end_date": "2025-12-31",
  "investment_amount": 59,
  "frequency": "monthly",
  "purchase_fee_rate": 0,
  "non_trading_day_policy": "next_trading_day"
}
```

`purchase_fee_rate` 使用小数表达费率，例如 `0.0015` 代表 0.15%。前端以百分比形式输入并自动转换。

## 计算口径

- 国内场外基金使用单位净值；美股 ETF / 股票使用复权收盘价。
- 每笔净申购金额 = 定投金额 / (1 + 费率)
- 买入份额/股数 = 净申购金额 / 当日单位净值或价格
- 累计投入按每笔定投金额（含申购费）累计
- 每日定投按可买入交易日执行，不按自然日补买周末、节假日或调休工作日；美股节假日通过实际行情日期自然排除
- 每周、每月计划遇到非交易日时，可选择顺延至下一个交易日或跳过；顺延不会超出回测结束日
- 若结束日不是有数据的交易日，最终估值使用结束日前最近一个可用交易日

历史净值/价格会写入 `backend/data/fund_cache.db`，同一资产的可覆盖请求会在 24 小时内直接使用本地缓存。

## 同步到 GitHub

项目根目录提供了 `sync-github.sh`，默认推送到：

```text
https://github.com/Trueybin/Fund-Backtesting.git
```

首次使用前，请先在本机设置 Git 用户信息：

```bash
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

然后执行：

```bash
./sync-github.sh "提交说明"
```

脚本不会保存 GitHub token。首次 push 时如果 Git 要求登录，请按提示输入 GitHub 用户名，并在密码位置输入有效 token；建议使用系统钥匙串或 Git Credential Manager 保存凭据。

## 部署到公网：Vercel

本项目已适配 Vercel：

- 前端：构建 `frontend` 下的 Vite 应用
- 后端：通过 `api/index.py` 暴露 FastAPI Python Function
- API 路由：`/api/*`
- 生产环境前端默认请求同域 API；本地开发仍默认请求 `http://127.0.0.1:8000`

Vercel 免费方案不需要绑卡，但它是 Serverless，不是常驻进程。没人访问时函数不会一直运行；第一次访问或较长时间后访问可能有冷启动。SQLite 缓存使用 `/tmp` 临时目录，只作为加速缓存；冷启动、重新部署后缓存丢失是正常的，不影响计算结果。

部署步骤：

1. 同步代码到 GitHub：

   ```bash
   ./sync-github.sh "Add Vercel deployment"
   ```

2. 打开 Vercel Dashboard。
3. 选择 `Add New...` → `Project`。
4. 导入 `Trueybin/Fund-Backtesting` 仓库。
5. Root Directory 保持仓库根目录。
6. Framework Preset 可以选择 `Other` 或让 Vercel 自动识别。
7. Build Command 使用根目录 `vercel.json` 中的配置：`cd frontend && npm run build`。
8. Output Directory 使用：`frontend/dist`。
9. 点击 Deploy。

部署完成后，Vercel 会给你一个 `https://xxx.vercel.app` 地址。访问这个地址就是前端页面，页面内部会请求同域的 `/api/backtests`。
