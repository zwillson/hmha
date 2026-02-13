"""Build filtered URLs for the WAAS jobs page.

Reference URL with all roles:
https://www.workatastartup.com/companies?demographic=any&hasEquity=any&hasSalary=any
&industry=any&interviewProcess=any&jobType=fulltime&layout=list-compact
&role=eng&role=design&role=science&role=any&role=sales&role=support
&role=marketing&role=product&role=operations&role=recruiting&role=finance
&role=legal&sortBy=created_desc&tab=any&usVisaNotRequired=any
"""

from __future__ import annotations

from urllib.parse import urlencode

WAAS_BASE_URL = "https://www.workatastartup.com/companies"

# Maps config role_category names to WAAS "role" query param values.
# These are the broad categories shown in the sidebar dropdown.
ROLE_CATEGORY_MAP = {
    "engineering": "eng",
    "design": "design",
    "product": "product",
    "science": "science",
    "sales": "sales",
    "marketing": "marketing",
    "support": "support",
    "operations": "operations",
    "recruiting": "recruiting",
    "finance": "finance",
    "legal": "legal",
    "all": "any",
    "any": "any",
}

# Maps config commitment names to WAAS "jobType" query param values.
JOB_TYPE_MAP = {
    "any": None,
    "all": None,
    "fulltime": "fulltime",
    "full-time": "fulltime",
    "intern": "internship",
    "internship": "internship",
    "contract": "contract",
}

# Maps config sort names to WAAS "sortBy" query param values.
SORT_MAP = {
    "most_active": "most_active",
    "newest": "created_desc",
    "created_desc": "created_desc",
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
    commitment: list[str] | None = None,
    role_categories: list[str] | None = None,
) -> str:
    """Construct the WAAS companies URL with query parameters from config.

    WAAS uses repeated params for multi-select (e.g. role=eng&role=design),
    so we build the query string manually instead of using urlencode for those.
    """
    # Start with simple single-value params
    parts: list[str] = []

    parts.append("layout=list-compact")
    parts.append("tab=any")

    # Commitment / jobType
    if commitment and len(commitment) > 0:
        # Use the commitment list from config
        for c in commitment:
            mapped = JOB_TYPE_MAP.get(c.lower())
            if mapped:
                parts.append(f"jobType={mapped}")
                break  # jobType is single-value
        # If all entries map to None (i.e. "All"), don't add jobType
    elif job_type and job_type != "any":
        mapped = JOB_TYPE_MAP.get(job_type.lower())
        if mapped:
            parts.append(f"jobType={mapped}")

    # Role categories (repeated params: role=eng&role=design&role=science)
    if role_categories:
        for cat in role_categories:
            mapped = ROLE_CATEGORY_MAP.get(cat.lower())
            if mapped:
                parts.append(f"role={mapped}")
                if mapped == "any":
                    break  # "All" means just role=any

    if remote and remote != "any":
        parts.append(f"remote={remote}")

    if location:
        parts.append(f"query={location.replace(' ', '+')}")

    if company_size and company_size != "any":
        parts.append(f"companySize={company_size}")

    if industries:
        parts.append(f"industry={','.join(industries)}")
    else:
        parts.append("industry=any")

    if visa_not_required and visa_not_required != "any":
        parts.append(f"usVisaNotRequired={visa_not_required}")
    else:
        parts.append("usVisaNotRequired=any")

    # Sort
    sort_val = SORT_MAP.get(sort_by, sort_by)
    parts.append(f"sortBy={sort_val}")

    # Defaults for other WAAS params
    parts.append("demographic=any")
    parts.append("hasEquity=any")
    parts.append("hasSalary=any")
    parts.append("interviewProcess=any")

    return f"{WAAS_BASE_URL}?{'&'.join(parts)}"
