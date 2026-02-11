"""Claude-powered personalized message generation.

Takes scraped job/company data and the user's profile, then
generates a tailored application message that sounds human-written.
"""

from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from hmha.config_loader import UserProfile
from hmha.models import Job
from hmha.utils import retry_async

logger = logging.getLogger("hmha")

SYSTEM_PROMPT = """You are helping a student write a short, personalized message to apply \
for a startup internship on Y Combinator's Work at a Startup platform. This message goes \
directly to the founding team.

RULES:
- Write EXACTLY 50-150 words. Count carefully.
- Write in first person as the applicant.
- Be conversational but professional. No corporate speak.
- Reference something SPECIFIC about the company or product -- not generic praise.
- Connect the applicant's experience to what the company actually needs.
- Show genuine curiosity about the problem space.
- Do NOT use phrases like "I am excited to apply" or "I believe I would be a great fit".
- Do NOT list skills in bullet points. Weave them into a narrative.
- If the company mentions specific values or personality traits they want, subtly reflect those.
- End with a forward-looking statement (what you want to build/learn), not a plea.
- Sound like a real person wrote this, not a cover letter generator.
- Output ONLY the message text. No subject line, no greeting header, no sign-off."""

FALLBACK_TEMPLATE = (
    "Hi! I'm {name}, a student with experience in {skills}. "
    "I came across {company} and I'm really interested in the {role} role. "
    "[EDIT THIS: mention something specific about what they're building]. "
    "I'd love to chat about how I can contribute this summer."
)


class MessageGenerator:
    """Generates personalized application messages using Claude."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    @retry_async(max_retries=3, backoff_base=2.0)
    async def generate_message(
        self,
        job: Job,
        user_profile: UserProfile,
        style_notes: str = "",
    ) -> str:
        """Generate a personalized 50-150 word application message.

        Falls back to a template with [EDIT THIS] markers if the API fails.
        """
        prompt = self._build_prompt(job, user_profile, style_notes)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        message = response.content[0].text.strip()

        # Validate minimum length (WAAS requires >= 50 chars)
        if len(message) < 50:
            logger.warning("Generated message too short (%d chars). Regenerating...", len(message))
            prompt += "\n\nIMPORTANT: Your previous message was too short. Write at least 50 characters."
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            message = response.content[0].text.strip()

        logger.info("Generated message: %d chars, ~%d words", len(message), len(message.split()))
        return message

    def generate_fallback(self, job: Job, user_profile: UserProfile) -> str:
        """Return a template message when the API is unavailable."""
        top_skills = ", ".join(user_profile.skills[:3])
        return FALLBACK_TEMPLATE.format(
            name=user_profile.name,
            skills=top_skills,
            company=job.company.name,
            role=job.title,
        )

    def _build_prompt(self, job: Job, user_profile: UserProfile, style_notes: str) -> str:
        """Construct the user prompt with all context for Claude."""
        sections = [
            "Write a message to apply for this role. Here's the context:",
            "",
            f"COMPANY: {job.company.name} ({job.company.yc_batch})" if job.company.yc_batch
            else f"COMPANY: {job.company.name}",
        ]

        if job.company.description:
            sections.append(f"WHAT THEY DO: {job.company.description}")

        sections.append(f"\nROLE: {job.title}")

        if job.description:
            sections.append(f"DESCRIPTION: {job.description}")
        if job.requirements:
            sections.append(f"REQUIREMENTS: {job.requirements}")
        if job.culture_notes:
            sections.append(f"CULTURE/VALUES: {job.culture_notes}")
        if job.location:
            sections.append(f"LOCATION: {job.location}")

        sections.extend([
            f"\nABOUT ME:\n{user_profile.experience_summary}",
            f"\nKEY THINGS I'VE DONE:",
        ])
        for highlight in user_profile.resume_highlights:
            sections.append(f"- {highlight}")

        sections.append(f"\nMY SKILLS: {', '.join(user_profile.skills)}")

        if user_profile.interests:
            sections.append(f"\nWHAT I'M LOOKING FOR: {user_profile.interests}")
        if user_profile.personality_notes:
            sections.append(f"\nMY STYLE: {user_profile.personality_notes}")
        if style_notes:
            sections.append(f"\nTONE GUIDANCE: {style_notes}")

        sections.append("\nWrite the message now. 50-150 words, specific to this company.")
        return "\n".join(sections)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
