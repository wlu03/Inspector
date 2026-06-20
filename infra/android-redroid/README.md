# Android plane — Redroid

Android-in-a-container. Boots the Android userspace on the host kernel (no nested
virtualization), driven entirely over `adb`.

## Host prerequisites (the fragile part)
Redroid needs Android kernel modules **loaded on the Linux host** — run
[`setup-host.sh`](setup-host.sh) as root. This rules out hosts where you can't
load modules: **managed/serverless containers, macOS Docker Desktop, and WSL2.**
Use a Linux host you control (bare metal, AWS Graviton, Hetzner). Prefer **ARM64**
to avoid ARM-on-x86 translation.

## Run
```bash
sudo ./setup-host.sh          # load binder + ashmem modules (once)
docker compose up -d          # start the Redroid container
adb connect localhost:5555
adb devices                   # expect: localhost:5555  device
```

## Drive it
```bash
adb install -r -t app.apk
adb shell am start -n com.example.app/.MainActivity
adb exec-out screencap -p > screen.png
adb shell input tap 540 1200
adb logcat -b crash -d
```

## Code
- `inspector/planes/android.py` (`RedroidRuntime`)
- `inspector/adapters/android.py` (`AndroidAdapter`) — task #9
- Sample app to test against: [`../../examples/sample-buggy-android/`](../../examples/sample-buggy-android/)
