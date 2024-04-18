"""Safely inspect or prune audits older than a retention period.

Dry-run is the default. Add --apply to delete; linked human reviews are removed with audits.
"""
# ruff: noqa: E402

import sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import argparse
from datetime import UTC, datetime, timedelta

from backend.database import SessionLocal, init_db
from backend.models import AuditRecord, HumanReview, ProviderUsage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=365, help="retain records newer than this many days"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform deletion; without this flag only report counts",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be >= 1")
    init_db()
    db = SessionLocal()
    cutoff = datetime.now(UTC) - timedelta(days=args.days)
    old_ids = [
        row[0] for row in db.query(AuditRecord.id).filter(AuditRecord.created_at < cutoff).all()
    ]
    reviews = (
        db.query(HumanReview).filter(HumanReview.audit_id.in_(old_ids)).count() if old_ids else 0
    )
    usage_count = db.query(ProviderUsage).filter(ProviderUsage.created_at < cutoff).count()
    print(
        f"Cutoff: {cutoff.isoformat()} | audits={len(old_ids)} | linked reviews={reviews} | provider usage rows={usage_count}"
    )
    if args.apply:
        if old_ids:
            db.query(HumanReview).filter(HumanReview.audit_id.in_(old_ids)).delete(
                synchronize_session=False
            )
            db.query(AuditRecord).filter(AuditRecord.id.in_(old_ids)).delete(
                synchronize_session=False
            )
        db.query(ProviderUsage).filter(ProviderUsage.created_at < cutoff).delete(
            synchronize_session=False
        )
        db.commit()
        print("Deletion complete.")
    else:
        print("Dry run only. Re-run with --apply to delete these records.")
    db.close()


if __name__ == "__main__":
    main()
