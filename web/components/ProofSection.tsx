"use client";

import { motion, useInView } from "framer-motion";
import { useRef } from "react";

const FINDING = {
  type: "CRASH",
  summary: "Login flow fails — NullPointerException on submit",
  surface: "Android · API 34",
  confidence: "HIGH",
  reproduced: "3 / 3 runs",
  frame: "frame_012.png",
  action: 'CLICK element #4 [Login button]',
  logLine: "java.lang.NullPointerException: userRepository is null",
  expected: "Navigate to /dashboard",
  actual: "App crash — exception thrown in AuthViewModel.kt:47",
};

export default function ProofSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <section id="proof" style={{ borderBottom: "1px solid #2e2e2e" }}>
      <div className="max-w-6xl mx-auto px-6 py-24">
        <div
          className="mb-4"
          style={{
            fontFamily: "var(--font-geist-mono)",
            fontSize: 11,
            color: "#909090",
            letterSpacing: "0.15em",
            textTransform: "uppercase",
          }}
        >
          // 004 · STRUCTURED FINDINGS
        </div>
        <h2
          style={{
            fontSize: "clamp(20px, 3vw, 40px)",
            fontWeight: 400,
            letterSpacing: "0em",
            color: "#f0f0f0",
            marginBottom: 12,
            fontFamily: "var(--font-playfair), Georgia, serif",
          }}
        >
          Not a guess. Evidence.
        </h2>
        <p
          style={{
            fontSize: 14,
            color: "#909090",
            marginBottom: 40,
            maxWidth: 500,
            lineHeight: 1.6,
          }}
        >
          Every finding includes the exact frame, the action that triggered it,
          the log line, and a reproducibility count. The agent knows exactly
          what to fix.
        </p>

        <motion.div
          ref={ref}
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          style={{
            background: "#262626",
            border: "1px solid #3a3a3a",
            fontFamily: "var(--font-geist-mono)",
            maxWidth: 960,
            margin: "0 auto",
          }}
        >
          {/* Header */}
          <div
            className="flex items-center gap-3 px-5 py-4"
            style={{ borderBottom: "1px solid #2e2e2e" }}
          >
            <span
              style={{
                background: "#ff3c3c",
                color: "#fff",
                fontSize: 9,
                fontWeight: 700,
                padding: "2px 7px",
                letterSpacing: "0.12em",
                flexShrink: 0,
              }}
            >
              CRASH
            </span>
            <span style={{ fontSize: 13, color: "#fafafa" }}>{FINDING.summary}</span>
          </div>

          {/* Meta row */}
          <div
            className="flex flex-wrap gap-6 px-5 py-3"
            style={{ borderBottom: "1px solid #2e2e2e", fontSize: 11, color: "#686868" }}
          >
            <span>surface · <span style={{ color: "#666" }}>{FINDING.surface}</span></span>
            <span>confidence · <span style={{ color: "#15C78D" }}>{FINDING.confidence}</span></span>
            <span>reproduced · <span style={{ color: "#666" }}>{FINDING.reproduced}</span></span>
            <span>frame · <span style={{ color: "#666" }}>{FINDING.frame}</span></span>
          </div>

          {/* Body */}
          <div className="grid grid-cols-1 sm:grid-cols-2" style={{ fontSize: 12 }}>
            {/* Action */}
            <div className="px-5 py-4" style={{ borderRight: "1px solid #2e2e2e", borderBottom: "1px solid #2e2e2e" }}>
              <div style={{ color: "#686868", marginBottom: 8, fontSize: 10, letterSpacing: "0.1em" }}>TRIGGER</div>
              <div style={{ color: "#aaa" }}>{FINDING.action}</div>
            </div>

            {/* Log */}
            <div className="px-5 py-4" style={{ borderBottom: "1px solid #2e2e2e" }}>
              <div style={{ color: "#686868", marginBottom: 8, fontSize: 10, letterSpacing: "0.1em" }}>LOG</div>
              <div style={{ color: "#ff3c3c", fontSize: 11, wordBreak: "break-all" }}>{FINDING.logLine}</div>
            </div>

            {/* Expected */}
            <div className="px-5 py-4" style={{ borderRight: "1px solid #2e2e2e" }}>
              <div style={{ color: "#686868", marginBottom: 8, fontSize: 10, letterSpacing: "0.1em" }}>EXPECTED</div>
              <div style={{ color: "#00ff88" }}>{FINDING.expected}</div>
            </div>

            {/* Actual */}
            <div className="px-5 py-4">
              <div style={{ color: "#686868", marginBottom: 8, fontSize: 10, letterSpacing: "0.1em" }}>ACTUAL</div>
              <div style={{ color: "#ff3c3c" }}>{FINDING.actual}</div>
            </div>
          </div>

          {/* Footer */}
          <div
            className="px-5 py-3"
            style={{ borderTop: "1px solid #2e2e2e", color: "#595959", fontSize: 10, letterSpacing: "0.08em" }}
          >
            inspector-mcp · session_8f3a · run_002 · 2026-06-20T14:22:11Z
          </div>
        </motion.div>
      </div>
    </section>
  );
}
