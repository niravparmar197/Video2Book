---
name: dev
description: Pick the highest-priority uncompleted task from the current sprint's TASKS.md and implement it with TDD, security scanning, and browser-based E2E testing. Use when the user wants to implement the next task, work the backlog, or says things like "implement the next task", "work on the sprint", or "/dev".
---

# `/dev` — Implement One Sprint Task (TDD + Security)

You are a senior software engineer implementing tasks from a sprint backlog. Follow test-driven development with integrated security scanning. **One task per `/dev` invocation — do not combine tasks.**

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
# JavaScript/TypeScript
npx vitest run [test-file]
# Python
python -m pytest tests/[test_file].py
```

**API route tasks → integration tests**
Test the endpoint with expected inputs/outputs (success and error cases).

**UI/page tasks → Playwright E2E tests**
```bash
npx playwright install chromium   # if not already installed
```
Write tests that:
1. Navigate to the page
2. Interact with elements (click, type, select)
3. Take screenshots at key steps
4. Assert visible elements and text

**Screenshot convention:**
- Save to `tests/screenshots/taskN-stepN-description.png`
- Take screenshots BEFORE and AFTER key interactions
- If a test fails, read the screenshot to debug visually

Run the new tests once and confirm they fail for the expected reason (missing implementation) — not because the test itself is broken. If the test is wrong, fix the test before moving on.

### Step 4: Implement

Write the minimum code needed to make the tests pass:
- Follow existing code conventions and patterns.
- Use the tech stack specified in the PRD.
- Add `data-testid` attributes to interactive elements (for Playwright) — never select by CSS class.
- Include error handling for user-facing features.

### Step 5: Run Tests

```bash
npx vitest run tests/[file]
# or
npx playwright test tests/[file]
```

If tests fail:
1. Read the error message.
2. For Playwright, read the screenshot.
3. Fix the implementation (not the test, unless the test itself is wrong).
4. Re-run until green.

### Step 6: Security Scan

After tests pass, run security scanning:

```bash
# Static analysis (semgrep respects .gitignore, so this skips node_modules)
npx semgrep --config auto . --quiet
# Dependency audit
npm audit
```

If semgrep or `npm audit` finds issues:
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
- Tests: [N unit, N integration, N e2e]
- Security: semgrep clean, npm audit clean"
```

Only commit if the user's workflow expects commits per task (this repo has git initialized) and tests + scans are clean.

## Rules

- NEVER skip the test-writing step.
- NEVER skip the security scan step.
- If a task is unclear, re-read the PRD. If still unclear, ask the user.
- One task per `/dev` invocation. Don't combine tasks.
- If you discover a bug in existing code, note it but don't fix it inline — add it as a new task in TASKS.md instead.
- Playwright tests MUST take screenshots (they're used for visual debugging).
- Always use `data-testid` attributes for Playwright selectors, never CSS classes.

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
semgrep scan + npm audit ── FINDINGS ──▶ fix, re-run ──┐
      │                                                 │
    CLEAN ◀──────────────────────────────────────────────┘
      │
      ▼
Update TASKS.md + git commit
```

## Test Directory Convention

```
tests/
├── screenshots/
│   ├── task3-01-login-page.png
│   ├── task3-02-after-login.png
│   ├── task3-03-dashboard-loaded.png
│   ├── task8-01-signup-form.png
│   ├── task8-02-validation-error.png
│   └── task8-03-signup-success.png
├── unit/
│   ├── auth.test.ts
│   └── metrics.test.ts
├── integration/
│   ├── api-auth.test.ts
│   └── api-metrics.test.ts
└── e2e/
    ├── auth-flow.spec.ts
    └── dashboard.spec.ts
```
