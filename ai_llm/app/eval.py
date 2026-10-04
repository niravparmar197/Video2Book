"""Eval gate for prompt / model changes (root AGENTS.md: a prompt or model
change ships only if the average judge score does not drop).

    python -m app.eval                      # run the eval set, compare to the baseline
    python -m app.eval --update-baseline    # also record this run as the new baseline
    python -m app.eval --add-example output/<book> --genre podcast
                                            # add a book's first chunk to the local set

Each example is a real transcript excerpt + its topics + its genre. The
current writer prompts write notes for it, the deterministic clean-ups run
(as in a real book), and the judge scores the result -- one write and one
judge call per example, no refine, so the score measures the prompts
themselves. Examples come from the LangSmith dataset EVAL_DATASET_NAME when
it is set (each example's inputs: transcript, topics, genre, title),
otherwise from eval/dataset.jsonl.

Verdict: no baseline yet -> this run becomes it. Average held or improved ->
PASS. Dropped -> BLOCKED when EVAL_ON_RELEASE=true (exit code 1), else WARN.
This is the one workflow besides a real book run that calls the real LLMs.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from app.config import load_settings
from app.llm import call_writer
from app.nodes.genre import GENRES
from app.nodes.verify import clean_notes, drop_unspoken_quotes, run_verify, strip_ungrounded_visuals
from app.nodes.write import _load_prompt, ensure_closing_section

_EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
DATASET_PATH = _EVAL_DIR / "dataset.jsonl"
BASELINE_PATH = _EVAL_DIR / "baseline.json"
_MAX_TRANSCRIPT_CHARS = 15_000
_PARALLEL_EXAMPLES = 4
_JUDGE_RUNS = 2


def load_examples() -> tuple[str, list[dict]]:
    """(source name, examples) -- LangSmith when EVAL_DATASET_NAME is set."""
    dataset_name = os.environ.get("EVAL_DATASET_NAME", "").strip()
    if dataset_name:
        from langsmith import Client

        examples = [
            {"id": str(example.id), **example.inputs}
            for example in Client().list_examples(dataset_name=dataset_name)
        ]
        return f"LangSmith:{dataset_name}", examples
    if not DATASET_PATH.exists():
        return str(DATASET_PATH), []
    lines = DATASET_PATH.read_text(encoding="utf-8").splitlines()
    return str(DATASET_PATH), [json.loads(line) for line in lines if line.strip()]


def add_example(book_dir: str | Path, genre: str, video_id: str | None = None) -> dict:
    """Append the first chunk of an already-made book to eval/dataset.jsonl."""
    if genre not in GENRES:
        raise ValueError(f"genre must be one of {GENRES}")
    book_dir = Path(book_dir)
    pattern = f"{video_id}_000.json" if video_id else "*_000.json"
    chunk_path = sorted((book_dir / "work" / "chunks").glob(pattern))[0]
    chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
    topics_path = book_dir / "work" / "topics" / chunk_path.name
    topics = json.loads(topics_path.read_text(encoding="utf-8"))["topics"] if topics_path.exists() else []
    videos = json.loads((book_dir / "videos.json").read_text(encoding="utf-8"))
    title = next((v["title"] for v in videos if v["video_id"] == chunk["video_id"]), chunk["video_id"])
    example = {
        "id": chunk["video_id"],
        "title": title,
        "genre": genre,
        "topics": topics,
        "transcript": chunk["text"][:_MAX_TRANSCRIPT_CHARS],
    }
    _EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with DATASET_PATH.open("a", encoding="utf-8") as dataset:
        dataset.write(json.dumps(example, ensure_ascii=False) + "\n")
    return example


def score_example(example: dict) -> dict:
    """One write + one judge with the current prompts."""
    transcript = example["transcript"]
    prompt = _load_prompt(transcript, example.get("topics") or [], example.get("genre", "lecture"))
    raw_notes = strip_ungrounded_visuals(call_writer(prompt), transcript)
    notes = drop_unspoken_quotes(clean_notes(raw_notes), transcript).strip()
    notes = ensure_closing_section(notes, example.get("genre", "lecture"))
    # One judge call swings by +-2 on identical notes; averaging several
    # makes a real change visible above the noise.
    results = [run_verify(transcript, notes) for _ in range(_JUDGE_RUNS)]
    return {
        "id": example["id"],
        "genre": example.get("genre"),
        "score": round(statistics.mean(result.score for result in results), 2),
        "feedback": results[0].feedback,
    }


def dataset_fingerprint(examples: list[dict]) -> str:
    """Scores are only comparable on the same examples."""
    return ",".join(sorted(str(example["id"]) for example in examples))


def verdict(average: float, baseline: dict | None, gate_on: bool, fingerprint: str = "") -> str:
    if baseline is None or baseline.get("dataset", fingerprint) != fingerprint:
        return "NEW BASELINE"
    if average >= baseline["average"]:
        return "PASS"
    return "BLOCKED" if gate_on else "WARN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval", description=__doc__.split("\n\n")[0])
    parser.add_argument("--add-example", metavar="BOOK_DIR")
    parser.add_argument("--genre", default="lecture")
    parser.add_argument("--video", help="with --add-example: which video of a playlist book")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    if args.add_example:
        example = add_example(args.add_example, args.genre, args.video)
        print(f"Added {example['id']} ({example['genre']}) to {DATASET_PATH}")
        return 0

    load_settings()  # populate the environment from .env (API keys, EVAL_*)
    source, examples = load_examples()
    if not examples:
        print(f"No eval examples in {source}. Add some with --add-example output/<book>.")
        return 1

    with ThreadPoolExecutor(max_workers=_PARALLEL_EXAMPLES) as pool:
        results = list(pool.map(score_example, examples))
    average = round(statistics.mean(result["score"] for result in results), 2)

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) if BASELINE_PATH.exists() else None
    gate_on = os.environ.get("EVAL_ON_RELEASE", "").strip().lower() in {"1", "true", "yes", "on"}
    fingerprint = dataset_fingerprint(examples)
    outcome = verdict(average, baseline, gate_on, fingerprint)

    print(f"Dataset: {source} ({len(examples)} examples)")
    for result in results:
        print(f"  {result['id']:<14} {result['genre']:<8} {result['score']}/10  {result['feedback'][:90]}")
    if baseline:
        print(f"Baseline: {baseline['average']} ({baseline['date']})  New: {average}  Delta: {average - baseline['average']:+.2f}")
    else:
        print(f"Average: {average}")
    print(f"Verdict: {outcome}")

    if outcome == "NEW BASELINE" or (outcome == "PASS" and args.update_baseline):
        _EVAL_DIR.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps(
                {
                    "average": average,
                    "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "examples": len(examples),
                    "dataset": fingerprint,
                    "scores": {result["id"]: result["score"] for result in results},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Baseline recorded in {BASELINE_PATH}")
    return 1 if outcome == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
