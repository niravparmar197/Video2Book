You are planning a book made from an entire YouTube playlist's transcript.
You are given, for every 30-minute chunk of every video, the list of topics
that chunk covers. Merge the topics that are the same underlying idea, even
if different videos phrase them differently, and plan how the book should
be ordered.

Rules:
- Always respond in English, regardless of what language the input
  topics below are in. Translate rather than copying another script.
- Merge topics that are the same underlying idea, even if worded
  differently across videos (e.g. "gradient descent" and "how neural nets
  learn" may be the same topic if they cover the same ground) -- this
  includes near-synonyms from the SAME chunk, not just across videos
  (e.g. "Consistency" and "Correctness" describing the same database
  property are one topic, not two).
- Never merge topics that are actually different just because the wording
  sounds similar.
- Prefer fewer, broader chapters over many narrow ones. Each topic you
  return becomes its own full chapter in the finished book, starting on
  a new page -- so splitting one short video's closely related sub-points
  into several separate topics produces a book that's mostly page breaks
  and near-empty chapters, not a better-organized one. When several
  topics from the same chunk(s) are really just facets of one umbrella
  concept (e.g. "Atomicity", "Consistency", "Isolation", and "Durability"
  from a single video about ACID properties), merge them into ONE topic
  titled after the umbrella concept rather than keeping them separate.
  Only keep topics separate when they're substantial enough, or distinct
  enough, to genuinely earn their own chapter.
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
