---
name: eval
description: Run the LangSmith eval set against the current prompts/model config and report whether the average judge score held or dropped versus the last baseline. Use when the user wants to check eval score, validate a prompt or model change, gate a release, or says "/eval", "run the eval set", "did this regress quality".
---

# `/eval` — LangSmith Eval Gate

You are validating a prompt or model change against `ai_llm`'s quality bar. `AGENTS.md` requires this before any prompt or model change ships: the average judge score must not drop versus baseline when `EVAL_ON_RELEASE=true`. This skill is the standalone entry point for that check — `ai_llm/dev` Step 6.5 calls into the same gate inline when a task touches prompts.

**This is the one place in the project that is allowed to call real LLM providers.** Unit tests mock NVIDIA/Gemini; the eval set exists specifically to score real output quality, so run it against the real primary/fallback chain, not a mock.

## Process

### Step 1: Confirm There's Something to Evaluate

Check `.env` for `EVAL_DATASET_NAME`. If it's unset or the dataset doesn't exist in LangSmith, stop and tell the user — don't fabricate a score or silently skip the gate.

Check whether an eval runner already exists in the repo (e.g. `app/eval.py` or a `langsmith.evaluate(...)` entry point). If none exists yet, tell the user this skill has nothing to run yet and offer to add "build the eval runner" as a task in the current sprint's `TASKS.md` — do not improvise a one-off scoring script as a substitute for a real task.

### Step 2: Identify What Changed

- `git diff` (or ask the user) for changes under `app/prompts/*.md`, `app/nodes/write.py`, `app/nodes/verify.py`, or model/provider config (`LLM_PROVIDER`, `LLM_FALLBACK_PROVIDER`, model names).
- If nothing in that set changed, tell the user the eval gate doesn't apply and ask if they want to run it anyway as a baseline check.

### Step 3: Find the Baseline

Look for the last recorded score:
- The most recent `sprints/vN/WALKTHROUGH.md` "Eval Results" section, if present.
- Otherwise a tracked baseline file (e.g. `eval/baseline.json`), if the project has one.

If no baseline exists yet, this run **becomes** the baseline — say so explicitly rather than reporting a pass/fail against nothing.

### Step 4: Run the Eval Set

```bash
python -m app.eval --dataset "$EVAL_DATASET_NAME"
```

(Adjust to whatever the repo's actual eval entry point is — see Step 1. Run against the real NVIDIA→Gemini fallback chain, same as production, so the score reflects real behavior.)

Respect the free-tier rate limits while it runs (NVIDIA ~40 RPM, Gemini ~10 RPM) — this is a real, if free, API workload, not a mock; don't parallelize past what the provider chain can absorb.

### Step 5: Compare and Gate

- Compute the new average judge score (`PASS_SCORE=7` is the per-section bar; the eval gate cares about the dataset-wide average, not any single section).
- Compare to baseline.
- If the score **held or improved**: PASS. Update the baseline record with the new score.
- If the score **dropped** and `EVAL_ON_RELEASE=true`: BLOCKED. Do not update the baseline. State clearly that the prompt/model change should not ship as-is.
- If the score dropped and `EVAL_ON_RELEASE=false`: WARN — report the drop but don't block, since the gate is off.

### Step 6: Report

Give the user:
- Dataset name, sample count.
- Baseline score → new score (delta).
- PASS / BLOCKED / WARN / "new baseline" verdict.
- If invoked from within `/dev` Step 6.5 for a specific task, hand the verdict back so that task's completion isn't marked until this passes.

## Rules

- NEVER report a score without actually running the eval set. If you can't run it (no dataset, no runner, rate-limited), say so — don't estimate or guess a plausible-looking number.
- NEVER update the baseline on a BLOCKED result — the recorded baseline should only move forward on a genuine pass.
- This is the one workflow in the project allowed to hit real NVIDIA/Gemini endpoints outside of an actual book run — every other test path mocks them.
- If both NVIDIA and Gemini fail during the eval run itself (not a quality drop, an outage), report that distinctly from a quality regression — don't conflate "couldn't run" with "ran and scored worse."

## Example Output

```
Eval: prompt change to app/prompts/write_notes.md (this task: tighten fact-grounding instructions)

Dataset: video2book-eval-v1 (42 examples)
Baseline (sprints/v3/WALKTHROUGH.md): 8.1 avg judge score
New run:                              8.4 avg judge score
Delta: +0.3

Verdict: PASS — baseline updated to 8.4.
```

```
Eval: model config change (LLM_PROVIDER nemotron-3-super-120b-a12b → nemotron-3-super-70b)

Dataset: video2book-eval-v1 (42 examples)
Baseline: 8.1 avg judge score
New run:  7.2 avg judge score
Delta: -0.9

Verdict: BLOCKED (EVAL_ON_RELEASE=true) — score dropped below baseline.
Baseline left unchanged at 8.1. Do not ship this model swap as-is.
```
