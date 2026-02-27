"""
Phase 1: Parcel Discovery & Project Creation via browser-use.

For each visible non-red parcel near COORDINATE_START:
  1. Enable Cadastral (parcels) + Constraints layers on the portfolio map
  2. Click a non-red parcel → side panel → "Copy polygon to project"
  3. "Save to project" popup → "+ New project" → name "BU - N" → Create
  4. Object detail pane → click "Other"
  5. Close project panel (X)
  6. Return list of created projects {name, url} for Phase 3

Logs every UI selector to output/screenshots/add_parcels_playwright_log.md
for a future Playwright migration.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

import config
from auth import playwright_login


TARGET_PARCEL_COUNT = 6
LOG_PATH = str(Path(config.SCREENSHOT_DIR) / "add_parcels_playwright_log.md")
OUTPUT_PATH = "output/created_projects.json"


async def run_add_parcels(storage_state: dict) -> list[dict]:
    from browser_use import Agent, Browser
    from browser_use import ChatBrowserUse
    from pydantic import BaseModel

    class CreatedProject(BaseModel):
        name: str
        parcel_id: str | None = None
        project_url: str | None = None

    class AddParcelsResult(BaseModel):
        projects: list[CreatedProject] = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(storage_state, tmp)
        state_path = tmp.name

    browser = Browser(storage_state=state_path, headless=False, keep_alive=False)

    coord = config.COORDINATE_START.strip().strip('"')

    task = f"""
You are automating the Glint Solar web app to add parcels to new projects.

== SETUP ==
1. Navigate to: {config.PORTFOLIO_URL}
   Wait for the map to load fully (networkidle).

2. Find the map and navigate to coordinates: {coord}
   - Look for a search box or coordinate input on the map (or use browser navigation)
   - If there is a search bar, type the coordinates to center the map there
   - Zoom to a level where you can see 5-8 individual land parcels (zoom ~14-15)

3. Enable the Cadastral / Parcels layer:
   - Click the Layers icon/tab in the top-right area of the map
   - Find the "Cadastral" folder in the layer list
   - Click its eye icon to make parcels visible on the map
   - You should now see parcel boundaries drawn on the map

4. Enable the Constraints overlay (to see which parcels are disqualified):
   - In the same layers panel, look for a "Constraints" section or toggle
   - Enable it — disqualified parcels will be highlighted in RED

== ADDING PARCELS (repeat {TARGET_PARCEL_COUNT} times) ==
For each parcel that is NOT completely covered in red:

5. Click the parcel polygon on the map.
   A side panel should open on the left or right showing parcel details.

6. In the side panel, find and click "Copy polygon to project"
   (it may also be labelled "Add to project" or similar).
   A "Save to project" popup/modal appears.

7. In the popup:
   a. Click the "Add to project" dropdown
   b. Select "+ New project" (first option in the dropdown)
   c. A "Project name" text field appears — it may be pre-filled with a city name.
      CLEAR the field and type the project name: "BU - {{N}}"
      where {{N}} is the sequential number (BU - 1, BU - 2, ... BU - {TARGET_PARCEL_COUNT})
   d. Click the purple "Create new project" button
   e. Wait for the project to be created and the modal to close.

8. After the project is created, an object detail pane opens on the RIGHT side.
   It shows 4 type options: "PV", "BESS", "Exclude", "Other"
   Click "Other" (the 4th option, rightmost).

9. Close the left project/parcel panel by clicking the X button in its top-right corner.

10. Note the URL in the browser address bar — it should contain the new project ID.
    Record it as the project_url for this entry.

11. Click somewhere on the map to deselect, then repeat steps 5-10 for the next
    non-red parcel. Skip any parcel that is entirely covered in red.

== IMPORTANT CONSTRAINTS ==
- SKIP parcels that are completely covered in red (constrained/disqualified)
- Only add parcels that have clear (non-red) land area
- Name projects sequentially: BU - 1, BU - 2, ..., BU - {TARGET_PARCEL_COUNT}
- Add exactly {TARGET_PARCEL_COUNT} parcels total
- After each parcel is added, close the project panel before moving to the next

== PLAYWRIGHT DOCUMENTATION ==
As you work, write a file at "{LOG_PATH}" documenting EVERY UI element
you interact with. For each action record:
  ### Step N: <description>
  - **Located by**: <method — role, text, CSS, XPath>
  - **Selector**: `<exact selector>`
  - **Action**: <click|type|wait|read>
  - **Notes**: <timing, fallbacks, observations>

This log is critical — it will be used to rewrite this flow in Playwright.

== OUTPUT ==
Return a list of projects with:
  - name: "BU - N"
  - parcel_id: the parcel ID shown in the side panel (if visible)
  - project_url: the full URL from the browser address bar after project creation
"""

    agent = Agent(
        task=task,
        llm=ChatBrowserUse(),
        browser=browser,
        output_model_schema=AddParcelsResult,
    )

    try:
        history = await agent.run(max_steps=120)
        Path(state_path).unlink(missing_ok=True)
        result = history.get_structured_output(AddParcelsResult)
        if result is None:
            result = AddParcelsResult()
        projects = [p.model_dump() for p in result.projects]
        print(f"\n[add_parcels] Created {len(projects)} project(s):")
        for p in projects:
            print(f"  {p['name']}: parcel={p['parcel_id']}  url={p['project_url']}")
        return projects
    except Exception as exc:
        Path(state_path).unlink(missing_ok=True)
        print(f"[add_parcels] agent error — {exc}")
        return []


def save_projects(projects: list[dict]) -> None:
    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_PATH).write_text(json.dumps(projects, indent=2))
    print(f"[add_parcels] Saved project list to {OUTPUT_PATH}")

    # Also emit the PROJECT_URL_N env lines for easy copy-paste into .env
    print("\n[add_parcels] Add these to .env:")
    for i, p in enumerate(projects, 1):
        if p.get("project_url"):
            print(f'  PROJECT_URL_{i}={p["project_url"]}')


async def main():
    print("=== Phase 1: Add Parcels ===")
    print(f"Portfolio: {config.PORTFOLIO_URL}")
    print(f"Coordinate: {config.COORDINATE_START}")
    print(f"Target parcels: {TARGET_PARCEL_COUNT}")

    Path(config.SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)

    _, storage_state = await playwright_login(config.EMAIL, config.PASSWORD)
    projects = await run_add_parcels(storage_state)

    if projects:
        save_projects(projects)
    else:
        print("[add_parcels] No projects created — check the playwright log for details.")


if __name__ == "__main__":
    asyncio.run(main())
