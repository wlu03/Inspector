# sample-buggy-android

M0 fixture for the **Android** surface (Redroid, Linux plane). An Expo/React-Native
app with the same bug: **Save** throws a `TypeError` before showing the "Saved"
confirmation.

LoopBack catches it via **logcat** (crash/error) and **verify-after-act**.

Build an APK and install into Redroid:
```bash
npx expo prebuild -p android
cd android && ./gradlew assembleDebug
adb install -r -t app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.loopback.samplebuggyandroid/.MainActivity
```
Driven by `loopback/adapters/android.py` (task #9). See
[`../../infra/android-redroid/`](../../infra/android-redroid/).
