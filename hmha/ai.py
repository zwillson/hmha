"""Claude-powered personalized message generation.

Takes scraped job/company data and the user's profile, then
generates a tailored application message that sounds human-written.
"""

from __future__ import annotations

import logging
import random
import re

from anthropic import AsyncAnthropic

from hmha.config_loader import UserProfile
from hmha.models import Job
from hmha.utils import retry_async

logger = logging.getLogger("hmha")

# --- Structural variation: pick a random template each call ---
# This prevents every message from reading identically.

_STRUCTURE_VARIANTS = [
    # Variant A: opener -> background -> skills -> close (classic)
    """\
For THIS message, use this flow:
1. GREETING — "Hi [founder name(s) if provided, else just 'Hi']"
2. SHORT PERSONAL OPENER (1-2 sentences) — something about YOU that connects to THEM.
3. BACKGROUND — weave in your experience naturally, emphasizing what's relevant to this company.
4. SKILLS — only mention what matters for this role. Skip this section entirely if the background already covers it.
5. CLOSING — "Would love to get in touch!" + LinkedIn URL on its own line.""",

    # Variant B: opener -> strongest experience first -> rest of background -> close
    """\
For THIS message, use this flow:
1. GREETING — "Hi [founder name(s) if provided, else just 'Hi']"
2. SHORT PERSONAL OPENER (1-2 sentences) — something about YOU that connects to THEM.
3. LEAD WITH YOUR STRONGEST EXPERIENCE for this role — go into a bit of detail about what you actually did. \
Then briefly mention your other experience and education.
4. CLOSING — "Would love to get in touch!" + LinkedIn URL on its own line.
(No separate skills section — weave relevant skills into the experience.)""",

    # Variant C: opener -> what you're looking for -> why you're qualified -> close
    """\
For THIS message, use this flow:
1. GREETING — "Hi [founder name(s) if provided, else just 'Hi']"
2. SHORT PERSONAL OPENER (1-2 sentences) — something about YOU that connects to THEM.
3. WHAT DRAWS YOU TO THIS ROLE — reference something specific from the job description or company page \
that you'd want to work on, and naturally tie it to your experience.
4. BRIEF BACKGROUND — keep it tight, 2-3 sentences covering your most relevant experience.
5. CLOSING — "Would love to get in touch!" + LinkedIn URL on its own line.""",
]

SYSTEM_PROMPT = """You are helping a student write a short, personalized message to apply \
for a startup internship on Y Combinator's Work at a Startup platform. This message goes \
directly to the founding team.

{structure_variant}

OPENER GUIDELINES:
The opener should be SHORT & PERSONAL (1-2 sentences MAX). \
Share something genuine about yourself that connects to what the company does. \
The format is basically: "[something personal about me] so [why this company is cool to me]." \
Examples of the VIBE (don't copy these verbatim — make each one unique): \
- AI movie company: "I've always been a big movie fan, watching Star Wars and Reservoir Dogs, \
so I'd be really excited to work on the future of movies." \
- Robotics company: "I've been nerding out about robots since I was a kid building LEGO Mindstorms, \
so a chance to work on real-world robotics is kind of a dream." \
- Fintech company: "After spending time on a trading desk at RBC, I got hooked on how tech can \
change the way people interact with money." \
Keep it SHORT. One or two casual sentences. Don't overthink it.

BACKGROUND FACTS (use these, don't invent):
- Engineering Science at University of Toronto, graduating soon
- Heading to UChicago for a Masters in Financial Mathematics
- 4 months quant trader at RBC Capital Markets
- 12 months AI Engineer at RBC
- API Tester at Scotiabank
- Working on a biomedical research paper (computer vision problem in a hospital setting)
- Skills: Python, ML, Java, JS
Emphasize whichever experience is most relevant to THIS company. \
Always mention that you're heading to UChicago for a Masters in Financial Mathematics — \
work it in naturally alongside your other background. \
Don't just list everything — pick the 2-3 things that matter and weave them in.

SOUNDING HUMAN — THIS IS CRITICAL:
- Use contractions: "I'm", "I've", "I'd", "don't", "didn't", "it's". Never "I am", "I have", "I would".
- Use casual transitions: "honestly", "anyway", "also", "on the side", "before that". \
Not "furthermore", "additionally", "moreover".
- It's okay to start a sentence with "And" or "But". Real people do this.
- Vary your sentence length. Mix short punchy sentences with longer ones. \
Don't make every sentence the same length — that's an AI tell.
- Reference something SPECIFIC from the job description or company page. \
Not their mission statement — pick a technical detail, a product feature, a specific problem they mention. \
Something that shows you actually read their page.
- Don't use the same sentence structure repeatedly. If one sentence starts with "I", \
the next one shouldn't. Mix it up.

BANNED WORDS/PHRASES (these scream AI — never use them):
"exciting", "excited to apply", "passionate", "thrilled", "amazing", "incredible", \
"love what you're building", "really resonates", "deeply impressed", \
"I believe I would be a great fit", "caught my eye", "stands out", "fascinating", \
"aligns with", "aligns perfectly", "I'm drawn to", "mission-driven", \
"innovative", "cutting-edge", "leverage my skills", "bring value", "make an impact", \
"contribute to your team", "unique opportunity", "I am confident", \
"diverse experience", "strong foundation", "well-positioned", \
"I would welcome the opportunity", "I look forward to", "keen interest".

MORE RULES:
- Write in first person as the applicant.
- Tone: like a text to someone you respect. Not a cover letter. Not a LinkedIn post.
- The opener should NEVER start with "I saw you're working on..." or "I noticed that..." — \
those are generic. Start with something about YOU that bridges to THEM.
- NEVER mention availability, dates, or when you're free.
- Vary the message length. Sometimes 80 words is fine, sometimes 150. Don't always aim for the same count.
- Output ONLY the message text. No subject line, no headers, no labels."""

