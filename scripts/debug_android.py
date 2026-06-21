#!/usr/bin/env python3
"""Debug the Android build pipeline step-by-step inside E2B."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inspector.config import Config
from inspector.planes.linux import LinuxPlane

config = Config.from_env()
plane = LinuxPlane(config)

def run(cmd, timeout=120):
    print(f"\n$ {cmd}")
    res = plane.run_sync(cmd, timeout=timeout)
    out = res.stdout if res and getattr(res, "stdout", "") else "(no output)"
    print(out[:2000])
    return res

print("=== Booting E2B sandbox ===")
plane.start()

print("\n=== Uploading sample app ===")
repo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "examples", "sample-buggy-android")
plane.upload(repo, "/home/user/app")

run("ls -la /home/user/app/")
run("cat /home/user/app/package.json")

print("\n=== Checking Docker ===")
run("which docker && docker --version || echo 'no docker'")
run("dockerd --version 2>/dev/null || echo 'no dockerd'")

print("\n=== Checking adb ===")
run("which adb || echo 'no adb'")

print("\n=== Checking Node ===")
run("which node && node --version || echo 'no node'")

NODE_V = "v22.11.0"
NODE_DIR = "/home/user/node"
NP = f"export PATH={NODE_DIR}/bin:$PATH"

print("\n=== Installing Node ===")
run(f"test -x {NODE_DIR}/bin/node || (cd /home/user && curl -fsSL https://nodejs.org/dist/{NODE_V}/node-{NODE_V}-linux-x64.tar.xz -o node.tar.xz && tar -xJf node.tar.xz && mv node-{NODE_V}-linux-x64 {NODE_DIR})", timeout=300)
run(f"{NP} && node --version")

print("\n=== npm install ===")
run(f"{NP} && cd /home/user/app && npm install 2>&1 | tail -20", timeout=300)

print("\n=== Checking Expo ===")
run(f"{NP} && cd /home/user/app && npx expo --version 2>&1 | tail -5")

print("\n=== Expo prebuild ===")
run(f"{NP} && cd /home/user/app && npx expo prebuild -p android --no-install 2>&1 | tail -30", timeout=300)

print("\n=== Check android dir ===")
run("ls -la /home/user/app/android/ 2>/dev/null || echo 'no android dir'")

print("\n=== Check for gradlew ===")
run("ls -la /home/user/app/android/gradlew 2>/dev/null || echo 'no gradlew'")

print("\n=== Installing JDK ===")
run("sudo apt-get update -qq && sudo apt-get install -y -qq openjdk-17-jdk-headless 2>&1 | tail -5", timeout=180)
run("javac -version")

SDK = "/home/user/android-sdk"
AENV = f"export ANDROID_HOME={SDK} && export ANDROID_SDK_ROOT={SDK}"

print("\n=== Setting up Android SDK licenses ===")
run(f"mkdir -p {SDK}/licenses")
run(f"echo -e '\\n24333f8a63b6825ea9c5514f83c2829b004d1fee' > {SDK}/licenses/android-sdk-license && "
    f"echo -e '\\n84831b9409646a918e30573bab4c9c91346d8abd' > {SDK}/licenses/android-sdk-preview-license && "
    f"echo -e '\\nd56f5187479451eabf01fb78af6dfcb131a6481e\\n24333f8a63b6825ea9c5514f83c2829b004d1fee' >> {SDK}/licenses/android-sdk-license && "
    f"echo -e '\\ne9acab5b5fbb560a72797e95dcdf135e1b3bf903' > {SDK}/licenses/android-sdk-arm-dbt-license")

print("\n=== Writing local.properties ===")
run(f"echo 'sdk.dir={SDK}' > /home/user/app/android/local.properties && cat /home/user/app/android/local.properties")

print("\n=== Gradle build ===")
run(f"{NP} && {AENV} && cd /home/user/app/android && chmod +x gradlew && ./gradlew assembleDebug 2>&1 | tail -40", timeout=600)

print("\n=== Find APK ===")
run("find /home/user/app -name '*.apk' 2>/dev/null")

print("\n=== Tearing down ===")
plane.stop()
print("Done.")
