"""Build filtered URLs for the WAAS jobs page."""

from __future__ import annotations

from urllib.parse import urlencode

WAAS_BASE_URL = "https://www.workatastartup.com/jobs"

# Maps config role names to WAAS query parameter values
ROLE_MAP = {
    "software-engineer": "software-engineer",
    "full-stack-engineer": "full-stack-engineer",
    "backend-engineer": "backend-engineer",
    "frontend-engineer": "frontend-engineer",
    "data-scientist": "data-scientist",
    "machine-learning-engineer": "machine-learning-engineer",
    "devops": "devops-engineer",
    "mobile-engineer": "mobile-engineer",
    "design": "designer",
    "product-manager": "product-manager",
}


def build_jobs_url(
    job_type: str = "any",
    roles: list[str] | None = None,
    remote: str = "any",
    location: str = "",
    company_size: str = "any",
    industries: list[str] | None = None,
    visa_not_required: str = "any",
    sort_by: str = "most_active",
) -> str:
    """Construct the WAAS jobs URL with query parameters from config filters.

    Returns the full URL string ready for navigation.
    """
    params: dict[str, str] = {}

    if job_type and job_type != "any":
        params["jobType"] = job_type

    if roles:
        # WAAS accepts multiple role params as comma-separated or repeated keys.
        # Use the mapped value if available, otherwise pass through raw.
        mapped = [ROLE_MAP.get(r, r) for r in roles]
        params["role"] = ",".join(mapped)

    if remote and remote != "any":
        params["remote"] = remote

    if location:
        params["query"] = location

    if company_size and company_size != "any":
        params["companySize"] = company_size

    if industries:
        params["industry"] = ",".join(industries)

    if visa_not_required and visa_not_required != "any":
        params["usVisaNotRequired"] = visa_not_required

    if sort_by:
        params["sortBy"] = sort_by

    if not params:
        return WAAS_BASE_URL

    return f"{WAAS_BASE_URL}?{urlencode(params)}"
