# BTC Reflex Engine

**Behavioral Structure Rotation Intelligence**
Phase 1 — Observer Mode

---

## What This Is

BTC Reflex Engine is a secondary tactical intelligence system that observes
how BTC behaves inside market structures. It is NOT a trade signal generator,
breakout predictor, or indicator aggregator.

It observes:
- Structure type and phase (4H context)
- Boundary interaction behavior (rotation, rejection, absorption)
- Change of Character in swing sequences (CHoCH)
- Volatility compression/expansion state
- Brain Ops macro context (read-only)

The engine describes what the market is doing. The trader decides.

---

## What This Is Not

- Not a replacement for BTC Brain or BTC Brain Ops
- Not an auto-trading bot
- Not an indicator stacking system
- Not a prediction AI
- Not a signal service

---

## System Boundaries

```
BTC Signal Alert System  ← untouched, separate
BTC Brain                ← untouched, separate
BTC Brain Ops            ← untouched, separate
        ↓  GET /brain-state (read-only)
BTC Reflex Engine        ← this system
        ↓
BTC Reflex Telegram Bot  ← separate bot token
```

---

## Phase 1 Scope

- [x] Structure detection (4H + 1H)
- [x] Rotation boundary behavior observation
- [x] CHoCH detection
- [x] Volatility compression/expansion state
- [x] Brain Ops read-only integration
- [x] Behavioral context assembly (not score-based)
- [x] Telegram behavioral narrative alerts
- [x] Database logging (observer records)
- [x] Safety test suite

Phase 2 (future):
- Liquidity sweep detection (trade stream)
- Orderflow / delta analysis
- Trapped trader detection refinement

---

## Deployment (Separate Railway Project)

1. Create a **new** Railway project — never deploy into Brain Ops project
2. Add a **new** Postgres service in this project
3. Set all env vars from `.env.example`
4. Deploy from this repo root

**Never share Railway environment, secrets, or services with Brain Ops.**

---

## Environment Variables

See `.env.example` for full reference.

Critical isolation rules:
- `REFLEX_DATABASE_URL` — separate Postgres, never Brain Ops DB
- `REFLEX_TELEGRAM_BOT_TOKEN` — separate bot, never Brain bot
- `BRAIN_STATE_URL` — HTTP read-only, Brain Ops `/brain-state` endpoint

---

## Brain Ops Integration

**One file change to Brain Ops:**

Copy `btc-brain-ops-patch/reflex_endpoint.py` into Brain Ops, then add
one line to register the router. See `btc-brain-ops-patch/PATCH_README.md`.

This is the only modification to Brain Ops. It is fully reversible.

---

## Alert Philosophy

Alerts describe behavioral context — not commands.

Example alert:
```
━━━ BTC REFLEX OBSERVATION ━━━
Symbol: BTCUSDT  |  Price: $67,450.00

📊 4H STRUCTURAL CONTEXT
  Structure:  Descending Wedge
  Phase:      Compression
  Location:   At Lower Boundary
  Range:      $65,200 — $70,800 (8.3%)
  Clarity:    High

⏱ 1H TACTICAL CONTEXT
  Structure:  Range
  Phase:      Bouncing
  Location:   At Lower Boundary

🔄 ROTATION BEHAVIOR
  Near lower boundary (2.1% from level)
  Signals:    momentum decaying, absorption visible, prior sweep of level

🔀 STRUCTURE CHARACTER
  Sequence:   Bullish Sequence
  CHoCH:      none — sequence intact

📉 VOLATILITY STATE
  State:      Compressing
  ATR ratio:  0.71x baseline
  Streak:     6 candles compressing

🧠 BRAIN OPS CONTEXT
  Regime:     Ranging
  Bias:       Neutral
  Confidence: 62%
  Risk mode:  Normal

⚖️  BEHAVIORAL WEIGHT
  Weight: 0.61 / 1.00 — Significant

─── Observer Mode — No Execution ───
Reflex observes. The trader decides.
```

---

## Running Locally

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env with your values
python -m app.main
```

## Tests

```bash
pytest tests/test_safety.py -v
```

All 7 safety tests must pass before deployment.
