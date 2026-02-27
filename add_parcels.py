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

4. Enable the Constraints overlay and set the correct profile:
   - In the top-right area of the map, find the Constraints control. It has TWO parts:
     a. An EYE ICON to the LEFT of the "Constraints" button (the eye may have a slash through it,
        meaning it is currently hidden). Click this eye icon to enable the red overlay on the map.
        After clicking, the eye icon should appear without the slash (visible).
     b. The "Constraints" button itself — click this to open the constraints settings panel.
   - In the settings panel, find the constraint profile selector (dropdown or tabs) and switch
     it to "BESS Capacity" (it may default to "Steepness" — you MUST change it).
   - After both steps, parcels that are disqualified under BESS Capacity will be highlighted RED
     on the map. Only add parcels that are NOT covered in red.

== LAYER PROTECTION — READ THIS CAREFULLY ==
IMPORTANT: The red constraint overlay does NOT block parcel selection.
You can click on a red parcel polygon and the side panel will open normally.
The red color is only INFORMATION — it tells you to skip that parcel, not that you can't click.
Do NOT turn off the constraints layer to "see better" — the red is the whole point.

After setup, NEVER click the constraints eye icon for any reason.
Exception: if you notice the constraints eye icon has a slash through it (layer is off),
you MUST click it once to turn it back on before selecting any more parcels.
After re-enabling, continue — do not touch it again.

NEVER click the Cadastral eye icon after setup either.

== FINDING VALID PARCELS ==

Keep a list of parcel IDs you have already added. Never add the same parcel ID twice.

SCOUTING STRATEGY — do this before adding any parcel:
- Zoom OUT (click Zoom Out button 2-3 times) to see a wider area
- Scan the map screenshot for areas that are NOT red (look for green, white, or yellow parcels)
- If the ENTIRE visible area is red, you must navigate to a new location:
  1. First try panning: drag the map by dispatching mousedown → mousemove → mouseup on canvas
  2. If still all red, use Location Search to jump to the alternate coordinate: "42.709677, -78.814508"
  3. Then zoom back in (3-4 times) to see individual parcels
- Once you see non-red parcels, zoom back in to zoom ~14 before clicking them

TO PAN THE MAP by dragging (use evaluate):
  (function(){{
    const c = document.querySelector('canvas[aria-label="Map"]');
    const r = c.getBoundingClientRect();
    const cx = r.left + r.width * 0.5, cy = r.top + r.height * 0.5;
    c.dispatchEvent(new MouseEvent('mousedown', {{bubbles:true, clientX:cx, clientY:cy}}));
    c.dispatchEvent(new MouseEvent('mousemove', {{bubbles:true, clientX:cx+300, clientY:cy}}));
    c.dispatchEvent(new MouseEvent('mouseup',   {{bubbles:true, clientX:cx+300, clientY:cy}}));
  }})()
  Vary the offset (+300, -300, etc.) to pan in different directions. Wait 1s after dragging.

TO CLICK A SPECIFIC POSITION on the canvas (use evaluate):
  (function(){{
    const c = document.querySelector('canvas[aria-label="Map"]');
    const r = c.getBoundingClientRect();
    const x = r.left + r.width * 0.XX;   // replace 0.XX with fraction like 0.5, 0.7, 0.3
    const y = r.top  + r.height * 0.YY;  // replace 0.YY with fraction like 0.5, 0.4, 0.6
    c.dispatchEvent(new MouseEvent('click', {{bubbles:true, clientX:x, clientY:y}}));
  }})()
  Use different positions for each parcel attempt. Never click the same position twice in a row.

For each parcel:

5. Before clicking any parcel, look at the map screenshot carefully:
   - Is there a red overlay visible on parcels? If NOT, the constraints layer is off —
     click the constraints eye icon once to re-enable it, then wait 2 seconds.
   - Can you see any non-red parcel areas in the current view?
     If the whole screen is red, zoom out and/or pan/navigate to find non-red areas first.

6. Click the canvas at a position that looks non-red, using evaluate (see above).
   A side panel will open showing the parcel ID.
   - READ the parcel ID BEFORE proceeding.
   - If already in your added list → close panel, click a different position.
   - Check the screenshot: is the clicked parcel mostly red?
     YES → constrained, close panel, try a different position.
     NO (green/white/yellow) → valid, proceed to step 7.

7. In the side panel, click "Copy polygon to project".
   A "Save to project" popup/modal appears.

8. In the popup:
   a. Click the "Add to project" dropdown
   b. Select "+ New project" (first option in the dropdown)
   c. A "Project name" text field appears — CLEAR it and type: "BU - {{N}}"
      where {{N}} is the sequential number (BU - 1, BU - 2, ... BU - {TARGET_PARCEL_COUNT})
   d. Click the purple "Create new project" button
   e. Wait for the project to be created and the modal to close.

9. After the project is created, an object detail pane opens on the RIGHT side.
   It shows 4 type options: "PV", "BESS", "Exclude", "Other"
   Click "Other" (the 4th option, rightmost).

10. Close the left project/parcel panel by clicking the X button in its top-right corner.

11. Note the URL in the browser address bar — record it as project_url. Add parcel ID to list.

== IMPORTANT CONSTRAINTS ==
- NEVER add the same parcel ID more than once
- SKIP parcels that are completely covered in red (constrained under BESS Capacity)
- Name projects sequentially: BU - 1, BU - 2, ..., BU - {TARGET_PARCEL_COUNT}
- Add exactly {TARGET_PARCEL_COUNT} parcels total
- Do NOT click any "?" help icons or question mark buttons — they navigate away from the page
- Do NOT click any eye icons after setup is complete

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
