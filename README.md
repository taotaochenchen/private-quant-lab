# Private Quant Lab

This project currently contains one provider-neutral chat model interface.
The model name determines which provider endpoint and API key are used.

## Setup

```bash
python3 -m unittest discover -s tests -v
```

For live smoke tests, copy `.env.example` to `.env` and set the relevant API
key locally. Do not commit `.env`.

```text
MODEL_NAME=deepseek-v4-flash
DEEPSEEK_API_KEY=...
```

or:

```text
MODEL_NAME=gpt-5.6-sol
OPENAI_API_KEY=...
```

## Interface

Application code should depend on `ChatModel` only:

```python
from private_quant_lab.models import ChatMessage, build_chat_model, load_model_config

model = build_chat_model(load_model_config())
response = model.complete([ChatMessage(role="user", content="Say hello.")])
print(response.content)
```

## Live Smoke Test

Run either provider after filling `.env`:

```bash
python3 scripts/smoke_models.py --model deepseek-v4-flash
python3 scripts/smoke_models.py --model gpt-5.6-sol
```

You can keep both API keys in `.env` and switch models from the command line
without editing the file.

## Mock Quant Tool ReAct Test

The first mocked tool environment includes common quant-agent tools:

- `market_snapshot`
- `price_history`
- `technical_indicators`
- `universe_screen`
- `fundamentals`
- `news_sentiment`
- `macro_indicator`
- `portfolio_risk`
- `strategy_backtest`
- `paper_order`
- `web_search`

Run a DeepSeek-backed ReAct flow. By default, DeepSeek also simulates the tool
observations:

```bash
python3 scripts/smoke_quant_react.py
python3 scripts/smoke_quant_react.py "用 mock 工具分析一下 SPY 的趋势和风险"
```

Run an individual tool with local deterministic output:

```bash
python3 scripts/smoke_quant_tools.py market_snapshot '{"symbol": "NVDA"}'
python3 scripts/smoke_quant_tools.py web_search '{"query": "NVDA AI demand", "limit": 3}'
```

Run an individual tool with DeepSeek-simulated observation output:

```bash
python3 scripts/smoke_quant_tools.py --llm-observation web_search '{"query": "NVDA AI demand", "limit": 3}'
```

This validates Agent flow only. The mocked observations are not real market data
and should not be used for investment decisions.
