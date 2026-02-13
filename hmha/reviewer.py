"""Terminal-based review interface for application messages.

Shows job context and the generated message, then lets the user
approve, edit, skip, or quit before each application is sent.
Also handles multi-job selection when a company has multiple postings.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from enum import Enum

from hmha.models import Job


class ReviewDecision(Enum):
    APPROVE = "approve"
    EDIT = "edit"
    SKIP = "skip"
    QUIT = "quit"


# ANSI color helpers
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

NOT_FOUND = f"{DIM}{RED}Couldn't be found by HMHA{RESET}"


class MessageReviewer:
    """Interactive terminal UI for reviewing generated messages."""

    def review(
        self,
        job: Job,
        message: str,
        job_number: int,
        total_jobs: int,
    ) -> tuple[ReviewDecision, str]:
        """Display job context and message, return user's decision and final message.

        Returns:
            (decision, message) where message may be edited by the user.
        """
        self._display_header(job_number, total_jobs)
        self._display_job_context(job)
        self._display_message(message)

        while True:
            choice = input(
                f"\n{BOLD}[A]pprove  [E]dit  [S]kip  [Q]uit{RESET} > "
            ).strip().lower()

            if choice in ("a", "approve", ""):
                return ReviewDecision.APPROVE, message
            elif choice in ("e", "edit"):
                message = self._edit_message(message)
                self._display_message(message)
                # After editing, loop back to let them approve or edit again
            elif choice in ("s", "skip"):
                return ReviewDecision.SKIP, message
            elif choice in ("q", "quit"):
                return ReviewDecision.QUIT, message
            else:
                print("Invalid choice. Use A/E/S/Q.")

    def _display_header(self, job_number: int, total_jobs: int) -> None:
        print(f"\n{'=' * 60}")
        print(f"{BOLD}{CYAN} Job {job_number}/{total_jobs}{RESET}")
        print(f"{'=' * 60}")

    def _display_job_context(self, job: Job) -> None:
        company = job.company

        # Company name + YC batch
        name_line = company.name if company.name and company.name != "Unknown" else NOT_FOUND
        if company.yc_batch:
            name_line += f" ({company.yc_batch})"
        print(f"{BOLD}Company:{RESET}    {name_line}")

        # Role
        role_line = job.title if job.title and job.title != "Unknown Role" else NOT_FOUND
        print(f"{BOLD}Role:{RESET}       {role_line}")

        # Location
        print(f"{BOLD}Location:{RESET}   {job.location or NOT_FOUND}")

        # Industry & size on one line
        industry = company.industry or NOT_FOUND
        size = f"{company.size} people" if company.size else NOT_FOUND
        print(f"{BOLD}Industry:{RESET}   {industry}  |  {BOLD}Size:{RESET} {size}")

        # Salary
        print(f"{BOLD}Salary:{RESET}     {job.salary_range or NOT_FOUND}")

        # Founders
        print(f"{BOLD}Founders:{RESET}   ", end="")
        if company.founders:
            founder_strs = []
            for f in company.founders:
                if f.linkedin:
                    founder_strs.append(f"{f.name} ({DIM}{f.linkedin}{RESET})")
                else:
                    founder_strs.append(f.name)
            print(", ".join(founder_strs))
        else:
            print(NOT_FOUND)

        # Company website
        print(f"{BOLD}Website:{RESET}    {DIM}{company.website or NOT_FOUND}{RESET}")

        # About the company
        print(f"{BOLD}{MAGENTA}About:{RESET} ", end="")
        if job.about_summary:
            print(job.about_summary)
        elif company.description:
            desc = company.description[:300].replace("\n", " ")
            if len(company.description) > 300:
                desc += "..."
            print(f"{DIM}{desc}{RESET}")
        else:
            print(NOT_FOUND)

        # Role description
        role_label = f"Role ({job.title})" if job.title and job.title != "Unknown Role" else "Role"
        print(f"{BOLD}{MAGENTA}{role_label}:{RESET} ", end="")
        if job.description_summary:
            print(job.description_summary)
        elif job.description:
            desc = job.description[:300].replace("\n", " ")
            if len(job.description) > 300:
                desc += "..."
            print(f"{DIM}{desc}{RESET}")
        else:
            print(NOT_FOUND)

        # Requirements
        print(f"{BOLD}{MAGENTA}Requirements:{RESET} ", end="")
        if job.requirements:
            reqs = job.requirements[:250].replace("\n", " ")
            if len(job.requirements) > 250:
                reqs += "..."
            print(f"{DIM}{reqs}{RESET}")
        else:
            print(NOT_FOUND)

        # Culture — truncated
        print(f"{BOLD}{MAGENTA}Culture:{RESET} ", end="")
        if job.culture_notes:
            culture = job.culture_notes[:200].replace("\n", " ")
            if len(job.culture_notes) > 200:
                culture += "..."
            print(f"{DIM}{culture}{RESET}")
        else:
            print(NOT_FOUND)

    def _display_message(self, message: str) -> None:
        word_count = len(message.split())
        char_count = len(message)
        print(f"\n{BOLD}{GREEN}--- Generated Message ({word_count} words, {char_count} chars) ---{RESET}")
        print(f"{YELLOW}{message}{RESET}")
        print(f"{GREEN}{'---' * 10}{RESET}")

    def _edit_message(self, message: str) -> str:
        """Open message in $EDITOR if available, otherwise inline edit."""
        editor = os.environ.get("EDITOR")
        if editor:
            return self._edit_in_editor(message, editor)
        return self._edit_inline(message)

    def _edit_in_editor(self, message: str, editor: str) -> str:
        """Write message to a temp file, open in editor, read back."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(message)
            tmp_path = f.name

        try:
            subprocess.call([editor, tmp_path])
            with open(tmp_path) as f:
                edited = f.read().strip()
            return edited if edited else message
        finally:
            os.unlink(tmp_path)

    def _edit_inline(self, message: str) -> str:
        """Simple inline editing: user types a new message."""
        print(f"\n{DIM}Type your new message (or press Enter to keep current):{RESET}")
        lines = []
        print(f"{DIM}(Type {BOLD}:done{RESET}{DIM} on its own line to finish. Blank lines are preserved.){RESET}")
        while True:
            line = input()
            if line.strip().lower() == ":done":
                break
            lines.append(line)

        if lines:
            return "\n".join(lines)
        return message

    def pick_jobs_from_company(
        self,
        company_name: str,
        job_stubs: list[dict],
        company_number: int,
        total_companies: int,
    ) -> list[dict] | None:
        """Show all job postings for a company and let the user pick which to apply to.

        Returns:
            list[dict] — the selected job stubs (could be 1 or many)
            None — if user wants to skip this company entirely
            "quit" sentinel is handled by returning empty list with a quit flag
        """
        # Show company header with blurb if available
        blurb = ""
        for s in job_stubs:
            if s.get("company_blurb"):
                blurb = s["company_blurb"]
                break

        print(f"\n{'=' * 60}")
        print(f"{BOLD}{CYAN}  Company {company_number}/{total_companies}: {company_name}{RESET}")
        if blurb:
            # Truncate to ~80 chars for a clean one-liner
            short = blurb if len(blurb) <= 80 else blurb[:77] + "..."
            print(f"  {DIM}{short}{RESET}")
        print(f"{'=' * 60}")

        if len(job_stubs) == 1:
            # Single posting — no need to pick, just show it
            stub = job_stubs[0]
            print(f"\n  {BOLD}1 open role:{RESET} {stub['title']}")
            choice = input(
                f"\n{BOLD}[A]pply  [S]kip company  [Q]uit{RESET} > "
            ).strip().lower()

            if choice in ("a", "apply", ""):
                return job_stubs
            elif choice in ("q", "quit"):
                return "quit"  # type: ignore
            else:
                return None  # skip

        # Multiple postings — show numbered list
        print(f"\n  {BOLD}{len(job_stubs)} open roles:{RESET}")
        for idx, stub in enumerate(job_stubs, start=1):
            print(f"    {BOLD}{CYAN}{idx}.{RESET} {stub['title']}")

        print(f"\n{DIM}Enter numbers separated by commas (e.g. 1,3), 'all', or 'skip'.{RESET}")
        while True:
            choice = input(
                f"{BOLD}Which roles? [numbers/all/skip/quit]{RESET} > "
            ).strip().lower()

            if choice in ("q", "quit"):
                return "quit"  # type: ignore
            elif choice in ("s", "skip"):
                return None
            elif choice in ("a", "all"):
                return job_stubs
            else:
                # Parse comma-separated numbers
                try:
                    indices = [int(x.strip()) for x in choice.split(",")]
                    selected = []
                    for idx in indices:
                        if 1 <= idx <= len(job_stubs):
                            selected.append(job_stubs[idx - 1])
                        else:
                            print(f"  {RED}Invalid number: {idx}. Pick between 1-{len(job_stubs)}.{RESET}")
                            selected = []
                            break
                    if selected:
                        return selected
                except ValueError:
                    print(f"  {RED}Invalid input. Enter numbers (e.g. 1,3), 'all', 'skip', or 'quit'.{RESET}")
