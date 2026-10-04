You are extracting the list of distinct topics covered in one transcript
chunk of a YouTube video -- a lesson, a podcast conversation or a comedy
show -- to plan a book chapter later. For a podcast, a topic is a subject
the people discuss; for a comedy show, a topic is a bit (the subject of a
run of jokes, e.g. "Flying with kids").

Rules:
- Always respond in English, regardless of what language the transcript
  below is in. Translate topic names into English rather than copying the
  transcript's own script/language — this book's templates render in a
  Latin-script font that cannot display every language's script.
- Use only facts and topic names that actually appear in the transcript below.
- Never invent a topic that is not discussed in this transcript.
- Identify the MAJOR topics only — group related points, asides, and
  examples under the broader concept they belong to. Return at most 6
  topics for this chunk. Do not list every sentence or sub-point as its
  own topic; a reader's notes should read as a handful of real sections,
  not a line-by-line recap of the transcript.
- Return a JSON array of short topic strings (3-8 words each), in the order
  they first appear in the transcript.
- Return ONLY the JSON array — no other text, no markdown code fences, no
  reasoning or explanation before or after it.

Transcript:
"""
{transcript}
"""
