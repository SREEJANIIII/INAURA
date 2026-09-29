"""Seed the synthetic course-alignment fixture (demo data only).

Manual use (never pytest): idempotently creates the synthetic institution,
course, cohorts, demo learners, skill signals, and demand rows used to test
course/industry alignment end to end. Safe to run repeatedly — existing
synthetic rows are reused, never duplicated.

    cd backend
    python scripts/seed_synthetic_alignment.py

Only rows scoped to the synthetic codes/provider/demo emails are touched.
Real students, employers, applications, and placements are never modified.
Every seeded row carries data_origin='demo_seeded'.

Exit codes: 0 seeded (or already present), 1 failure (e.g. Supabase not
configured, taxonomy rows missing).
"""

import json
import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from app.services.synthetic_alignment_seed import seed_synthetic_alignment
    except ImportError as exc:
        print(f"Cannot import seed module: {exc}")
        return 1
    try:
        summary = seed_synthetic_alignment()
    except Exception as exc:
        print(f"Synthetic seed failed: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(summary, indent=2, default=str))
    print("Seed complete — all rows data_origin='demo_seeded'.")
    print("Test in the UI: Industry Intelligence -> Course Alignment,")
    print("institution 'INAURA Synthetic Institute', course")
    print("'Full Stack Engineering — Synthetic 2026', cohort")
    print("'Full Stack Engineering — Synthetic Batch A', role 'Software Engineer',")
    print("India / Karnataka / Bengaluru, then Evaluate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
