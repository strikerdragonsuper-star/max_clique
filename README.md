# model-upgrade

Rust maximum clique solver and miner stack for [Bittensor subnet 83 (CliqueAI)](https://github.com/toptensor/CliqueAI).

The solver lives in **`crates/model_upgrade_core/`**. Python is only used for the Bittensor miner entrypoint and benchmark scripts (graph codec from CliqueAI).

## Project layout

```
model-upgrade/
├── Cargo.toml                      # Rust workspace
├── crates/
│   ├── model_upgrade_core/         # solver engine (edit here)
│   └── model_upgrade_py/           # PyO3 bindings → model_upgrade_rs
├── model_upgrade/
│   ├── miner.py                    # Bittensor miner (thin wrapper)
│   └── validator_store.py          # save validator queries
└── scripts/
    ├── benchmark.py                # offline benchmark
    └── preflight_submit.py         # pre-deploy checks
```

## Rust development

```bash
cargo build -p model_upgrade_core --release
cargo test -p model_upgrade_core
cd crates/model_upgrade_py && maturin develop --release
```

Tune solver constants in `crates/model_upgrade_core/src/solver.rs`.

## Deploy miner on subnet 83 (Linux)

Production mining requires **Ubuntu 24.04**, **Python 3.12+**, **Rust**, and a **public IP** with an open axon port.

### 1. Clone repos

```bash
mkdir -p ~/bittensor/83 && cd ~/bittensor/83
git clone https://github.com/toptensor/CliqueAI.git
git clone <your-model-upgrade-repo> model-upgrade
```

### 2. Register on subnet 83

```bash
btcli subnet register --netuid 83 --wallet.name <coldkey> --wallet.hotkey <hotkey> --subtensor.network finney
```

### 3. Configure

```bash
cd model-upgrade
cp miner.env.example miner.env
# Edit miner.env: WALLET_NAME, WALLET_HOTKEY, AXON_IP, AXON_PORT
```

### 4. Install and preflight

```bash
chmod +x install.sh start_miner.sh scripts/preflight.sh
./install.sh --skip-benchmark
./scripts/preflight.sh
python scripts/preflight_submit.py
```

### 5. Start miner

```bash
./start_miner.sh
```

Monitor:

```bash
pm2 logs miner-cliqueAI-sn83
pm2 status
```

The miner logs `Solver backend: rust` at startup.

### Firewall

Open your axon port (default `8091/tcp`) on the host and cloud security group.

## Local development (Windows)

```powershell
.\install.ps1 -SkipBenchmark
.\venv\Scripts\python.exe scripts\benchmark.py --validator-data
.\venv\Scripts\python.exe scripts\preflight_submit.py
```

## Benchmark

Uses local `test_data/` or `validator_data/` and saves results to `test_output/`:

```bash
source venv/bin/activate
python scripts/benchmark.py
python scripts/benchmark.py --validator-data
python scripts/benchmark.py --timeout 30
```

## Solver strategy

1. Multi-start greedy construction with varied vertex orderings
2. Randomized local search
3. Branch-and-bound on reduced cores when time remains
4. Dense-graph complement MIS mode for high-density instances
5. Maximality extension and validation before return

## Hardware (from CliqueAI)

| Resource | Recommended |
|----------|-------------|
| CPU | 8 cores @ 3.5 GHz |
| RAM | 16 GB+ |
| GPU | Optional (not required) |
| Network | 100 Mbps down / 20 Mbps up |
| OS | Ubuntu 24.04 |

## Operations

| Task | Command |
|------|---------|
| Restart miner | `pm2 restart miner-cliqueAI-sn83` |
| Stop miner | `pm2 stop miner-cliqueAI-sn83` |
| Update deps | `./install.sh --skip-benchmark && pm2 restart miner-cliqueAI-sn83` |
| Re-run checks | `./scripts/preflight.sh && python scripts/preflight_submit.py` |

Avoid frequent axon re-registration on-chain; recently updated miners are excluded from validator queries for ~1 epoch.