FALLBACK_TEMPLATE = (
    "Hi!\n\n"
    "My name is {name}. Your company looks really exciting to me because "
    "[EDIT THIS: insert personal, specialized reason].\n\n"
    "I'm graduating University of Toronto from the Engineering Science program "
    "and heading to UChicago for a Masters in Financial Mathematics. I'm "
    "looking for an internship at a startup this coming summer. I have spent "
    "4 months as a quant trader at RBC Capital Markets, and previously I spent "
    "12 months as an AI Engineer there. Before that, I was an API Tester at "
    "Scotiabank and I'm working on a biomedical research paper.\n"
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

        Picks a random structural variant each time so messages don't
        all read the same. Falls back to a template if the API fails.
        """
        prompt = self._build_prompt(job, user_profile, style_notes)

        # Pick a random structure variant for this message
        variant = random.choice(_STRUCTURE_VARIANTS)
        system = SYSTEM_PROMPT.format(structure_variant=variant)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=400,
            system=system,
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
                system=system,
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
        """Construct the user prompt with all context for Claude.

        Feeds rich company context so the model can reference specific details
        rather than writing generic messages.
        """
        sections = [
            "Write a message to apply for this role. Here's everything I know about the company and role:",
            "",
            f"COMPANY: {job.company.name} ({job.company.yc_batch})" if job.company.yc_batch
            else f"COMPANY: {job.company.name}",
        ]

        # Founder names — so Claude can greet them by name
        if job.company.founders:
            founder_names = [f.name for f in job.company.founders]
            sections.append(f"FOUNDERS: {', '.join(founder_names)}")

        if job.company.website:
            sections.append(f"COMPANY WEBSITE: {job.company.website}")

        if job.company.description:
            # Feed the FULL company description so Claude can pick out specifics
            sections.append(f"ABOUT THE COMPANY (from their page):\n{job.company.description[:2000]}")

        sections.append(f"\nROLE: {job.title}")

        if job.description:
            # Feed the FULL job description — this is where the best specific details live
            sections.append(f"FULL JOB DESCRIPTION:\n{job.description[:2000]}")
        if job.requirements:
            sections.append(f"REQUIREMENTS:\n{job.requirements[:1000]}")
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

        # Final instruction — nudge Claude to be specific
        sections.append(
            "\nWrite the message now. IMPORTANT: reference at least one SPECIFIC thing "
            "from the job description or company page above — a product feature, a technical "
            "detail, a problem they mention. Don't be generic."
        )
        return "\n".join(sections)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
