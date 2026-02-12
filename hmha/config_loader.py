"""Load and validate the YAML configuration file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class UserProfile:
    name: str
    education: str
    experience_summary: str
    skills: list[str]
    interests: str
    location_preference: str
    resume_highlights: list[str]
    personality_notes: str = ""
    linkedin: str = ""
    availability: str = ""


@dataclass
class SearchFilters:
    job_type: str = "any"
    roles: list[str] = field(default_factory=list)
    remote: str = "any"
    location: str = ""
    company_size: str = "any"
    industries: list[str] = field(default_factory=list)
    visa_not_required: str = "any"
    sort_by: str = "most_active"
    allowed_locations: list[str] = field(default_factory=list)


@dataclass
class Config:
    user_profile: UserProfile
    search_filters: SearchFilters
    message_style: str = ""
    max_applications_per_session: int = 25
    delay_min_seconds: float = 8.0
    delay_max_seconds: float = 20.0
    browser_headless: bool = False
    browser_slow_mo: int = 50
    anthropic_api_key: str = ""


def load_config(config_path: Path) -> Config:
    """Load config.yaml and .env, validate required fields, return Config."""
    load_dotenv()

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            "Copy config.example.yaml to config.yaml and fill in your details."
        )

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    # Parse user profile
    prof = raw.get("user_profile", {})
    required_profile_fields = ["name", "education", "experience_summary", "skills"]
    for field_name in required_profile_fields:
        if not prof.get(field_name):
            raise ValueError(f"Missing required user_profile field: {field_name}")

    user_profile = UserProfile(
        name=prof["name"],
        education=prof["education"],
        experience_summary=prof["experience_summary"],
        skills=prof.get("skills", []),
        interests=prof.get("interests", ""),
        location_preference=prof.get("location_preference", ""),
        resume_highlights=prof.get("resume_highlights", []),
        personality_notes=prof.get("personality_notes", ""),
        linkedin=prof.get("linkedin", ""),
        availability=prof.get("availability", ""),
    )

    # Parse search filters
    filt = raw.get("search_filters", {})
    search_filters = SearchFilters(
        job_type=filt.get("job_type", "any"),
        roles=filt.get("roles", []),
        remote=filt.get("remote", "any"),
        location=filt.get("location", ""),
        company_size=filt.get("company_size", "any"),
        industries=filt.get("industries", []),
        visa_not_required=filt.get("visa_not_required", "any"),
        sort_by=filt.get("sort_by", "most_active"),
        allowed_locations=filt.get("allowed_locations", []),
    )

    # Parse settings
    settings = raw.get("settings", {})
    delay = settings.get("delay_between_applications", {})

    # API key from environment only
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not found in environment.\n"
            "Set it in .env or export it: export ANTHROPIC_API_KEY=sk-..."
        )

    return Config(
        user_profile=user_profile,
        search_filters=search_filters,
        message_style=raw.get("message_style", ""),
        max_applications_per_session=settings.get("max_applications_per_session", 25),
        delay_min_seconds=delay.get("min_seconds", 8.0),
        delay_max_seconds=delay.get("max_seconds", 20.0),
        browser_headless=settings.get("browser_headless", False),
        browser_slow_mo=settings.get("browser_slow_mo", 50),
        anthropic_api_key=api_key,
    )
