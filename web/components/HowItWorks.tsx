"use client";

import { motion, useInView } from "framer-motion";
import { useRef } from "react";

const STEPS = [
  {
    id: "LAUNCH",
    desc: "Inspector detects your framework and runs your dev command — npm run dev, expo start, electron .",
    mono: "$ npm run dev",
  },
  {
    id: "PERCEIVE",
    desc: "Screenshot taken. OmniParser detects elements and produces a Set-of-Mark overlay: numbered boxes over every clickable target.",
    mono: "frame_001.png → 12 elements",
  },
  {
    id: "GROUND",
    desc: "The annotated screenshot is returned to your coding agent. The agent picks element #N — no raw coordinate guessing.",
    mono: "host agent → #4 [Login]",
  },
  {
    id: "ACT",
    desc: "Inspector maps the element ID to coordinates and dispatches the input. Works identically on web, Electron, Android, iOS.",
    mono: "tap(614, 382) → verify",
  },
  {
    id: "DETECT",
    desc: "Crash? Console error? Visual breakage? Layout anomaly? Every deterministic signal captured and structured.",
    mono: "NullPointerException ✗",
  },
  {
    id: "FIX",
    desc: "Structured findings returned to the agent. It repairs the code and re-verifies. You step in only at the PR gate.",
    mono: "agent patches → re-run",
  },
];

export default function HowItWorks() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <section id="how-it-works" style={{ borderBottom: "1px solid #2e2e2e" }}>
      <div className="max-w-6xl mx-auto px-6 py-24">
        <div
          className="mb-12"
          style={{
            fontFamily: "var(--font-geist-mono)",
            fontSize: 11,
            color: "#909090",
            letterSpacing: "0.15em",
            textTransform: "uppercase",
          }}
        >
          // 002 · HOW IT WORKS
        </div>

        <div ref={ref} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px" style={{ border: "1px solid #2e2e2e" }}>
          {STEPS.map((step, i) => (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, y: 16 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.4, delay: i * 0.08, ease: [0.22, 1, 0.36, 1] }}
              className="flex flex-col gap-4 p-6"
              style={{ background: "#1e1e1e", borderRight: "1px solid #2e2e2e", borderBottom: "1px solid #2e2e2e" }}
            >
              <div className="flex items-center gap-3">
                <span
                  style={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 9,
                    color: "#595959",
                    letterSpacing: "0.08em",
                    border: "1px solid #3a3a3a",
                    padding: "1px 6px",
                  }}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  style={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 16,
                    fontWeight: 700,
                    letterSpacing: "0.12em",
                    color: "#15C78D",
                  }}
                >
                  {step.id}
                </span>
              </div>

              <p style={{ fontSize: 13, color: "#9e9e9e", lineHeight: 1.6, flex: 1 }}>
                {step.desc}
              </p>

              <div
                style={{
                  fontFamily: "var(--font-geist-mono)",
                  fontSize: 11,
                  color: "#686868",
                  background: "#262626",
                  border: "1px solid #2e2e2e",
                  padding: "6px 10px",
                }}
              >
                {step.mono}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
