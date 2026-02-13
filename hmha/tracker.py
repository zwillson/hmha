"""CSV-based application tracking and deduplication.

Maintains two separate CSV files:
  - applications.csv: Real confirmed sends (status=sent)
  - dry_runs.csv: Dry run attempts (status=dry_run)

Skipped and errored jobs are logged to whichever file matches
the current run mode (dry_run or live).
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
    "company_website",
    "founders",
    "message_sent",
    "status",
    "timestamp",
    "notes",
]


class ApplicationTracker:
    """Read/write application records to CSV with deduplication."""

    def __init__(
        self,
        data_dir: Path | str = "data",
        dry_run: bool = False,
    ):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._applications_path = self._data_dir / "applications.csv"
        self._dry_runs_path = self._data_dir / "dry_runs.csv"
        self._dry_run = dry_run

        # IDs of jobs we've actually sent real applications to
        self._applied_ids: set[str] = set()
        self._load_existing()

    def _load_existing(self) -> None:
        """Load previously sent job IDs into memory for fast lookup."""
        # Always load from the real applications file for deduplication
        if not self._applications_path.exists():
            return

        with open(self._applications_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                job_id = row.get("job_id", "")
                status = row.get("status", "")
                if status == "sent" and job_id:
                    self._applied_ids.add(job_id)

        logger.info("Loaded %d previously applied job IDs.", len(self._applied_ids))

    def has_applied(self, job_id: str) -> bool:
        """Check if we've already sent a real application to this job."""
        return job_id in self._applied_ids

    def record(self, application: Application) -> None:
        """Append an application record to the appropriate CSV."""
        # Dry runs and their skips/errors go to dry_runs.csv
        # Real sends and their skips/errors go to applications.csv
        if self._dry_run:
            csv_path = self._dry_runs_path
        else:
            csv_path = self._applications_path

        is_new_file = not csv_path.exists() or csv_path.stat().st_size == 0

        with open(csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if is_new_file:
                writer.writeheader()

            founders_str = ", ".join(
                f.name for f in application.job.company.founders
            ) if application.job.company.founders else ""

            writer.writerow({
                "job_id": application.job.job_id,
                "company_name": application.job.company.name,
                "job_title": application.job.title,
                "url": application.job.url,
                "company_website": application.job.company.website or "",
                "founders": founders_str,
                "message_sent": application.message,
                "status": application.status.value,
                "timestamp": application.timestamp.isoformat(),
                "notes": application.notes,
            })

        # Update in-memory set for real sends only
        if application.status.value == "sent":
            self._applied_ids.add(application.job.job_id)

        logger.debug(
            "Recorded: %s at %s [%s] -> %s",
            application.job.title,
            application.job.company.name,
            application.status.value,
            csv_path.name,
        )

    def get_summary(self) -> dict[str, int]:
        """Return counts by status from the current run's CSV."""
        csv_path = self._dry_runs_path if self._dry_run else self._applications_path
        counts: dict[str, int] = {}
        if not csv_path.exists():
            return counts

        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("status", "unknown")
                counts[status] = counts.get(status, 0) + 1

        return counts

    def get_full_summary(self) -> dict[str, dict[str, int]]:
        """Return counts for both real and dry-run files."""
        result = {}
        for label, path in [("live", self._applications_path), ("dry_run", self._dry_runs_path)]:
            counts: dict[str, int] = {}
            if path.exists():
                with open(path, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        status = row.get("status", "unknown")
                        counts[status] = counts.get(status, 0) + 1
            result[label] = counts
        return result
