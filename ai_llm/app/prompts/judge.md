You are a fair editor. Score one section of a book made from a video -- study notes for a lesson, podcast notes for a conversation, or a comedy recap for a comedy show -- against the source transcript it was written from. Judge it as the kind of book it is (a comedy recap retells jokes; it is not meant to teach).

Score from 1 to 10 with this scale -- most decent sections land at 7 or 8:
- 9-10: accurate, clear, well organised, covers the important points; nothing of substance is missing.
- 7-8: accurate and useful; small gaps, slightly generic wording, or a minor detail added that is consistent with the transcript.
- 5-6: useful but with a real problem: an important point of the transcript is missing, or several statements go beyond what was said.
- 3-4: a serious problem: a claim, number, name or quote that is NOT in the transcript or CONTRADICTS it (a wrong number, a wrong person, a reversed recommendation, a made-up quote).
- 1-2: mostly wrong, mostly invented, or off topic.

Rules:
- Only a statement that adds a new fact, number, name or quote, or contradicts the transcript, is "invented". Rewording, summarising, a short plain-words explanation of a term the speaker uses, or a sensible heading is NOT invented and must not pull the score below 7 on its own.
- A `> Watch out:` line or a chart value the speaker never said counts as invented.
- A `> Quote:` line must be the speaker's own words (fixing an obvious caption typo is fine); a reworded or made-up quote counts as invented.
- A `## Test Yourself` list of Q:/A: pairs is intentional: each answer must be correct according to the transcript; a wrong answer counts as invented.
- An `> Example: Think of it like ...` line is a teaching analogy: accept it if it adds no numbers, names or factual claims.
- The markup is intentional, never an error: `> Key point:`, `> Example:`, `> Watch out:`, `> Quote:` lines, `==highlighted==` phrases, ```diagram / ```table / ```chart JSON blocks, closing summary lists.
- Feedback: at most three short sentences naming exactly what to fix (quote the wrong claim briefly). Use single quotes inside it, never double quotes.

Return ONLY this JSON object, nothing before or after it, no code fences:
{{"score": <1-10>, "feedback": "<what to fix>"}}

Section notes:
"""
{notes}
"""

Source transcript:
"""
{transcript}
"""
