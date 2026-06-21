# Inspector Demo: Super Productivity (Buggy Build)

This is a fork of Super Productivity with 5 planted bugs on the **Planner page** for demoing Inspector's autonomous QA capabilities.

## Quick Start — Web

```bash
npm install
npm run serve
```

Open `http://localhost:4200`, navigate to the **Planner** page, and add a few tasks to see the bugs.

## Quick Start — Android (Capacitor)

### Prerequisites

- Android Studio: https://developer.android.com/studio
- During Android Studio setup wizard, install the default Android SDK
- After install, add to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"   # macOS default
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
```

- Restart your terminal or `source ~/.zshrc`
- In Android Studio: Tools > Device Manager > Create a device (e.g. Pixel 7, API 34)

### Build & Run

```bash
npm install
npm run build                # build the Angular app
npx cap sync android         # sync web assets into the Android project
npx cap open android         # opens the project in Android Studio
```

In Android Studio, select your emulator and hit Run (green play button). The app launches on the emulator — navigate to the Planner page.

## Planted Bugs (Planner Page Only)

All 5 bugs are in `src/app/features/planner/` and are discoverable by clicking around the planner UI:

| # | Bug | How to trigger | Expected vs Actual |
|---|-----|---------------|-------------------|
| 1 | Done toggle broken | Click the checkbox on any task | Animation plays in reverse (done shows undone animation, undone shows done) |
| 2 | Time remaining inflates | Add a time estimate to a task, then log time against it | Remaining time = estimate + spent instead of estimate - spent; working on a task makes remaining time go UP |
| 3 | Progress bar colors inverted | Have enough tasks with estimates to see the day progress bar | Overloaded days (>95%) show green; light days show red — colors are backwards |
| 4 | Drag reorder reversed | Drag a task from one position to another within the same day | Task moves in the opposite direction from where you dragged it |
| 5 | Today indicator on wrong days | Look at the day headers in the planner | The sun icon appears on every day EXCEPT today |

## Files Modified

- `src/app/features/planner/planner-task/planner-task.component.ts` (bugs 1 & 2)
- `src/app/features/planner/planner-day/planner-day.component.ts` (bugs 3 & 4)
- `src/app/features/planner/planner-day/planner-day.component.html` (bug 5)

## Planted Bugs (Other Screens)

Six additional bugs spread across non-Planner screens, mixing functional, state, visual, UX, empty-state, and accessibility categories. Each is a small, localized, individually reversible edit and is discoverable by clicking through the UI.

| # | Bug | Category | Screen | How to trigger | Expected vs Actual | File:line |
|---|-----|----------|--------|----------------|--------------------|-----------|
| 6 | "Pin to today" does nothing | Broken functionality (no-op) | Notes panel | Open a note's context menu and click **Pin to today** (or unpin a pinned note) | Expected: the note's pinned-to-today state toggles. Actual: nothing changes — the update writes the field back to its current value (missing `!`), so the action is a silent no-op | `src/app/features/note/note/note.component.ts:170` |
| 7 | Sub-task time total shows estimate, not spent | State / data | Task list / task detail | Give a parent task two or more sub-tasks, set time **estimates** and log different **spent** time on them, then view the parent's aggregated sub-task time | Expected: the sub-task summary sums each sub-task's *time spent*. Actual: it sums each sub-task's *time estimate* (wrong field) — a plausible-but-wrong positive total | `src/app/features/tasks/pipes/sub-task-total-time-spent.pipe.ts:11` |
| 8 | Tag chips overflow / overlap at narrow width | Visual / layout | Any task row with multiple tags (esp. ~375px wide) | View a task that has 2–3+ tags, or narrow the window to phone width | Expected: tag chips wrap onto multiple lines and stay inside the row. Actual: `flex-wrap: nowrap` forces them onto one line so they overflow the container and overlap adjacent content | `src/app/features/tag/tag-list/tag-list.component.scss:23` |
| 9 | Action button looks/behaves disabled | UX (disabled-looking button) | Settings → Automatic Backups (any config section with an action button) | Open the config section and look at its action button (e.g. *Create backup*); try to click it | Expected: the button is enabled until its action is running. Actual: the `[disabled]` binding is inverted, so the button is greyed-out/disabled in its normal idle state and only enables while pending (which it can't reach) | `src/app/features/config/config-section/config-section.component.html:54` |
| 10 | Empty-state message shown backwards | Empty / error state | Notes panel | Open the Notes panel with some notes present, then with none | Expected: the "No notes" message appears only when the list is empty. Actual: the `@if` condition is inverted (`!== 0`), so the message shows whenever notes **exist** and is hidden when the list is actually empty | `src/app/features/note/notes/notes.component.html:46` |
| 11 | Bottom-panel close button has no accessible name | Accessibility | Mobile bottom panel (Notes / task panel) | Open the bottom panel and inspect its close (×) icon button with a screen reader / a11y tooling | Expected: the icon-only button exposes an `aria-label` ("Close"). Actual: the `aria-label` was removed, so the control announces nothing | `src/app/features/bottom-panel/bottom-panel-container.component.html:12` |
