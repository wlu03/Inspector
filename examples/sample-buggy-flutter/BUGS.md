# Planted bugs — sample-buggy-flutter

A minimal Flutter counter app with three deterministic, **visually observable** bugs.
Flutter renders its UI to a single canvas, so the iOS accessibility tree is sparse —
an agent must read the **screenshot** (vision / OmniParser grounding) rather than the
a11y tree. This fixture exists to validate the Flutter→iOS-simulator build path and the
vision grounding mode end-to-end. Machine-readable: [`bugs.json`](./bugs.json).

| ID | Severity | Difficulty | The defect (seen on the Counter screen) |
|----|----------|------------|------------------------------------------|
| BUG-01 | high   | obvious | **Plus** increments the count by **2**, not 1 |
| BUG-02 | medium | subtle  | **Reset** sets the count to **1**, not 0 |
| BUG-03 | medium | subtle  | The subscribe **switch label flips but the switch never moves** (control/state disagree) |

---

### BUG-01 — Plus increments by 2 (`_count += 2`)
- **Trigger:** from 0, tap **Plus** once → read the big count number.
- **Expected:** `1`. **Actual:** `2`.

### BUG-02 — Reset sets to 1 (`_count = 1`)
- **Trigger:** tap **Plus** a few times → tap **Reset** → read the count.
- **Expected:** `0`. **Actual:** `1`.

### BUG-03 — Subscribe switch never toggles (`onChanged: (_) => setState(() {})`)
- **Trigger:** tap the subscribe switch → compare the switch position to its label.
- **Expected:** the switch turns on and reads "Subscribed".
- **Actual:** the switch value never changes (the handler ignores the new value), so the
  control stays off regardless of taps.

---

Build: `flutter build ios --simulator --debug` (requires the Flutter SDK + CocoaPods).
Run via the iOS adapter with `INSPECTOR_FLUTTER_BIN` + `INSPECTOR_IDB_BIN` set.
