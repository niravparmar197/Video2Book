You are writing chapter notes for a book, based only on a video transcript
and the topics already identified for this transcript chunk.

Rules:
- Use only facts, numbers, and terminology that appear in the transcript below.
- Never invent a number, statistic, or fact that is not present in the transcript.
- Write real notes, not a transcript recap: do not narrate the video
  sentence-by-sentence or follow its exact chronological phrasing.
  Reorganize and condense what was said into clear explanations the way a
  textbook would present the topic.
- Write enough depth that someone who reads only these notes — and never
  watches the video — fully understands the topic: define key terms,
  explain the reasoning or process step by step, and include every
  concrete example, number, or formula the transcript gives for it. A
  single short paragraph is almost never enough; write as many paragraphs
  as the topic actually needs.
- Use a `##` heading for each topic, in the order given below.
- Write Markdown only — never raw LaTeX.

Visual aids (optional, use sparingly):
- If — and only if — a topic's content genuinely calls for a table, a
  diagram, or a chart, you may add ONE right after that topic's paragraphs,
  as a single fenced code block tagged ```table, ```diagram, or ```chart
  containing exactly one JSON object. Most topics need no visual aid at
  all — never add one just to have one.
- ```table: {{"headers": ["...", ...], "rows": [["...", ...], ...]}} — only
  for genuinely tabular content (e.g. comparing several items across
  several attributes).
- ```diagram: {{"nodes": ["...", ...], "edges": [["from", "to"], ...]}} —
  only for a process, structure, or relationship the transcript actually
  describes.
- ```chart: {{"type": "bar", "title": "...", "categories": ["...", ...],
  "values": [number, ...]}} — only when the transcript states explicit
  numbers to plot; never invent a number to fill a chart.

Topics covered in this chunk:
{topics}

Transcript:
"""
{transcript}
"""
