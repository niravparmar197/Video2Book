"""Command-line entry point for the Video2Book core engine.

Usage:
    python -m app.cli "<video url>" --estimate
    python -m app.cli "<video url>" --plan-only
    python -m app.cli "<video url>"
    python -m app.cli --resume output/<book>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _output_dir_for_url(url: str) -> Path:
    """Derive a stable output/<slug> directory name from a video URL.

    No API call needed: parses the URL itself so the CLI can pick an output
    directory before the fetch step has even run.
    """
    parsed = urlparse(url)
    video_id = None
    if parsed.hostname and "youtube.com" in parsed.hostname:
        video_id = parse_qs(parsed.query).get("v", [None])[0]
    elif parsed.hostname and "youtu.be" in parsed.hostname:
        video_id = parsed.path.strip("/")

    slug = video_id or re.sub(r"[^A-Za-z0-9_-]+", "-", url).strip("-")[:64]
    return Path("output") / slug


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Turn a YouTube video (or playlist) into a PDF book.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="YouTube video or playlist URL",
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Print a cost/time estimate and exit without calling the writer LLM",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Stop after the book outline is written (outline.json / outline.md)",
    )
    parser.add_argument(
        "--resume",
        metavar="OUTPUT_DIR",
        default=None,
        help="Resume a previous run from its output/<book> directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if the playlist exceeds MAX_BOOK_HOURS or MAX_BOOK_COST_USD",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.resume is None and args.url is None:
        parser.error("either a video URL or --resume OUTPUT_DIR is required")

    if args.estimate:
        from app.estimate import print_estimate

        print_estimate(args.url)
        return 0

    if args.plan_only:
        from app.graph import run_plan

        output_dir = _output_dir_for_url(args.url)
        _videos, chapters = run_plan(args.url, output_dir, force=args.force)
        print(f"Outline written: {output_dir / 'outline.md'} ({len(chapters)} chapters)")
        return 0

    if args.resume:
        from app.graph import resume_book

        pdf_path = resume_book(args.resume)
        print(f"Book updated: {pdf_path}")
        return 0

    from app.graph import run_book

    output_dir = _output_dir_for_url(args.url)
    pdf_path = run_book(args.url, output_dir, force=args.force)
    print(f"Book written: {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
