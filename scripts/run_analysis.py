"""Run the full analysis pipeline: quick filter + geometric analysis."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.analysis.quick_filter import run as run_quick_filter
from backend.analysis.batch_processor import run as run_batch

if __name__ == "__main__":
    print("=" * 60)
    print("Step 1: Quick Filter Classification")
    print("=" * 60)
    run_quick_filter()

    print("\n" + "=" * 60)
    print("Step 2: Geometric Subdivision Analysis")
    print("=" * 60)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_batch(max_workers=4, limit=limit)

    print("\n" + "=" * 60)
    print("Pipeline Complete!")
    print("=" * 60)
