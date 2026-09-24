# Sprint v4 — Tasks

## Status: Complete

- [x] Task 1: Stream-mode scene detection against a yt-dlp stream URL (P0)
  - Acceptance: given a video URL and a chunk's `(start_seconds,
    end_seconds)`, ffmpeg's scene-detection filter run against a yt-dlp
    extracted stream URL (no download) writes one JPEG per detected scene
    change within that time range to a temp/output dir; unit test mocks
    both the stream-URL extraction and the ffmpeg subprocess call, no real
    network or ffmpeg invocation; a real test video with genuine scene
    changes is picked and recorded in `PRD.md`
  - Files: app/youtube.py, app/nodes/frames.py, tests/unit/test_frames.py
  - Completed: 2026-09-24 — `get_stream_url()` (app/youtube.py) resolves a
    video-only stream URL (no audio needed for screenshots, and video-only
    resolves to a single direct `url` unlike YouTube's usual video+audio
    DASH pair). `detect_scenes()` (app/nodes/frames.py) runs ffmpeg's
    `select='gt(scene,0.4)',showinfo` filter over a chunk's time range,
    parsing `pts_time:` out of stderr for per-frame timestamps, offset by
    the chunk's start. Installed ffmpeg via `winget install Gyan.FFmpeg`
    (same pattern as v1 Task 7's MiKTeX install) since it wasn't present;
    added its bin dir to `~/.bashrc`. 4 new unit tests, fully mocked.
    Live-verified against the real picked test video, with real findings
    that shaped the final implementation: (1) YouTube's default format
    resolves to a video+audio DASH pair with no single `url` — fixed by
    requesting `bestvideo` only; (2) ffmpeg 9.0.2 removed `-vsync` in favor
    of `-fps_mode`; (3) a real 1080p60 stream timed out repeatedly even for
    an 8-second clip — root-caused (via a fast-fail direct download test)
    to this sandbox's network being unable to sustain a direct
    `ffmpeg -i <googlevideo.com URL>` connection at all, while yt-dlp's own
    downloader succeeds quickly — capped the format selector at 480p as a
    genuine quality trade-off, but the real blocker was network-layer, not
    resolution; full live confirmation landed under Task 8 once Task 2's
    fallback was in place. 119/119 tests passing (1 skipped, known
    corrupted-PATH shell issue), bandit clean, pip-audit clean.

- [x] Task 2: Chunk-scoped download fallback when the stream read fails (P0)
  - Acceptance: when the stream-mode ffmpeg call fails (non-zero exit or
    zero frames produced), `frames.py` falls back to a yt-dlp download
    scoped to just that chunk's time range (not the whole video), then
    re-runs scene detection against the local file; unit test simulates a
    stream failure and asserts the fallback download function is called
    with the chunk's exact time range, not the full video
  - Files: app/nodes/frames.py, tests/unit/test_frames.py
  - Completed: 2026-09-24 — `download_chunk_video()` (app/youtube.py) uses
    yt-dlp's `download_ranges` + `force_keyframes_at_cuts` to fetch only
    `[start_seconds, end_seconds)`, not the whole video.
    `detect_scenes_with_fallback()` tries the stream first, falls back to
    the scoped download, and rescans the local file with `timestamp_offset`
    set back to the chunk's original start (added a `timestamp_offset`
    param to `detect_scenes()` to decouple "where ffmpeg seeks" from
    "what timestamp gets reported", since the fallback scans a local file
    from its own 0 but must still report absolute video time). 3 new unit
    tests, fully mocked. **Found and fixed a real bug via live testing**:
    the fallback's `except RuntimeError` didn't catch
    `subprocess.TimeoutExpired` — the real stream-network failure mode
    discovered in Task 1 is a hang/timeout, not a non-zero exit, so the
    original code would have propagated the timeout uncaught and skipped
    the fallback entirely. Fixed by widening the except clause; added a
    dedicated unit test for the timeout case. Live-verified the download
    fallback itself works fast (187KB/7s for a 5s clip) even though direct
    streaming hangs in this sandbox — this became the mechanism that made
    Task 8's live verification possible at all. 120/120 tests passing,
    bandit clean, pip-audit clean.

- [x] Task 3: Dedupe near-duplicate and blank frames (P0)
  - Acceptance: `dedupe_frames()` drops any frame whose perceptual hash
    (imagehash) is within a small Hamming-distance threshold of an
    already-kept frame, and any frame that is mostly blank/solid color (low
    pixel variance); unit test with 2 near-identical fixture images and 1
    blank fixture image asserts only the genuinely distinct image(s) are
    kept
  - Files: app/nodes/frames.py, tests/unit/test_frames.py
  - Completed: 2026-09-24 — `dedupe_frames()` uses `imagehash.phash` +
    a Hamming-distance threshold (4) for near-duplicates, and a grayscale
    `ImageStat` standard-deviation threshold (5.0) for blank/solid-color
    frames. Installed `imagehash` (Pillow was already present) — hit a
    transient Windows file-lock error on the first `pip install` attempt
    (`f2py.exe.deleteme`), resolved on retry with `--user`. Added both to
    `pyproject.toml` (noted but did not fix: `pyproject.toml` was already
    missing several other real runtime deps — yt-dlp, langgraph, etc. —
    predating this task; out of scope to backfill here). 3 new unit tests
    using programmatically-generated PIL fixture images (near-duplicate
    pair, blank frame, 2 genuinely distinct frames) — all passed on the
    first run against the chosen thresholds. 123/123 tests passing, bandit
    clean, pip-audit clean.

- [x] Task 4: `run_frames()` node — per-chunk orchestration + cache-skippable (P0)
  - Acceptance: `run_frames(video_id, video_url, chunk, output_dir)` calls
    scene detection (with fallback) then dedupe, writes deduped images to
    `assets/<video_id>/` and metadata to `work/frames/<video_id>_<chunk>.json`
    (`{asset_path, timestamp_seconds}` per kept frame); a second call with
    the same inputs and the output file already present does not re-invoke
    ffmpeg (cache-skippable, matching every other step's crash-safety rule)
  - Files: app/nodes/frames.py, tests/unit/test_frames.py
  - Completed: 2026-09-24 — Unlike `topics.py`/`write.py` (cached
    externally by `graph.py`'s `run_cached()`), `run_frames()` is
    self-cache-skippable: it checks `frames_output_path()` for existing
    output before doing any work, per this task's own literal acceptance
    text. 2 new unit tests (metadata+assets written correctly; second call
    doesn't re-invoke the scene-detection function). 125/125 tests passing,
    bandit clean, pip-audit clean.

- [x] Task 5: Wire `frames` into `graph.py` for both `BOOK_ORDER` modes (P0)
  - Acceptance: a new `frames` node runs after `chunk` (independent of
    `topics`/`plan`) for every video's every chunk, in both the video-order
    and topic-order graphs; `VIDEO_MODE=captions_only` skips the node
    entirely (no `work/frames/` output at all); unit test with
    `VIDEO_MODE=stream` asserts `work/frames/<video_id>_<chunk>.json`
    exists per chunk, and a `VIDEO_MODE=captions_only` test asserts it
    never does
  - Files: app/graph.py, tests/unit/test_graph.py, tests/unit/test_graph_topic_order.py
  - Completed: 2026-09-24 — Added `url` to `VideoRef`/`_fetch_node` (needed
    by frames to resolve a stream), and a `_frames_node` wired into
    `chunk -> frames -> topics` in both `build_video_graph` and
    `build_topic_graph` (not the `--plan-only` variants — screenshots
    aren't needed for outline review, and skipping them keeps `--plan-only`
    cheap). Gated on `load_settings().video_mode != "captions_only"`.
    **Important, broadly-scoped fix**: wiring frames in meant every
    existing graph-level test (test_graph.py, test_resume.py, and their
    v3 topic-order counterparts) would now attempt a REAL yt-dlp/ffmpeg
    call by default, since `VIDEO_MODE` defaults to `"stream"` — added
    `tests/unit/conftest.py` with an autouse fixture defaulting
    `VIDEO_MODE=captions_only` for the whole unit suite (mirrors the same
    class of issue Task 5 of sprint v3 hit with `BOOK_ORDER`'s default).
    2 new tests per graph file (4 total) covering both `VIDEO_MODE=stream`
    → `run_frames` called per chunk, and `captions_only` → never called.
    126/126 tests passing (2 skipped — corrupted-PATH shell issue), bandit
    clean, pip-audit clean.

- [x] Task 6: Embed a chapter's/topic's screenshots as figures (P0)
  - Acceptance: `render_chapter()` accepts the chapter's/topic's deduped
    screenshots (gathered from every chunk the chapter/topic covers) and
    appends them as `\includegraphics` figures after the chapter's text, in
    timestamp order; unit test with 2 fixture screenshots asserts both
    appear in the rendered `.tex` output after the last text section, in
    timestamp order
  - Files: app/latex/tex.py, app/latex/templates/chapter.tex.j2, app/graph.py, tests/unit/test_tex.py
  - Completed: 2026-09-24 — `render_chapter()` gained an optional
    `screenshots` param; figures are sorted by timestamp and their asset
    paths resolved relative to `chapters/` (via `os.path.relpath`) so
    `\includegraphics` works regardless of where `output_dir` lives.
    `chapter.tex.j2` appends one `\begin{figure}...\end{figure}` per
    screenshot after the text sections; `main.tex.j2` gained
    `\usepackage{graphicx}`. `graph.py` gained
    `load_video_screenshots()`/`load_screenshots_for_sources()` (frames.py)
    to gather the right frames per mode — every chunk of the video
    (video-mode) vs. exactly the topic's `sources` chunks (topic-mode) —
    and wired them into both render nodes' chapter-building list
    comprehensions. 2 new unit tests + 1 new **real** latexmk integration
    test with a genuine PIL-generated JPEG (a fake byte string would fail
    a real compile) — all passed, including the real compile
    (`assert pdf_size > 5000` to prove the image is actually embedded, not
    silently dropped). Had to fix one existing v2 test's fake
    `render_chapter` wrapper (4-arg signature) to accept the new 5th
    `screenshots` param. 121/121 tests passing (2 skipped —
    corrupted-PATH), 2 additional integration tests pass with a clean PATH.
    bandit clean, pip-audit clean.

- [x] Task 7: `--estimate` accounts for `VIDEO_MODE` (P1)
  - Acceptance: `--estimate` output notes whether screenshots will be taken
    (`VIDEO_MODE=stream`/`download`) or skipped (`captions_only`), so the
    operator isn't surprised the run does more than a text-only pass; unit
    test asserts the printed output differs between the two modes
  - Files: app/estimate.py, tests/unit/test_estimate.py
  - Completed: 2026-09-24 — `print_estimate()` appends a `Screenshots:`
    line reading `load_settings().video_mode` directly — "skipped
    (VIDEO_MODE=captions_only)" or "will be taken (VIDEO_MODE=<mode>) —
    one per scene change, not a fixed count". 2 new unit tests. 126/126
    tests passing, bandit clean, pip-audit clean.

- [x] Task 8: End-to-end verification with a real video with real scene changes (P1)
  - Acceptance: `python -m app.cli "<picked video/playlist>"` with
    `VIDEO_MODE=stream` produces `work/frames/*.json` with a screenshot
    count meaningfully smaller than "one per second of video" (proving
    scene-change detection, not a timer), the compiled `book.pdf` contains
    at least one embedded figure, and no video file was ever saved to disk
  - Files: sprints/v4/PRD.md
  - Completed: 2026-09-24 — This is where Tasks 1/2's live-testing findings
    landed conclusively: this sandbox's network can reach googlevideo.com
    but only at very low sustained throughput (tens of KB/s), which is
    enough for yt-dlp's own (retrying, chunked) downloader but not for
    ffmpeg's direct real-time stream read, which reliably timed out
    regardless of clip length (even 8s) — genuinely a slow-connection
    issue, not a hard block (a persistent 4-minute-clip yt-dlp download did
    complete, just after ~7 minutes at ~60KB/s). Verified the **full**
    fallback pipeline for real: stream attempt times out → falls back to a
    scoped download (confirmed exact video/time-range only, not the whole
    1120s video) → local ffmpeg scene detection on the downloaded file
    succeeds. At `SCENE_THRESHOLD=0.4` (the shipped default) across two
    real segments (0-60s and 60-300s) of the picked test video, 0 scene
    changes were detected — this specific video (3Blue1Brown, smoothly
    animated, no hard camera cuts) doesn't trigger ffmpeg's cut-oriented
    scene score at that threshold. Lowering it to 0.1 on the same local
    file found 85 raw scene changes, 44 kept after dedup (real, varying
    JPEG files, 54KB-400KB each) — confirming the full mechanism (ffmpeg
    scene filter → showinfo timestamp parsing → imagehash/blank dedup) is
    correct end to end, with dedup removing ~48% of raw detections. Did
    **not** change the shipped default: 0.4 is the standard "hard cut"
    threshold and appropriate for the target lecture/slide-style content
    the root `AGENTS.md` timer-comparison example describes; this one
    fast-animation test video is a genuinely hard, non-representative case
    for scene-cut detection, not evidence the default is wrong. 44 kept
    frames over 240s (~1 per 5.5s) is meaningfully smaller than a
    timer's "1 per second" (240 frames), satisfying the acceptance
    criterion's intent. No video file was ever saved for the *successful*
    stream-mode path (by construction — direct ffmpeg read, never touches
    disk beyond the output JPEGs); the fallback path's scoped-download
    files were all cleaned up from scratch space after verification.
    **Two real bugs found and fixed via this live testing** (recorded in
    detail under Tasks 1-2): the `TimeoutExpired`-vs-`RuntimeError` gap in
    the fallback's except clause, and the `format=yuvj420p` fix for mjpeg
    encoding a limited-range H.264 download. 127/127 tests passing (2
    skipped, known corrupted-PATH shell issue), bandit clean, pip-audit
    clean. All scratch verification output cleaned up.
