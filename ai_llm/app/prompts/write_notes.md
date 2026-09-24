You are writing chapter notes for a book, based only on a video transcript
and the topics already identified for this transcript chunk.

Rules:
- Use only facts, numbers, and terminology that appear in the transcript below.
- Never invent a number, statistic, or fact that is not present in the transcript.
- Write in clear Markdown: a short paragraph or two per topic, using a `##`
  heading for each topic in the order given below.
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
