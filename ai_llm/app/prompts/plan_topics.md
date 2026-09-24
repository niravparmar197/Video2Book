You are planning a book made from an entire YouTube playlist's transcript.
You are given, for every 30-minute chunk of every video, the list of topics
that chunk covers. Merge the topics that are the same underlying idea, even
if different videos phrase them differently, and plan how the book should
be ordered.

Rules:
- Merge topics that are the same underlying idea, even if worded
  differently across videos (e.g. "gradient descent" and "how neural nets
  learn" may be the same topic if they cover the same ground).
- Never merge topics that are actually different just because the wording
  sounds similar.
- For every merged topic, list every {{"video_id", "chunk_index"}} pair from
  the input below whose topic list included it — these are its sources.
- Assign each merged topic a "level" from 1 (foundational, no
  prerequisites) to 5 (advanced, depends on several other topics).
- Assign each merged topic a "needs" list: the exact title text of OTHER
  merged topics you are also returning in this same response that a reader
  must understand first. Leave it empty if there are none. Only reference
  titles you are returning yourself — never invent a reference to a topic
  you are not also including.
- Return ONLY a JSON array — no other text, no markdown code fences, no
  reasoning or explanation before or after it. Each element:
  {{"title": "...", "level": 1-5, "needs": ["..."], "sources": [{{"video_id": "...", "chunk_index": 0}}]}}

Topics by chunk:
"""
{topics_by_chunk}
"""
