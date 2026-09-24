"""Unit tests for the app.cli argument parser.

No LLM or YouTube calls here — only argparse wiring is exercised.
"""
import subprocess
import sys

from app.cli import _output_dir_for_url, build_parser, main


def test_parser_has_estimate_flag():
    parser = build_parser()
    option_strings = {opt for action in parser._actions for opt in action.option_strings}
    assert "--estimate" in option_strings


def test_parser_has_plan_only_flag():
    parser = build_parser()
    option_strings = {opt for action in parser._actions for opt in action.option_strings}
    assert "--plan-only" in option_strings


def test_parser_has_resume_flag():
    parser = build_parser()
    option_strings = {opt for action in parser._actions for opt in action.option_strings}
    assert "--resume" in option_strings


def test_parser_has_force_flag():
    parser = build_parser()
    option_strings = {opt for action in parser._actions for opt in action.option_strings}
    assert "--force" in option_strings


def test_parser_accepts_url_positional():
    parser = build_parser()
    args = parser.parse_args(["https://www.youtube.com/watch?v=aircAruvnKk", "--estimate"])
    assert args.url == "https://www.youtube.com/watch?v=aircAruvnKk"
    assert args.estimate is True
    assert args.plan_only is False
    assert args.resume is None


def test_parser_accepts_resume_without_url():
    parser = build_parser()
    args = parser.parse_args(["--resume", "output/some-book"])
    assert args.resume == "output/some-book"
    assert args.url is None


def test_cli_help_lists_all_flags():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--estimate" in result.stdout
    assert "--plan-only" in result.stdout
    assert "--resume" in result.stdout
    assert "--force" in result.stdout


def test_main_estimate_calls_print_estimate_and_returns_zero(monkeypatch):
    calls = []

    def fake_print_estimate(url):
        calls.append(url)

    monkeypatch.setattr("app.estimate.print_estimate", fake_print_estimate)

    exit_code = main(["https://www.youtube.com/watch?v=aircAruvnKk", "--estimate"])

    assert exit_code == 0
    assert calls == ["https://www.youtube.com/watch?v=aircAruvnKk"]


def test_main_requires_url_or_resume():
    try:
        main(["--estimate"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2


def test_output_dir_for_url_uses_video_id_for_watch_urls():
    result = _output_dir_for_url("https://www.youtube.com/watch?v=aircAruvnKk")
    assert result.name == "aircAruvnKk"
    assert result.parent.name == "output"


def test_output_dir_for_url_uses_path_for_short_urls():
    result = _output_dir_for_url("https://youtu.be/aircAruvnKk")
    assert result.name == "aircAruvnKk"


def test_main_plain_run_calls_run_book_and_returns_zero(monkeypatch):
    calls = []

    def fake_run_book(url, output_dir, force=False):
        calls.append((url, output_dir))
        return "output/aircAruvnKk/book.pdf"

    monkeypatch.setattr("app.graph.run_book", fake_run_book)

    exit_code = main(["https://www.youtube.com/watch?v=aircAruvnKk"])

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == "https://www.youtube.com/watch?v=aircAruvnKk"


def test_main_plain_run_passes_force_flag_through(monkeypatch):
    calls = []

    def fake_run_book(url, output_dir, force=False):
        calls.append(force)
        return "output/aircAruvnKk/book.pdf"

    monkeypatch.setattr("app.graph.run_book", fake_run_book)

    exit_code = main(["https://www.youtube.com/watch?v=aircAruvnKk", "--force"])

    assert exit_code == 0
    assert calls == [True]


def test_main_resume_calls_resume_book_and_returns_zero(monkeypatch):
    calls = []

    def fake_resume_book(output_dir):
        calls.append(output_dir)
        return "output/some-book/book.pdf"

    monkeypatch.setattr("app.graph.resume_book", fake_resume_book)

    exit_code = main(["--resume", "output/some-book"])

    assert exit_code == 0
    assert calls == ["output/some-book"]


def test_main_plan_only_calls_run_plan_and_returns_zero(monkeypatch):
    calls = []

    def fake_run_plan(url, output_dir, force=False):
        calls.append((url, output_dir))
        return (
            [{"video_id": "aircAruvnKk", "title": "T", "url": url}],
            [{"id": "chapter:aircAruvnKk", "video_id": "aircAruvnKk", "title": "T"}],
        )

    monkeypatch.setattr("app.graph.run_plan", fake_run_plan)

    exit_code = main(["https://www.youtube.com/watch?v=aircAruvnKk", "--plan-only"])

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == "https://www.youtube.com/watch?v=aircAruvnKk"


def test_main_plan_only_never_calls_run_book(monkeypatch):
    run_book_calls = []

    monkeypatch.setattr("app.graph.run_plan", lambda url, output_dir, force=False: ([], []))
    monkeypatch.setattr(
        "app.graph.run_book",
        lambda url, output_dir, force=False: run_book_calls.append((url, output_dir)),
    )

    main(["https://www.youtube.com/watch?v=aircAruvnKk", "--plan-only"])

    assert run_book_calls == []
