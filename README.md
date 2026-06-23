# model-upgrade

Competitive maximum clique solver and miner stack for [Bittensor subnet 83 (CliqueAI)](https://github.com/toptensor/CliqueAI).

## Deploy miner on subnet 83 (Linux)

Production mining requires **Ubuntu 24.04**, **Python 3.12+**, and a **public IP** with an open axon port.

### 1. Clone repos

```bash
mkdir -p ~/bittensor/83 && cd ~/bittensor/83
git clone https://github.com/toptensor/CliqueAI.git
git clone <your-model-upgrade-repo> model-upgrade   # or copy this folder
```

Layout:

```
83/
├── CliqueAI/       # upstream subnet repo (miner entrypoint)
└── model-upgrade/  # your solver + deploy scripts
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

The miner uses `synapse.timeout` from validators (sampled from `{6, 7.5, 10, 15, 30}` seconds per tier) and runs the `model_upgrade` solver.

### Firewall

Open your axon port (default `8091/tcp`) on the host and cloud security group.

## Local development (Windows)

Solver-only install and benchmark (no Bittensor stack on Windows):

```powershell
.\install.ps1
.\venv\Scripts\python.exe scripts\benchmark.py
```

## Benchmark

Uses local `test_data/` and saves results to `test_output/`:

```bash
source venv/bin/activate
python scripts/benchmark.py
python scripts/benchmark.py --timeout 30
python scripts/download_test_data.py
```

## Solver strategy

1. Multi-start greedy construction with varied vertex orderings
2. Randomized local search
3. Branch-and-bound on graphs with ≤420 nodes when time remains
4. Maximality extension and validator-compatible validation before return

Tune defaults in `model_upgrade/solver.py`.

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
| Re-run checks | `./scripts/preflight.sh` |

Avoid frequent axon re-registration on-chain; recently updated miners are excluded from validator queries for ~1 epoch.
