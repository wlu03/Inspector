"use client";

import { motion, useInView } from "framer-motion";
import { useRef } from "react";

const SURFACES = [
  {
    name: "Web",
    status: "LIVE",
    statusColor: "#15C78D",
    desc: "Any framework. Vite, Next.js, CRA. Launched from dev command, exercised via screenshot + xdotool on a Linux sandbox.",
    stack: "E2B Desktop · scrot · xdotool",
    note: null,
  },
  {
    name: "Electron",
    status: "LIVE",
    statusColor: "#15C78D",
    desc: "Same Linux plane as web. Xvfb display. Window mapped via xdotool. Main + renderer logs both captured.",
    stack: "E2B Desktop · Xvfb · xdotool",
    note: null,
  },
  {
    name: "Android",
    status: "LIVE",
    statusColor: "#15C78D",
    desc: "Expo, React Native, or native APK. Runs in Redroid container. ADB screencap + input. Logcat for crash detection.",
    stack: "Redroid · adb · UiAutomator",
    note: null,
  },
  {
    name: "iOS",
    status: "LIVE",
    statusColor: "#15C78D",
    desc: "Simulator on macOS plane. Build via Xcode / expo run:ios. idb for tap + type. simctl io screenshot.",
    stack: "iOS Simulator · idb · simctl",
    note: null,
  },
];

export default function SurfaceGrid() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <section id="surfaces" style={{ borderBottom: "1px solid #2e2e2e" }}>
      <div className="max-w-6xl mx-auto px-6 py-24">
        <div className="flex items-end justify-between mb-12 flex-wrap gap-4">
          <div
            style={{
              fontFamily: "var(--font-geist-mono)",
              fontSize: 11,
              color: "#7a7a7a",
              letterSpacing: "0.15em",
              textTransform: "uppercase",
            }}
          >
            // 003 · SURFACES
          </div>
          <p
            style={{
              fontFamily: "var(--font-geist-mono)",
              fontSize: 11,
              color: "#15C78D",
              letterSpacing: "0.05em",
            }}
          >
            Playwright can&apos;t reach native. We can.
          </p>
        </div>

        <div
          ref={ref}
          className="grid grid-cols-1 sm:grid-cols-2 gap-px"
          style={{ border: "1px solid #2e2e2e" }}
        >
          {SURFACES.map((s, i) => (
            <motion.div
              key={s.name}
              initial={{ opacity: 0 }}
              animate={inView ? { opacity: 1 } : {}}
              transition={{ duration: 0.4, delay: i * 0.1 }}
              className="p-8 flex flex-col gap-5 relative"
              style={{
                background: "#1e1e1e",
                borderRight: "1px solid #2e2e2e",
                borderBottom: "1px solid #2e2e2e",
              }}
            >
              <div className="flex items-center justify-between">
                <span
                  style={{
                    fontSize: "clamp(20px, 3vw, 32px)",
                    fontWeight: 400,
                    letterSpacing: "0em",
                    color: "#f0f0f0",
                    fontFamily: "var(--font-playfair), Georgia, serif",
                  }}
                >
                  {s.name}
                </span>
                <span
                  style={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 9,
                    fontWeight: 700,
                    letterSpacing: "0.15em",
                    color: s.statusColor,
                    border: `1px solid ${s.statusColor}`,
                    padding: "2px 7px",
                  }}
                >
                  {s.status}
                </span>
              </div>

              <p style={{ fontSize: 13, color: "#9e9e9e", lineHeight: 1.6, flex: 1 }}>
                {s.desc}
              </p>

              <div
                style={{
                  fontFamily: "var(--font-geist-mono)",
                  fontSize: 10,
                  color: "#686868",
                  letterSpacing: "0.05em",
                }}
              >
                {s.stack}
              </div>

              {s.note && (
                <div
                  style={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 10,
                    color: "#15C78D",
                    letterSpacing: "0.05em",
                  }}
                >
                  ↳ {s.note}
                </div>
              )}
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
