You are writing ONE section of a book chapter for the topic below, drawing
on excerpts from multiple source videos that all cover it. Synthesize a
single, coherent section — do not repeat the same point once per source
video; merge what they say into one explanation.

Rules:
- Use only facts that appear in the excerpts below. Never invent a number,
  fact, or claim that is not present in at least one excerpt.
- If sources disagree or add different details, cover both without
  contradiction, in one coherent narrative — do not write "Video 1 says...
  Video 2 says..." as separate sub-sections.
- Write real notes, not a transcript recap: do not narrate the source
  excerpts sentence-by-sentence or in their original order. Reorganize and
  condense them into clear, textbook-style explanations of the topic.
- Write enough depth that someone who reads only this section — and never
  watches any of the source videos — fully understands the topic: define
  key terms, explain the reasoning or process step by step, and include
  every concrete example, number, or formula the excerpts give for it. A
  single short paragraph is almost never enough; write as many paragraphs
  as the topic actually needs.
- Write in Markdown: one or more "## heading" sections with plain
  paragraphs underneath. Never write raw LaTeX.
- Return ONLY the Markdown notes — no other text, no reasoning or
  explanation before or after it.

Visual aids (optional, use sparingly):
- If — and only if — a section's content genuinely calls for a table, a
  diagram, or a chart, you may add ONE right after that section's
  paragraphs, as a single fenced code block tagged ```table, ```diagram, or
  ```chart containing exactly one JSON object. Most sections need no
  visual aid at all — never add one just to have one.
- ```table: {{"headers": ["...", ...], "rows": [["...", ...], ...]}} — only
  for genuinely tabular content (e.g. comparing several items across
  several attributes).
- ```diagram: {{"nodes": ["...", ...], "edges": [["from", "to"], ...]}} —
  only for a process, structure, or relationship the excerpts actually
  describe.
- ```chart: {{"type": "bar", "title": "...", "categories": ["...", ...],
  "values": [number, ...]}} — only when the excerpts state explicit
  numbers to plot; never invent a number to fill a chart.

Topic: {topic}

Source excerpts:
"""
{excerpts}
"""
