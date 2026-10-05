"""Load test: several users queue several books at once against a running
API + worker, to see how the queue, the per-user limit and the shared LLM
rate limit behave under real concurrency (backend/AGENTS.md checklist).

    python scripts/load_test.py --users 3 --books 2 \\
        --url https://www.youtube.com/watch?v=mQM3V8E13yc

Makes real books (real YouTube + LLM calls): use a short video. Each user
signs up (pass --invite-code if the API requires one; the API's per-IP
sign-up limit must allow --users sign-ups, see SIGNUP_LIMIT_PER_IP_PER_HOUR),
queues --books books at the same moment, approves each outline as it becomes
ready, and the script waits until every book is done or failed. It prints
per-book timings (queued -> outline ready -> done), how many requests were
refused with 429 (the per-user limit), failures, and the totals. Deletes the
test accounts (and their books) at the end unless --keep.
"""

import argparse
import asyncio
import statistics
import sys
import time
import uuid

import httpx

TERMINAL = {"done", "failed"}


class BookRun:
    def __init__(self, user: int, index: int):
        self.user, self.index = user, index
        self.book_id: str | None = None
        self.status = "not created"
        self.refused: str | None = None
        self.started = time.monotonic()
        self.outline_at: float | None = None
        self.finished_at: float | None = None
        self.error: str | None = None


async def _request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    """One call, retried on a dropped connection (seen under load: the
    server closed a kept-alive connection the client was reusing)."""
    for attempt in range(4):
        try:
            return await client.request(method, path, **kwargs)
        except httpx.TransportError:
            if attempt == 3:
                raise
            await asyncio.sleep(1 + attempt)
    raise AssertionError("unreachable")


async def _sign_up(client: httpx.AsyncClient, invite_code: str | None) -> dict:
    email = f"load-{uuid.uuid4().hex[:10]}@example.com"
    resp = await _request(client, "POST", "/users", json={"email": email, "accept_terms": True, "invite_code": invite_code})
    resp.raise_for_status()
    return {"X-API-Key": resp.json()["api_key"]}


async def _run_book(client: httpx.AsyncClient, headers: dict, run: BookRun, url: str, poll: float, timeout: float):
    resp = await _request(client, "POST", "/books/youtube", json={"url": url}, headers=headers)
    if resp.status_code == 429:
        run.refused, run.status = resp.json().get("detail", "429"), "refused"
        return
    resp.raise_for_status()
    run.book_id, run.status = resp.json()["id"], resp.json()["status"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(poll)
        book = (await _request(client, "GET", f"/books/{run.book_id}", headers=headers)).json()
        run.status = book["status"]
        if run.status == "outline_ready" and run.outline_at is None:
            run.outline_at = time.monotonic()
            chapters = (await _request(client, "GET", f"/books/{run.book_id}/outline", headers=headers)).json()
            edits = [{"id": c["id"], "skip": c["skip"], "locked": c["locked"]} for c in chapters]
            (await _request(client, "PUT", f"/books/{run.book_id}/outline", json=edits, headers=headers)).raise_for_status()
        if run.status in TERMINAL:
            run.finished_at = time.monotonic()
            run.error = book.get("error_message")
            return
    run.error = f"still '{run.status}' after {timeout:.0f}s"


def _seconds(start: float, end: float | None) -> str:
    return f"{end - start:6.0f}s" if end else "     -"


async def main(args: argparse.Namespace) -> int:
    async with httpx.AsyncClient(base_url=args.api, timeout=60) as client:
        users = [await _sign_up(client, args.invite_code) for _ in range(args.users)]
        runs = [BookRun(u, b) for u in range(args.users) for b in range(args.books)]
        started = time.monotonic()
        outcomes = await asyncio.gather(
            *(_run_book(client, users[run.user], run, args.url, args.poll, args.timeout) for run in runs),
            return_exceptions=True,
        )
        for run, outcome in zip(runs, outcomes):
            if isinstance(outcome, Exception):
                run.error = f"script error: {outcome!r}"
        total = time.monotonic() - started

        print(f"\n{args.users} user(s) x {args.books} book(s) of {args.url}")
        print(f"{'user':>4} {'book':>4}  {'status':<10} {'outline':>7} {'done':>7}  note")
        for run in runs:
            note = run.refused or run.error or ""
            print(
                f"{run.user:>4} {run.index:>4}  {run.status:<10} {_seconds(run.started, run.outline_at)} "
                f"{_seconds(run.started, run.finished_at)}  {note[:80]}"
            )
        done = [run for run in runs if run.status == "done"]
        durations = [run.finished_at - run.started for run in done if run.finished_at]
        print(
            f"\ndone {len(done)}, failed {sum(r.status == 'failed' for r in runs)}, "
            f"refused (429) {sum(r.status == 'refused' for r in runs)}, "
            f"unfinished {sum(r.status not in TERMINAL | {'refused'} for r in runs)}; wall time {total:.0f}s"
        )
        if durations:
            print(f"book time: median {statistics.median(durations):.0f}s, max {max(durations):.0f}s")

        if not args.keep:
            # Books still being made are cancelled first (DELETE refuses them).
            for run in runs:
                if run.book_id and run.status not in TERMINAL:
                    await _request(client, "POST", f"/books/{run.book_id}/cancel", headers=users[run.user])
            for headers in users:
                await _request(client, "DELETE", "/users/me", headers=headers)
        return 0 if len(done) + sum(r.status == "refused" for r in runs) == len(runs) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--url", required=True, help="a short YouTube video")
    parser.add_argument("--users", type=int, default=3)
    parser.add_argument("--books", type=int, default=2, help="books each user queues at once")
    parser.add_argument("--invite-code")
    parser.add_argument("--poll", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=3600.0, help="per book, seconds")
    parser.add_argument("--keep", action="store_true", help="keep the test accounts and books")
    sys.exit(asyncio.run(main(parser.parse_args())))
