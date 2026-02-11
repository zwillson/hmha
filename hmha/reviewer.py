"""Terminal-based review interface for application messages.

Shows job context and the generated message, then lets the user
approve, edit, skip, or quit before each application is sent.
"""

import os
import subprocess
import tempfile
from enum import Enum


class ReviewDecision(Enum):
    APPROVE = "approve"
    EDIT = "edit"
    SKIP = "skip"
    QUIT = "quit"


# ANSI color helpers
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


class MessageReviewer:
    """Interactive terminal UI for reviewing generated messages."""

    def review(
        self,
        job_title: str,
        company_name: str,
        company_description: str,
        culture_notes: str,
        message: str,
        job_number: int,
        total_jobs: int,
    ) -> tuple[ReviewDecision, str]:
        """Display job context and message, return user's decision and final message.

        Returns:
            (decision, message) where message may be edited by the user.
        """
        self._display_header(job_number, total_jobs)
        self._display_job_context(job_title, company_name, company_description, culture_notes)
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

    def _display_job_context(
        self,
        job_title: str,
        company_name: str,
        company_description: str,
        culture_notes: str,
    ) -> None:
        print(f"\n{BOLD}Role:{RESET}    {job_title}")
        print(f"{BOLD}Company:{RESET} {company_name}")
        if company_description:
            # Show first ~200 chars of company description
            desc = company_description[:200]
            if len(company_description) > 200:
                desc += "..."
            print(f"{BOLD}About:{RESET}   {DIM}{desc}{RESET}")
        if culture_notes:
            notes = culture_notes[:150]
            if len(culture_notes) > 150:
                notes += "..."
            print(f"{BOLD}Culture:{RESET} {DIM}{notes}{RESET}")

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
        print(f"{DIM}(Enter a blank line to finish){RESET}")
        while True:
            line = input()
            if line == "":
                break
            lines.append(line)

        if lines:
            return " ".join(lines)
        return message
