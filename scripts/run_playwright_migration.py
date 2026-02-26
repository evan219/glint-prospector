"""
Playwright Migration Orchestrator
==================================
Runs the Drafter → Reviewer → Tester pipeline for each task defined in CLAUDE.md,
respecting task dependencies and parallelising independent tasks.

Usage:
    python scripts/run_playwright_migration.py [--dry-run] [--task TASK-P1]

Each task goes through:
  1. Drafter  — Claude Code agent that writes the implementation
  2. Reviewer — Claude Code agent that reviews for bugs/risks (BUGS/RISKS/VERDICT)
  3. Tester   — runs `python -m pytest tests/ -v` and checks pass count

A task only starts when all its DEPENDS_ON tasks are DONE.
Independent tasks (no deps, or all deps done) run in parallel.

Requires: ANTHROPIC_API_KEY set in environment.
"""

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).parent.parent


# ── Task definitions ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class Task:
    id: str
    title: str
    description: str          # passed to Drafter agent
    files_to_create: list[str]
    files_to_modify: list[str]
    test_selector: str        # pytest -k selector to verify
    depends_on: list[str] = dataclasses.field(default_factory=list)
    status: str = "pending"   # pending | drafting | reviewing | testing | done | failed


TASKS: list[Task] = [
    Task(
        id="TASK-P1",
        title="Playwright right-click + context menu",
        description="""
Create `playwright_flow.py` in the repo root and implement:

    async def open_buildable_area_panel(page, parcel_id: str) -> None

This function must:
1. Wait for the Objects sidebar to finish loading
   (wait for `page.locator('text=Objects')` to be visible)
2. Locate the parcel row using `page.locator(f'p:has-text("Parcel {parcel_id}")')`
3. Dispatch a contextmenu event on the parcel row
   (use `locator.dispatch_event('contextmenu', {'bubbles': True, 'cancelable': True})`)
4. Wait for the context menu to appear
   (wait for `page.get_by_role("button", name="Buildable Area")` to be visible, 5s timeout)
5. Click "Buildable Area"
6. Wait for the buildable area settings panel
   (wait for `page.get_by_role("button", name="Run Buildable Area")` to be visible, 10s timeout)

Also create `tests/test_playwright_flow.py` with `test_open_buildable_area_panel` that
mocks a Playwright page and verifies the sequence of calls.

Follow the existing code style in `installed_capacity.py` and `buildable_area.py`.
""",
        files_to_create=["playwright_flow.py", "tests/test_playwright_flow.py"],
        files_to_modify=[],
        test_selector="test_open_buildable_area_panel",
        depends_on=[],
    ),
    Task(
        id="TASK-P2",
        title="Buildable area run + acres extraction",
        description="""
In `playwright_flow.py`, implement:

    async def run_buildable_area_and_copy(page) -> float | None

This function must:
1. Click `page.get_by_role("button", name="Run Buildable Area")`
2. Poll every 2 seconds (up to 120s) for `page.get_by_role("button", name="Copy to project")`
   to become visible — the floating panel appears when calculation finishes
3. Parse the acres value from the floating panel text: look for a pattern like
   "N objects selected" followed by "X.XX ac" — use page.locator with text matching
   or extract via page.evaluate scanning for leaf text matching digits + ".XX ac"
4. Click "Copy to project"
5. Wait for the floating panel to disappear (the button is no longer visible)
6. Return the acres as a float, or None if parsing fails

Add `test_run_buildable_area_and_copy` to `tests/test_playwright_flow.py`.
""",
        files_to_create=[],
        files_to_modify=["playwright_flow.py", "tests/test_playwright_flow.py"],
        test_selector="test_run_buildable_area_and_copy",
        depends_on=[],
    ),
    Task(
        id="TASK-P3",
        title="New Analysis kW read",
        description="""
In `playwright_flow.py`, implement:

    async def click_new_analysis_and_read_kw(page) -> float | None

This function must:
1. Click `page.get_by_role("button", name="New analysis")`
2. Wait up to 60s for a non-zero MWp/kWp value to appear anywhere in the page
   using `page.wait_for_function` scanning leaf elements for the pattern
   /[1-9][\\d,.]*\\s*[MmKk][Ww][Pp]?/
3. Call `_read_kw_from_page(page)` from `installed_capacity.py` to extract the value
4. Return float kW or None

Import `_read_kw_from_page` from `installed_capacity`. Do not duplicate the parsing logic.

Add `test_click_new_analysis_and_read_kw` to `tests/test_playwright_flow.py`.
""",
        files_to_create=[],
        files_to_modify=["playwright_flow.py", "tests/test_playwright_flow.py"],
        test_selector="test_click_new_analysis_and_read_kw",
        depends_on=[],
    ),
    Task(
        id="TASK-P4",
        title="Fix _verify_and_screenshot",
        description="""
In `installed_capacity.py`, fix `_verify_and_screenshot` so it no longer relies on
`config.SEL_NEW_ANALYSIS` (a brittle CSS hash selector that breaks between sessions).

Replace the "Open New Analysis panel" block with a call to
`click_new_analysis_and_read_kw(page)` from `playwright_flow.py` (TASK-P3).

The function should:
1. Navigate to `project_url or config.PROJECT_URL`
2. Call `await click_new_analysis_and_read_kw(page)` — this handles the button click
   and waits for the kW result
3. Take the screenshot AFTER the kW value is non-zero
4. Return (kw, screenshot_path)

Remove the now-dead `config.SEL_NEW_ANALYSIS` fallback + `wait_for_function` block
from `_verify_and_screenshot` (they are replaced by the call above).

Update the corresponding unit tests in `tests/test_installed_capacity.py` if any
existing tests mock the internal flow.
""",
        files_to_create=[],
        files_to_modify=["installed_capacity.py", "tests/test_installed_capacity.py"],
        test_selector="test_verify_and_screenshot",
        depends_on=["TASK-P3"],
    ),
    Task(
        id="TASK-P5",
        title="Replace browser-use with full Playwright in _run_agent_for_parcel",
        description="""
In `installed_capacity.py`, replace `_run_agent_for_parcel` with a pure Playwright
implementation. Remove the browser-use dependency entirely from this function.

New implementation:

    async def _run_playwright_for_parcel(
        storage_state: dict,
        parcel_id: str,
        project_url: str,
        screenshot_dir: Path,
    ) -> _ParcelResult:

Steps:
1. Launch Playwright browser using `storage_state` dict directly
   (`await browser.new_context(storage_state=storage_state)`)
2. Navigate to `project_url`
3. Call `await open_buildable_area_panel(page, parcel_id)` (TASK-P1)
4. Call `acres = await run_buildable_area_and_copy(page)` (TASK-P2)
5. Call `kw = await click_new_analysis_and_read_kw(page)` (TASK-P3)
6. Take a screenshot to `screenshot_dir / f"{parcel_id}_result.png"`
7. Return `_ParcelResult(installed_capacity_kw=kw, buildable_area_acres=acres)`

Also rename `_run_agent_for_parcel` to `_run_agent_for_parcel_legacy` (keep for
fallback testing), and update `get_all_installed_capacities` to call the new
`_run_playwright_for_parcel`.

Remove `from browser_use import Agent, Browser, ChatBrowserUse` from the function body.
Remove the `tempfile` storage_state hack.

Update CLAUDE.md to reflect that `BROWSER_USE_API_KEY` is no longer required.

Run `python -m pytest tests/ -v` — all tests must pass.
Run `python main.py` — all 3 parcels must complete with `kw_verified` not None.
""",
        files_to_create=[],
        files_to_modify=["installed_capacity.py", "CLAUDE.md"],
        test_selector="",  # full suite + integration
        depends_on=["TASK-P1", "TASK-P2", "TASK-P3", "TASK-P4"],
    ),
]

