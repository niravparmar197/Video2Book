"""Eval gate for prompt / model changes (root AGENTS.md: a prompt or model
change ships only if the average judge score does not drop).

    python -m app.eval                      # run the eval set, compare to the baseline
    python -m app.eval --update-baseline    # also record this run as the new baseline
    python -m app.eval --ref HEAD~1         # A/B: score HEAD~1's prompts too, now, and compare
    python -m app.eval --add-example output/<book> --genre podcast
                                            # add a book's first chunk to the local set

Each example is a real transcript excerpt + its topics + its genre. The
current writer prompts write notes for it, the deterministic clean-ups run
(as in a real book), and the judge scores the result -- one write and one
judge call per example, no refine, so the score measures the prompts
themselves. Examples come from the LangSmith dataset EVAL_DATASET_NAME when
it is set (each example's inputs: transcript, topics, genre, title),
otherwise from eval/dataset.jsonl.

Verdict: no baseline yet -> this run becomes it. Otherwise each example is
compared with its own earlier score (the baseline's, or --ref's): a mean
change worse than both 0.25 and two standard errors is a real drop ->
BLOCKED when EVAL_ON_RELEASE=true (exit code 1), else WARN; anything else
is PASS (the 15-example average moves ~0.4 between identical runs, so a
plain average comparison flagged noise as regressions).
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
# One judge call swings by +-2 on identical notes; 2 runs still left the
# 15-example average moving ~0.4 between identical reruns.
_JUDGE_RUNS = int(os.environ.get("EVAL_JUDGE_RUNS", "3"))
# A drop counts only past both this and two standard errors of the paired
# per-example differences -- smaller ones are noise, not a regression.
_MIN_REAL_DROP = 0.25


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


def paired_change(scores: dict[str, float], old_scores: dict[str, float]) -> tuple[float, float, int]:
    """(mean change, its standard error, examples compared) over the
    examples scored in both runs. Comparing each example with itself
    removes most of the between-example spread that made two averages
    differ by 0.4 on identical code."""
    shared = [key for key in scores if key in old_scores]
    changes = [scores[key] - old_scores[key] for key in shared]
    if not changes:
        return 0.0, 0.0, 0
    mean = statistics.mean(changes)
    error = statistics.stdev(changes) / len(changes) ** 0.5 if len(changes) > 1 else 0.0
    return mean, error, len(changes)


def is_real_drop(change: float, standard_error: float) -> bool:
    return change < -max(_MIN_REAL_DROP, 2 * standard_error)


def verdict(
    average: float,
    baseline: dict | None,
    gate_on: bool,
    fingerprint: str = "",
    scores: dict[str, float] | None = None,
) -> str:
    # No fingerprint (a baseline from before it was recorded) is not comparable either.
    if baseline is None or baseline.get("dataset") != fingerprint:
        return "NEW BASELINE"
    if scores and baseline.get("scores"):
        change, error, compared = paired_change(scores, baseline["scores"])
        if compared:
            if not is_real_drop(change, error):
                return "PASS"
            return "BLOCKED" if gate_on else "WARN"
    if average >= baseline["average"]:
        return "PASS"
    return "BLOCKED" if gate_on else "WARN"


def run_at_ref(ref: str) -> dict[str, float]:
    """Score the eval set with the prompts and code of git `ref`, in a
    temporary worktree (this .env copied in), for a same-day A/B: prompts
    are compared on the same examples, the same models and the same
    provider load, instead of against a number saved weeks ago."""
    import shutil
    import subprocess  # nosec B404 - fixed git/python argument lists
    import tempfile

    engine_dir = Path(__file__).resolve().parent.parent
    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=engine_dir, capture_output=True, text=True, check=True
    )
    repo = Path(toplevel.stdout.strip())
    workdir = Path(tempfile.mkdtemp(prefix="v2b-eval-"))
    tree = workdir / "tree"
    subprocess.run(["git", "worktree", "add", "--detach", str(tree), ref], cwd=repo, check=True, capture_output=True)
    try:
        engine_in_tree = tree / engine_dir.relative_to(repo)
        if (engine_dir / ".env").exists():
            shutil.copyfile(engine_dir / ".env", engine_in_tree / ".env")
        # The current dataset, so both sides score the same examples.
        if DATASET_PATH.exists():
            (engine_in_tree / "eval").mkdir(exist_ok=True)
            shutil.copyfile(DATASET_PATH, engine_in_tree / "eval" / "dataset.jsonl")
        out = workdir / "scores.json"
        script = (
            "import json, sys; from concurrent.futures import ThreadPoolExecutor; import app.eval as e; "
            "_, ex = e.load_examples(); "
            "r = list(ThreadPoolExecutor(4).map(e.score_example, ex)); "
            "json.dump({x['id']: x['score'] for x in r}, open(sys.argv[1], 'w'))"
        )
        subprocess.run([sys.executable, "-c", script, str(out)], cwd=engine_in_tree, check=True)
        return json.loads(out.read_text(encoding="utf-8"))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=repo, capture_output=True)
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval", description=__doc__.split("\n\n")[0])
    parser.add_argument("--add-example", metavar="BOOK_DIR")
    parser.add_argument("--genre", default="lecture")
    parser.add_argument("--video", help="with --add-example: which video of a playlist book")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument(
        "--ref",
        metavar="GIT_REF",
        help="A/B: also score the eval set with this commit's prompts, now, and compare example by example",
    )
    parser.add_argument("--json", metavar="PATH", help="write the per-example scores to this file")
    args = parser.parse_args(argv)

    if args.add_example:
        example = add_example(args.add_example, args.genre, args.video)
        print(f"Added {example['id']} ({example['genre']}) to {DATASET_PATH}")
        return 0

    # Feedback quotes the notes (non-breaking hyphens, arrows); a Windows
    # console's code page crashed the report after 14 minutes of scoring.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    load_settings()  # populate the environment from .env (API keys, EVAL_*)
    source, examples = load_examples()
    if not examples:
        print(f"No eval examples in {source}. Add some with --add-example output/<book>.")
        return 1

    # The old side first (a subprocess): the two runs share one rate limit.
    ref_scores = run_at_ref(args.ref) if args.ref else None

    with ThreadPoolExecutor(max_workers=_PARALLEL_EXAMPLES) as pool:
        results = list(pool.map(score_example, examples))
    average = round(statistics.mean(result["score"] for result in results), 2)
    scores = {result["id"]: result["score"] for result in results}
    if args.json:
        Path(args.json).write_text(json.dumps(scores, indent=2), encoding="utf-8")

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) if BASELINE_PATH.exists() else None
    gate_on = os.environ.get("EVAL_ON_RELEASE", "").strip().lower() in {"1", "true", "yes", "on"}
    fingerprint = dataset_fingerprint(examples)
    if ref_scores is not None:
        # Same-day A/B against the ref replaces the saved baseline.
        compare_to = {
            "average": statistics.mean(ref_scores.values()),
            "date": f"ref {args.ref}",
            "dataset": fingerprint,
            "scores": ref_scores,
        }
    else:
        compare_to = baseline
    outcome = verdict(average, compare_to, gate_on, fingerprint, scores)

    print(f"Dataset: {source} ({len(examples)} examples, {_JUDGE_RUNS} judge runs each)")
    old_scores = (compare_to or {}).get("scores") or {}
    for result in results:
        old = f" (was {old_scores[result['id']]})" if result["id"] in old_scores else ""
        print(f"  {result['id']:<14} {result['genre']:<8} {result['score']}/10{old}  {result['feedback'][:90]}")
    if compare_to:
        print(
            f"Compared with: {compare_to['date']}  Old: {round(compare_to['average'], 2)}  New: {average}  "
            f"Delta: {average - compare_to['average']:+.2f}"
        )
        change, error, compared = paired_change(scores, old_scores)
        if compared:
            print(
                f"Per example: {change:+.2f} +- {error:.2f} (standard error, {compared} examples); "
                f"a drop counts past {-max(_MIN_REAL_DROP, 2 * error):.2f}"
            )
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
                    "scores": scores,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Baseline recorded in {BASELINE_PATH}")
    return 1 if outcome == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
