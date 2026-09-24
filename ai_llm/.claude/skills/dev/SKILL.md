---
name: dev
description: Pick the highest-priority uncompleted task from the current sprint's TASKS.md and implement it with TDD, security scanning, and pipeline/integration testing. Use when the user wants to implement the next task, work the backlog, or says things like "implement the next task", "work on the sprint", or "/dev".
---

# `/dev` — Implement One Sprint Task (TDD + Security)

You are a senior AI/ML engineer implementing tasks from a sprint backlog. Follow test-driven development with integrated security scanning. **One task per `/dev` invocation — do not combine tasks.**

## Process

### Step 1: Find the Current Sprint

Find the latest `sprints/vN/TASKS.md` (highest N). Read it and identify the highest-priority uncompleted task: the first `- [ ]` item, preferring P0 over P1 over P2, in file order.

If no `sprints/` directory or no uncompleted tasks exist, tell the user and stop — don't invent a task.

### Step 2: Understand Context

- Read the sprint's `PRD.md` for architecture and requirements.
- If a previous sprint exists, read its `WALKTHROUGH.md`.
- Read any existing source files the task will modify (prompts, chains, pipelines, model configs).
- Announce: `Working on Task N: [description]`.

### Step 3: Write Tests FIRST (TDD)

Before writing any implementation code, write tests appropriate to the task type:

**Logic/utility tasks → unit tests**
```bash
python -m pytest tests/unit/test_[name].py -v
```

**LLM call / prompt / chain tasks → unit tests with the model call mocked or stubbed**
Never make real paid API calls in a unit test. Mock the client (e.g. `unittest.mock`, a fake LLM class) and assert on: the prompt/payload sent, parsing of a fixed sample response, and error/retry handling on a simulated failure.

**Pipeline / data processing tasks → integration tests against fixture data**
Use small, checked-in sample inputs (`tests/fixtures/`) and assert on the final structured output, not exact model wording.

**Evaluation-sensitive tasks (e.g. output quality, groundedness) → golden-file tests**
Compare structured output shape and key fields against a stored expected result; flag (don't hard-fail) on wording drift if the task is inherently non-deterministic.

Run the new tests once and confirm they fail for the expected reason (missing implementation) — not because the test itself is broken. If the test is wrong, fix the test before moving on.

### Step 4: Implement

Write the minimum code needed to make the tests pass:
- Follow existing code conventions and patterns (PEP 8, type hints where the codebase already uses them).
- Use the model/provider and libraries specified in the PRD.
- Never hardcode API keys or secrets — read from environment variables.
- Add timeouts and error handling around all external model/API calls; don't let one failure crash a pipeline run.
- Validate and sanitize any user-supplied text before it's interpolated into a prompt (prompt-injection surface).

### Step 5: Run Tests

```bash
python -m pytest tests/ -v
```

If tests fail:
1. Read the error message and traceback.
2. Fix the implementation (not the test, unless the test itself is wrong).
3. Re-run until green.

### Step 6: Security Scan

After tests pass, run security scanning:

```bash
# Static analysis (SAST)
bandit -r app/ -ll
# Dependency vulnerability audit
pip-audit
```

If bandit or `pip-audit` finds issues:
1. Fix them immediately.
2. Re-run tests to make sure fixes don't break anything.
3. Re-run the scanner to confirm the findings are resolved.

Also check: no API keys, tokens, or `.env` values are committed, and no raw user input is passed into a prompt without sanitization.

### Step 6.5: LangSmith Eval Gate (prompt/model changes only)

If this task touched `app/prompts/*.md`, a prompt used by `write.py`/`verify.py`/`topics.py`, or the model/provider config (`LLM_PROVIDER`, model names), invoke the `/eval` skill before marking the task done.

If `/eval` reports BLOCKED, the task is **not done** — revise the prompt/model change and re-run `/eval`, don't mark it complete with a regression. Record the before/after score `/eval` reports in the TASKS.md completed line (Step 7).

Skip this step for tasks that don't touch prompts or model config.

### Step 7: Update TASKS.md

Mark the task complete, keeping the acceptance/files lines and appending a completed line:

```
- [x] Task N: [description] (P0)
  - Acceptance: [criteria]
  - Files: [files]
  - Completed: [date] — [brief note of what was done]
```

### Step 8: Commit

```bash
git add -A
git commit -m "feat(vN): Task N — [description]

- Implemented [what]
- Tests: [N unit, N integration/fixture]
- Security: bandit clean, pip-audit clean"
```

Only commit if the user's workflow expects commits per task (this repo has git initialized) and tests + scans are clean.

## Rules

- NEVER skip the test-writing step.
- NEVER skip the security scan step.
- NEVER call a real paid model API from an automated test — mock or stub it.
- NEVER mark a prompt or model-config task done if it skipped the LangSmith eval gate (Step 6.5) or shipped with a dropped judge score while `EVAL_ON_RELEASE=true`.
- If a task is unclear, re-read the PRD. If still unclear, ask the user.
- One task per `/dev` invocation. Don't combine tasks.
- If you discover a bug in existing code, note it but don't fix it inline — add it as a new task in TASKS.md instead.
- Never commit API keys, tokens, or `.env` files.

## The /dev Flow

```
Read TASKS.md
      │
      ▼
Pick highest-priority
uncompleted task
      │
      ▼
Write tests FIRST (TDD, model calls mocked)
      │
      ▼
Run tests ── PASS unexpectedly ──▶ fix the test (it's wrong)
      │
     FAIL (expected — no impl yet)
      │
      ▼
Implement the code
      │
      ▼
Run tests ── FAIL ──▶ fix code, re-run ──┐
      │                                   │
     PASS ◀───────────────────────────────┘
      │
      ▼
bandit + pip-audit ── FINDINGS ──▶ fix, re-run ──┐
      │                                            │
    CLEAN ◀─────────────────────────────────────────┘
      │
      ▼
Prompt/model task? ── yes ──▶ run /eval ── BLOCKED ──▶ fix, re-run ──┐
      │                            │                                 │
      no                        PASS ◀────────────────────────────────┘
      │                            │
      └──────────────┬─────────────┘
                      ▼
      Update TASKS.md + git commit
```

## Test Directory Convention

```
tests/
├── fixtures/
│   ├── sample_input.json
│   └── expected_output.json
├── unit/
│   ├── test_prompt_builder.py
│   └── test_llm_client.py
└── integration/
    └── test_pipeline.py
```
