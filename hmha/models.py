"""Data models for jobs, companies, and applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ApplicationStatus(Enum):
    SENT = "sent"
    SKIPPED = "skipped"
    ERROR = "error"
    DRY_RUN = "dry_run"


@dataclass
class Company:
    name: str
    description: str
    yc_batch: str = ""
    industry: str = ""
    size: str = ""
    url: str = ""


@dataclass
class Job:
    job_id: str
    title: str
    company: Company
    url: str
    description: str = ""
    requirements: str = ""
    location: str = ""
    job_type: str = ""
    role_category: str = ""
    salary_range: str = ""
    culture_notes: str = ""


@dataclass
class Application:
    job: Job
    message: str
    status: ApplicationStatus
    timestamp: datetime = field(default_factory=datetime.now)
    notes: str = ""
