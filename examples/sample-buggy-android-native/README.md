# sample-buggy-android-native

A minimal **native** Android app (Java, gradle) that **builds cleanly** — the M2
fixture for the Android adapter. (The Expo sample exists too, but its RN 0.76 /
Kotlin native build is fragile; this one compiles in seconds.)

## The planted bug
`MainActivity` — the **Save** button is supposed to show a green "Saved" toast, but
it throws a `NullPointerException` first, so the UI never updates. It emits a
distinct log line before crashing, observable over `adb logcat`:

```
E Inspector: query not invalidated after save
```

Inspector catches it via the **logcat tap** (the `Log.e` signature + the uncaught
exception) and **verify-after-act** (the toast text never changes).

## Build / run by hand
```bash
export ANDROID_HOME=~/Library/Android/sdk      # or your SDK path
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
./gradlew assembleDebug                          # -> app/build/outputs/apk/debug/app-debug.apk
adb install -r -t app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.inspector.sample/.MainActivity
```

Inspector does all of this automatically via `AndroidBuilder` + `AndroidAdapter`
(`surface="android"`), driving a local emulator.
