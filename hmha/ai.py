"""Claude-powered personalized message generation.

Takes scraped job/company data and the user's profile, then
generates a tailored application message that sounds human-written.
"""

from __future__ import annotations

import logging
import re

from anthropic import AsyncAnthropic

from hmha.config_loader import UserProfile
from hmha.models import Job
from hmha.utils import retry_async

logger = logging.getLogger("hmha")

SYSTEM_PROMPT = """You are helping a student write a short, personalized message to apply \
for a startup internship on Y Combinator's Work at a Startup platform. This message goes \
directly to the founding team.

STRUCTURE (follow this order, adapt wording naturally to each company):
1. GREETING: "Hi [founder name(s) if provided, otherwise just 'Hi']"
2. OPENER — SHORT & PERSONAL (1-2 sentences MAX): \
Share something genuine about yourself that connects to what the company does. Keep it simple and human. \
The format is basically: "[something personal about me] so [why this company is cool to me]." \
Examples of the VIBE (don't copy these, make each one unique and specific to the company): \
- AI movie company: "I've always been a big movie fan, watching Star Wars and Reservoir Dogs, \
so I'd be really excited to work on the future of movies." \
- Robotics company: "I've been nerding out about robots since I was a kid building LEGO Mindstorms, \
so a chance to work on real-world robotics is kind of a dream." \
- Fintech company: "After spending time on a trading desk at RBC, I got hooked on how tech can \
change the way people interact with money." \
Keep it SHORT. One or two casual sentences. Don't overthink it. Don't be verbose. \
Just say something real about yourself and connect it to them naturally.
3. BACKGROUND: Introduce yourself. Engineering Science at University of Toronto, graduating \
soon, heading to UChicago for a Masters in Financial Mathematics. Looking for a summer internship \
before that starts. Mention relevant experience: quant trader at RBC \
Capital Markets (4 months), AI Engineer at RBC (12 months), API Tester at Scotiabank, \
and computer vision research paper in progress. Weave these in naturally -- don't just list them. \
Emphasize whichever experience is most relevant to THIS company. \
Mention UChicago MFM when it's relevant (e.g., fintech, quant, data-heavy roles) but don't \
force it in if the company has nothing to do with finance or math.
4. SKILLS: Mention proficiency in Python and machine learning, familiarity with Java and JS. \
Only mention what's relevant to the role.
5. CLOSING: "Would love to get in touch!" followed by LinkedIn URL on a new line.

RULES:
- Write in first person as the applicant.
- Keep the tone casual and direct. Like a text to someone you respect, not a cover letter.
- The opener should NEVER start with "I saw you're working on..." or "I noticed that..." — \
those are generic. Start with something about YOU that bridges to THEM.
- Keep the opener SHORT. 1-2 sentences. Not a paragraph. Think casual, not essay.
- NEVER use these words/phrases: "exciting", "passionate", "thrilled", "amazing", "incredible", \
"love what you're building", "really resonates", "deeply impressed", "I am excited to apply", \
"I believe I would be a great fit", "caught my eye", "stands out", "fascinating". These all scream AI.
- Sound like a 22-year-old engineering student, not a LinkedIn influencer.
- NEVER mention availability, dates, or when you're free (no "June through August", no "available this summer", etc.).
- Output ONLY the message text. No subject line."""

FALLBACK_TEMPLATE = (
    "Hi!\n\n"
    "My name is {name}. Your company looks really exciting to me because "
    "[EDIT THIS: insert personal, specialized reason].\n\n"
    "I'm graduating University of Toronto from the Engineering Science program "
    "and heading to UChicago for a Masters in Financial Mathematics. I'm "
    "looking for an internship at a startup this coming summer. I have spent "
    "4 months as a quant trader at RBC Capital Markets, and previously I spent "
    "12 months as an AI Engineer there. Before that, I was an API Tester at "
    "Scotiabank and I am working on getting my computer vision research paper published.\n"
    "I am proficient in Python, machine learning, and also familiar with Java and JS.\n\n"
    "Would love to get in touch! You can learn more about me here: {linkedin}"
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
        return FALLBACK_TEMPLATE.format(
            name=user_profile.name,
            company=job.company.name,
            role=job.title,
            linkedin=user_profile.linkedin,
        )

    async def summarize_for_display(self, job: Job) -> tuple[str, str]:
        """Summarize the company about section and role description for terminal display.

        Returns (about_summary, description_summary) — each a short paragraph.
        Uses a fast, cheap call to Claude.
        """
        parts = []
        if job.company.description:
            parts.append(f"COMPANY ABOUT SECTION (raw scraped text):\n{job.company.description[:1500]}")
        if job.description:
            parts.append(f"ROLE DESCRIPTION (raw scraped text):\n{job.description[:1500]}")
        if job.requirements:
            parts.append(f"REQUIREMENTS:\n{job.requirements[:500]}")

        if not parts:
            return "", ""

        prompt = "\n\n".join(parts) + """

Summarize the above into two short sections for quick reading:

1. ABOUT THE COMPANY (2-3 sentences max): What does this company do? What problem are they solving? What's their product?

2. ROLE SUMMARY (2-3 sentences max): What will this person actually do day-to-day? What are the key requirements?

Keep it concise and factual. No filler words. Write in third person.
Format your response exactly like:
ABOUT: [your summary]
ROLE: [your summary]"""

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            about_summary = ""
            role_summary = ""

            about_match = re.search(r"ABOUT:\s*(.+?)(?=ROLE:|$)", text, re.DOTALL)
            if about_match:
                about_summary = about_match.group(1).strip()

            role_match = re.search(r"ROLE:\s*(.+?)$", text, re.DOTALL)
            if role_match:
                role_summary = role_match.group(1).strip()

            return about_summary, role_summary
        except Exception as e:
            logger.debug("Summarization failed: %s", e)
            return "", ""

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
        if user_profile.linkedin:
            sections.append(f"\nLINKEDIN URL: {user_profile.linkedin}")
        if style_notes:
            sections.append(f"\nTONE GUIDANCE: {style_notes}")

        sections.append("\nWrite the message now. Follow the structure from the system prompt. Be specific to this company.")
        return "\n".join(sections)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
