#!/usr/bin/env python3
"""Probe a subnet 83 miner axon for reachability."""

import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIQUE_ROOT = ROOT.parent / "CliqueAI"
sys.path.insert(0, str(CLIQUE_ROOT))

HOST = "144.91.90.139"
PORT = 8091
ENDPOINT = f"http://{HOST}:{PORT}/MaximumCliqueOfLambdaGraph"


def tcp_check() -> bool:
    with socket.create_connection((HOST, PORT), timeout=10):
        return True


def load_sample_payload() -> dict:
    sample = ROOT / "test_data" / "sample.json"
    if sample.exists():
        with sample.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "uuid": data.get("uuid", "probe-test"),
            "label": data.get("label", "general"),
            "number_of_nodes": data["number_of_nodes"],
            "encoded_matrix": data["encoded_matrix"],
            "timeout": 30.0,
        }
    return {
        "uuid": "probe-test",
        "label": "general",
        "number_of_nodes": 3,
        "encoded_matrix": "    $)",
        "timeout": 30.0,
    }


def http_post_probe() -> tuple[int | None, str]:
    payload = json.dumps(load_sample_payload()).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(200_000).decode("utf-8", errors="replace")
            return response.status, body[:2000]
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        return exc.code, body
    except Exception as exc:
        return None, str(exc)


def main() -> None:
    print(f"Probing miner axon at {HOST}:{PORT}")
    print("-" * 60)

    try:
        tcp_ok = tcp_check()
        print(f"TCP {HOST}:{PORT}  -> {'OPEN' if tcp_ok else 'CLOSED'}")
    except OSError as exc:
        print(f"TCP {HOST}:{PORT}  -> FAILED ({exc})")
        tcp_ok = False

    print(f"POST {ENDPOINT}")
    status, body = http_post_probe()
    if status is None:
        print(f"HTTP response     -> FAILED ({body})")
    else:
        print(f"HTTP response     -> {status}")
        print(f"Body preview      -> {body[:500]}")

    print("-" * 60)
    if not tcp_ok:
        print("Result: port not reachable (firewall, miner down, or wrong IP/port)")
        sys.exit(1)
    if status in (200, 401, 403, 422):
        print("Result: axon is running and responding")
        if status == 200:
            print("        miner accepted the request (unsigned probe may still fail auth)")
        elif status in (401, 403):
            print("        auth rejected unsigned probe (expected without validator keys)")
        elif status == 422:
            print("        validation error on payload (axon alive, check synapse format)")
        sys.exit(0)
    print("Result: port open but axon did not return a normal HTTP response")
    sys.exit(1)


if __name__ == "__main__":
    main()
