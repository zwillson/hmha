"""CSV-based application tracking and deduplication.

Logs every application attempt (sent, skipped, error) to a CSV file
so we never apply to the same job twice.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from hmha.models import Application

logger = logging.getLogger("hmha")

CSV_HEADERS = [
    "job_id",
    "company_name",
    "job_title",
    "url",
    "message_sent",
    "status",
    "timestamp",
    "notes",
]


class ApplicationTracker:
    """Read/write application records to CSV with deduplication."""

    def __init__(self, csv_path: Path | str = "data/applications.csv"):
        self._csv_path = Path(csv_path)
        self._applied_ids: set[str] = set()
        self._load_existing()

    def _load_existing(self) -> None:
        """Load previously recorded job IDs into memory for fast lookup."""
        if not self._csv_path.exists():
            return

        with open(self._csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                job_id = row.get("job_id", "")
                status = row.get("status", "")
                # Only skip jobs we actually sent applications to
                if status == "sent" and job_id:
                    self._applied_ids.add(job_id)

        logger.info("Loaded %d previously applied job IDs.", len(self._applied_ids))

    def has_applied(self, job_id: str) -> bool:
        """Check if we've already sent an application to this job."""
        return job_id in self._applied_ids

    def record(self, application: Application) -> None:
        """Append an application record to the CSV."""
        is_new_file = not self._csv_path.exists() or self._csv_path.stat().st_size == 0

        with open(self._csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if is_new_file:
                writer.writeheader()

            writer.writerow({
                "job_id": application.job.job_id,
                "company_name": application.job.company.name,
                "job_title": application.job.title,
                "url": application.job.url,
                "message_sent": application.message,
                "status": application.status.value,
                "timestamp": application.timestamp.isoformat(),
                "notes": application.notes,
            })

        # Update in-memory set
        if application.status.value == "sent":
            self._applied_ids.add(application.job.job_id)

        logger.debug(
            "Recorded: %s at %s [%s]",
            application.job.title,
            application.job.company.name,
            application.status.value,
        )

    def get_summary(self) -> dict[str, int]:
        """Return counts by status from the CSV."""
        counts: dict[str, int] = {}
        if not self._csv_path.exists():
            return counts

        with open(self._csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("status", "unknown")
                counts[status] = counts.get(status, 0) + 1

        return counts
