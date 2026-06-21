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
