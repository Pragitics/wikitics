#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.benchmarks.openrouter_model_benchmark import main


if __name__ == "__main__":
    raise SystemExit(main())
