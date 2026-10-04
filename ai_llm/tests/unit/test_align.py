"""Unit tests for app.nodes.align -- where each section is spoken."""
import json

from app.nodes import align
from app.nodes.chunk import Cue


def _cues(video_id, lines):
    return [(video_id, Cue(start_seconds=t, end_seconds=t + 5, text=text)) for t, text in lines]


_CUES = _cues(
    "vid1",
    [
        (10, "today we talk about database transactions and commits"),
        (20, "a transaction groups several writes together"),
        (120, "now isolation levels decide what concurrent readers see"),
        (130, "dirty reads phantom reads and serializable isolation"),
        (300, "finally replication copies data to followers and leaders"),
    ],
)

_NOTES = """## Transactions
A **transaction** groups several database writes and commits them together.

## Isolation levels
Isolation decides what concurrent readers see: dirty reads, phantom reads, serializable.

## Replication
Leaders copy data to followers.

## Key Takeaways
- Transactions, isolation and replication.
"""


def test_each_section_gets_the_time_where_its_words_are_spoken():
    times = align.section_times(_NOTES, _CUES)

    assert times == [("vid1", 10), ("vid1", 120), ("vid1", 300), None]


def test_a_section_with_too_little_overlap_gets_no_time():
    # English notes from a Hindi caption track share no words.
    hindi = _cues("vid1", [(5, "नमस्ते दोस्तों आज हम बात करेंगे")])

    assert align.section_times(_NOTES, hindi) == [None, None, None, None]


def test_timed_cues_come_from_the_chapters_own_chunks_only(tmp_path):
    (tmp_path / "work" / "captions").mkdir(parents=True)
    (tmp_path / "work" / "chunks").mkdir(parents=True)
    (tmp_path / "work" / "captions" / "vid1.en.vtt").write_text(
        "WEBVTT\n\n00:00:10.000 --> 00:00:12.000\nfirst part\n\n"
        "00:31:00.000 --> 00:31:02.000\nsecond part\n",
        encoding="utf-8",
    )
    (tmp_path / "work" / "chunks" / "vid1_001.json").write_text(
        json.dumps({"start_seconds": 1800, "end_seconds": 3600, "text": "second part"}), encoding="utf-8"
    )

    cues = align.timed_cues_for_sources([{"video_id": "vid1", "chunk_index": 1}], tmp_path)

    assert [(video_id, cue.text) for video_id, cue in cues] == [("vid1", "second part")]
