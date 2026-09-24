You are extracting the list of distinct topics covered in one transcript
chunk of an educational YouTube video, to plan a book chapter later.

Rules:
- Use only facts and topic names that actually appear in the transcript below.
- Never invent a topic that is not discussed in this transcript.
- Return a JSON array of short topic strings (3-8 words each), in the order
  they first appear in the transcript.
- Return ONLY the JSON array — no other text, no markdown code fences, no
  reasoning or explanation before or after it.

Transcript:
"""
{transcript}
"""