TASK_BY_ID = {t.id: t for t in TASKS}


# ── Agent prompts ─────────────────────────────────────────────────────────────


def drafter_prompt(task: Task) -> str:
    files_context = []
    for f in task.files_to_modify + task.files_to_create:
        path = REPO_ROOT / f
        if path.exists():
            content = path.read_text()
            files_context.append(f"### {f}\n```python\n{content}\n```")
    context_str = "\n\n".join(files_context) if files_context else "(new files — none to read)"

    return f"""You are a Drafter agent implementing {task.id}: {task.title}.

## Task description
{task.description}

## Current file contents
{context_str}

## Instructions
Implement the changes described above.  Follow these rules:
- Match the existing code style exactly
- Do not add comments unless logic is non-obvious
- Do not add features beyond what is asked
- After writing, output the complete new content of EACH modified/created file
  in a fenced code block labelled with the filename, e.g.:

### playwright_flow.py
```python
<full file content>
```

Output ALL changed files. Do not truncate."""


def reviewer_prompt(task: Task, draft_output: str) -> str:
    return f"""You are a Reviewer agent checking {task.id}: {task.title}.

## Draft implementation
{draft_output}

## Review checklist
- BUGS: correctness errors, wrong API usage, missing awaits, off-by-one
- RISKS: race conditions, timeouts too short/long, fragile selectors
- IMPROVEMENTS: optional but worth noting
- VERDICT: LGTM or REQUEST_CHANGES

If REQUEST_CHANGES, list must-fix items clearly.
Output ONLY the structured report."""


def tester_prompt(test_selector: str) -> str:
    cmd = f"python -m pytest tests/ -v -k '{test_selector}'" if test_selector else "python -m pytest tests/ -v"
    return f"""Run the following command and report the result:

    {cmd}

Output the full pytest output and conclude with:
- PASSED: N tests passed
- FAILED: list failing tests
- VERDICT: PASS or FAIL"""


