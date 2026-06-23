#!/usr/bin/env python3
"""Download CliqueAI subnet 83 test graphs from GitHub."""

from pathlib import Path
from urllib.request import urlretrieve

REPO_BASE = "https://raw.githubusercontent.com/toptensor/CliqueAI/main/test_data"
TEST_FILES = [
    "sample.json",
    "general_0.1.json",
    "general_0.2.json",
    "general_0.4.json",
]


def main() -> None:
    dest = Path(__file__).resolve().parents[1] / "test_data"
    dest.mkdir(parents=True, exist_ok=True)

    for filename in TEST_FILES:
        url = f"{REPO_BASE}/{filename}"
        target = dest / filename
        print(f"Downloading {filename}...")
        urlretrieve(url, target)

    print(f"Saved {len(TEST_FILES)} files to {dest}")


if __name__ == "__main__":
    main()
