You are building a glossary for a book made from multiple chapters. Extract
every genuinely important term that a reader would want defined, across all
the chapters below, and give each one a short, clear definition grounded
only in what the chapters actually say.

Rules:
- Always respond in English, regardless of what language the chapters
  below are in. Translate terms and definitions rather than copying
  another script.
- Use only facts and definitions that are actually stated or clearly
  implied by the chapters below. Never invent a definition.
- Do not include a term more than once — if multiple chapters define or
  use the same term, write ONE merged entry for it.
- Skip generic words that don't need a glossary entry — only include terms
  a reader would plausibly look up.
- Never use a double-quote character (") anywhere inside "definition" —
  use single quotes ('like this') instead if you need to quote a word or
  phrase. "definition" sits inside a JSON string, and an unescaped double
  quote inside it breaks the JSON.
- Return ONLY a JSON array — no other text, no markdown code fences, no
  reasoning or explanation before or after it. Each element:
  {{"term": "...", "definition": "..."}}

Chapters:
"""
{chapters}
"""