# ── Claude client ─────────────────────────────────────────────────────────────


_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def call_claude(prompt: str, model: str = "claude-sonnet-4-6") -> str:
    response = _client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def run_tests(selector: str) -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
    cmd = ["python", "-m", "pytest", "tests/", "-v"]
    if selector:
        cmd += ["-k", selector]
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    passed = result.returncode == 0
    return passed, output


def apply_draft(draft_output: str) -> None:
    """Extract fenced code blocks from draft and write them to disk."""
    import re
    pattern = re.compile(r"### ([\w./]+)\n```(?:python)?\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(draft_output):
        filename = m.group(1).strip()
        content = m.group(2)
        target = REPO_ROOT / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        print(f"  [apply] wrote {filename} ({len(content)} chars)")


# ── Pipeline ──────────────────────────────────────────────────────────────────


async def run_task(task: Task, dry_run: bool = False) -> bool:
    """Run Drafter → Reviewer → Tester for one task. Returns True on success."""
    print(f"\n{'='*60}")
    print(f"Starting {task.id}: {task.title}")
    print(f"{'='*60}")

    # ── Drafter ───────────────────────────────────────────────────────────────
    task.status = "drafting"
    print(f"\n[{task.id}] Drafter...")
    if dry_run:
        print("  [DRY RUN] skipping")
        draft_output = "(dry run)"
    else:
        draft_output = call_claude(drafter_prompt(task))
        print(f"  Draft length: {len(draft_output)} chars")
        apply_draft(draft_output)

    # ── Reviewer ──────────────────────────────────────────────────────────────
    task.status = "reviewing"
    print(f"\n[{task.id}] Reviewer...")
    if dry_run:
        verdict = "LGTM"
        review_output = "(dry run) LGTM"
    else:
        review_output = call_claude(reviewer_prompt(task, draft_output))
        print(review_output[:800])
        verdict = "REQUEST_CHANGES" if "REQUEST_CHANGES" in review_output else "LGTM"

    if verdict == "REQUEST_CHANGES":
        print(f"\n[{task.id}] REVIEWER REQUESTED CHANGES — task failed")
        task.status = "failed"
        return False

    # ── Tester ────────────────────────────────────────────────────────────────
    task.status = "testing"
    print(f"\n[{task.id}] Running tests ({task.test_selector or 'full suite'})...")
    if dry_run:
        passed, test_output = True, "(dry run)"
    else:
        passed, test_output = run_tests(task.test_selector)
        print(test_output[-1000:])

    if not passed:
        print(f"\n[{task.id}] TESTS FAILED — task failed")
        task.status = "failed"
        return False

    task.status = "done"
    print(f"\n[{task.id}] ✓ DONE")
    return True


async def orchestrate(target_tasks: list[str] | None = None, dry_run: bool = False) -> None:
    """Run all tasks respecting dependencies, parallelising where possible."""
    tasks = TASKS if not target_tasks else [t for t in TASKS if t.id in target_tasks]

    pending = list(tasks)
    running: dict[str, asyncio.Task] = {}

    while pending or running:
        # Start all tasks whose dependencies are satisfied
        newly_started = []
        for task in list(pending):
            deps_done = all(
                TASK_BY_ID[dep].status == "done" for dep in task.depends_on
            )
            deps_failed = any(
                TASK_BY_ID[dep].status == "failed" for dep in task.depends_on
            )
            if deps_failed:
                print(f"\n[{task.id}] SKIPPED — dependency failed")
                task.status = "failed"
                pending.remove(task)
            elif deps_done and task.id not in running:
                print(f"\n[{task.id}] Queuing (deps satisfied)")
                running[task.id] = asyncio.create_task(run_task(task, dry_run))
                newly_started.append(task)
                pending.remove(task)

        if not running:
            break

        # Wait for any running task to finish
        done_ids, _ = await asyncio.wait(
            list(running.values()), return_when=asyncio.FIRST_COMPLETED
        )
        for coro in done_ids:
            finished_id = next(k for k, v in running.items() if v is coro)
            del running[finished_id]

    failed = [t for t in TASKS if t.status == "failed"]
    done = [t for t in TASKS if t.status == "done"]
    print(f"\n{'='*60}")
    print(f"DONE: {[t.id for t in done]}")
    print(f"FAILED: {[t.id for t in failed]}")


# ── CLI ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Playwright migration orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Skip actual Claude calls")
    parser.add_argument("--task", nargs="+", help="Run only specific tasks (e.g. TASK-P1)")
    parser.add_argument("--list", action="store_true", help="List tasks and exit")
    args = parser.parse_args()

    if args.list:
        for t in TASKS:
            deps = f" (depends: {', '.join(t.depends_on)})" if t.depends_on else ""
            print(f"  {t.id}: {t.title}{deps}")
        sys.exit(0)

    asyncio.run(orchestrate(target_tasks=args.task, dry_run=args.dry_run))
