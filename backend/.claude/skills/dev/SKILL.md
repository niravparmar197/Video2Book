---
name: dev
description: Pick the highest-priority uncompleted task from the current sprint's TASKS.md and implement it with TDD, security scanning, and integration testing. Use when the user wants to implement the next task, work the backlog, or says things like "implement the next task", "work on the sprint", or "/dev".
---

# `/dev` — Implement One Sprint Task (TDD + Security)

You are a senior backend engineer implementing tasks from a sprint backlog. Follow test-driven development with integrated security scanning. **One task per `/dev` invocation — do not combine tasks.**

## Process

### Step 1: Find the Current Sprint

Find the latest `sprints/vN/TASKS.md` (highest N). Read it and identify the highest-priority uncompleted task: the first `- [ ]` item, preferring P0 over P1 over P2, in file order.

If no `sprints/` directory or no uncompleted tasks exist, tell the user and stop — don't invent a task.

### Step 2: Understand Context

- Read the sprint's `PRD.md` for architecture and requirements.
- If a previous sprint exists, read its `WALKTHROUGH.md`.
- Read any existing source files the task will modify.
- Announce: `Working on Task N: [description]`.

### Step 3: Write Tests FIRST (TDD)

Before writing any implementation code, write tests appropriate to the task type:

**Logic/utility tasks → unit tests**
```bash
python -m pytest tests/unit/test_[name].py -v
```

**API route/endpoint tasks → integration tests**
Use the framework's test client (e.g. FastAPI `TestClient`, Flask `test_client()`, Django `APIClient`) to test the endpoint with expected inputs/outputs (success and error cases), including auth and validation failures.
```bash
python -m pytest tests/integration/test_[name].py -v
```

**Data access/DB tasks → integration tests against a real or test-container database**
Never mock the database layer for these — assert against actual query results.

Run the new tests once and confirm they fail for the expected reason (missing implementation) — not because the test itself is broken. If the test is wrong, fix the test before moving on.

### Step 4: Implement

Write the minimum code needed to make the tests pass:
- Follow existing code conventions and patterns (PEP 8, type hints where the codebase already uses them).
- Use the tech stack specified in the PRD.
- Validate all external input at the boundary (request bodies, query params, env vars) — never trust it implicitly.
- Include error handling for user-facing failure modes; don't swallow exceptions silently.

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
- Tests: [N unit, N integration]
- Security: bandit clean, pip-audit clean"
```

Only commit if the user's workflow expects commits per task (this repo has git initialized) and tests + scans are clean.

## Rules

- NEVER skip the test-writing step.
- NEVER skip the security scan step.
- If a task is unclear, re-read the PRD. If still unclear, ask the user.
- One task per `/dev` invocation. Don't combine tasks.
- If you discover a bug in existing code, note it but don't fix it inline — add it as a new task in TASKS.md instead.
- Never commit secrets, API keys, or `.env` files.

## The /dev Flow

```
Read TASKS.md
      │
      ▼
Pick highest-priority
uncompleted task
      │
      ▼
Write tests FIRST (TDD)
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
Update TASKS.md + git commit
```

## Test Directory Convention

```
tests/
├── unit/
│   ├── test_auth.py
│   └── test_metrics.py
└── integration/
    ├── test_api_auth.py
    └── test_api_metrics.py
```
