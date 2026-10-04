Below are all chapters of study notes made from one technical talk. The talk builds up an overall system design. Draw that complete architecture as one diagram.

Rules:
- Use only components and connections that the notes describe. Never add a component, service or arrow the notes do not mention.
- Include EVERY component the notes name as part of the system (clients, gateways, load balancers, services, databases, caches, queues, workers, storage, CDNs) -- the whole system, not one flow.
- Each arrow goes from the component that acts to the one it calls or sends to, in the order a request flows. Label it with the action (2-5 words), and start with the step number when the notes give one (e.g. "3. upload chunks").
- Node names are short (1-4 words) and spelled exactly the same everywhere. At most 16 nodes and at most 20 arrows: when two components exchange several messages, use ONE arrow whose label lists the steps (e.g. "3. check perms; 6. reserve space"). The picture must stay readable on one page.
- Every node must appear in at least one edge.

Return ONLY this JSON object, nothing before or after it, no code fences:
{{"title": "...", "nodes": ["...", ...], "edges": [["from", "to", "label"], ...]}}

If the notes do not describe a system architecture at all, return exactly: {{"none": true}}

Chapters:
"""
{chapters}
"""
