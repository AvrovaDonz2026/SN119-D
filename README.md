# SN119 demo

This repository contains a small, standard-library-only pipeline for an SN119
data-patch demo. It records provenance, applies deterministic quality gates,
evaluates a frozen local baseline, and compares four offline miner policies.
It never connects to a wallet or claims real TAO earnings.

```bash
cd /Users/zxy/SN119-D
export PYTHONPATH=src
python -m sn119_demo.cli seed --reports-dir reports
python -m sn119_demo.cli generate --reports-dir reports --count 8
python -m sn119_demo.cli validate --reports-dir reports
python -m sn119_demo.cli evaluate --reports-dir reports
python -m sn119_demo.cli simulate --reports-dir reports
python -m sn119_demo.cli report --reports-dir reports
```

Each command prints JSON and writes `<stage>.json` under `reports/`. The
`generate` stage emits add/update/skip patch operations; `validate` reports
rights, privacy, duplicate, contamination, and leakage findings; `evaluate`
uses `sn119-frozen-v1` proxy metrics; and `simulate` compares
`full_generation`, `high_confidence`, `provenance_first`, and `quality_gated`.
All market values are offline synthetic units, not real TAO earnings or a
profit forecast.

