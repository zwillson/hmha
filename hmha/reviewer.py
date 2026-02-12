"""Terminal-based review interface for application messages.

Shows job context and the generated message, then lets the user
approve, edit, skip, or quit before each application is sent.
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
        print(f"\n{BOLD}Company:{RESET}    {name_line}")

        # Role
        role_line = job.title if job.title and job.title != "Unknown Role" else NOT_FOUND
        print(f"{BOLD}Role:{RESET}       {role_line}")

        # Location
        print(f"{BOLD}Location:{RESET}   {job.location or NOT_FOUND}")

        # Industry & size
        industry = company.industry or NOT_FOUND
        size = f"{company.size} people" if company.size else NOT_FOUND
        print(f"{BOLD}Industry:{RESET}   {industry}")
        print(f"{BOLD}Size:{RESET}       {size}")

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

        # Website (clickable link for the user)
        print(f"{BOLD}Website:{RESET}    {DIM}{company.website or NOT_FOUND}{RESET}")

        # Job URL
        print(f"{BOLD}Job URL:{RESET}    {DIM}{job.url or NOT_FOUND}{RESET}")

        # About the company (use AI summary if available, fall back to raw)
        print(f"\n{BOLD}{MAGENTA}About the company:{RESET}")
        if job.about_summary:
            print(f"  {job.about_summary}")
        elif company.description:
            print(f"  {DIM}{company.description[:500]}{RESET}")
        else:
            print(f"  {NOT_FOUND}")

        # Role description (use AI summary if available, fall back to raw)
        print(f"\n{BOLD}{MAGENTA}Role summary:{RESET}")
        if job.description_summary:
            print(f"  {job.description_summary}")
        elif job.description:
            desc = job.description[:500]
            if len(job.description) > 500:
                desc += "..."
            print(f"  {DIM}{desc}{RESET}")
        else:
            print(f"  {NOT_FOUND}")

        # Requirements
        print(f"\n{BOLD}{MAGENTA}Requirements:{RESET}")
        if job.requirements:
            reqs = job.requirements[:400]
            if len(job.requirements) > 400:
                reqs += "..."
            print(f"  {DIM}{reqs}{RESET}")
        else:
            print(f"  {NOT_FOUND}")

        # Culture
        print(f"\n{BOLD}{MAGENTA}Culture/Values:{RESET}")
        if job.culture_notes:
            print(f"  {DIM}{job.culture_notes}{RESET}")
        else:
            print(f"  {NOT_FOUND}")

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
