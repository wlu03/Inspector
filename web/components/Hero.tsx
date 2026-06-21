"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import InspectorViz from "./InspectorViz";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={copy}
      className="transition-colors"
      style={{
        fontFamily: "var(--font-geist-mono)",
        fontSize: 11,
        color: copied ? "#15C78D" : "#6b6b6b",
        letterSpacing: "0.05em",
        cursor: "pointer",
        background: "none",
        border: "none",
        padding: 0,
      }}
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

export default function Hero() {
  return (
    <section className="relative min-h-screen flex flex-col justify-center" style={{ paddingTop: 80 }}>
      <div className="max-w-6xl mx-auto px-6 w-full">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          {/* Left */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          >
            {/* Label */}
            <div
              className="mb-6"
              style={{
                fontFamily: "var(--font-geist-mono)",
                fontSize: 11,
                color: "#7a7a7a",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
              }}
            >
              // MCP · Computer-Use · Cross-Platform
            </div>

            {/* Headline */}
            <h1
              style={{
                fontSize: "clamp(36px, 5vw, 72px)",
                fontWeight: 400,
                lineHeight: 1.1,
                letterSpacing: "0em",
                color: "#f0f0f0",
                marginBottom: 28,
                fontFamily: "var(--font-playfair), Georgia, serif",
              }}
            >
              Your agent
              <br />
              wrote the code.
              <br />
              <span style={{ color: "#15C78D" }}>Inspector</span>
              <br />
              checks it <em>works.</em>
            </h1>

            {/* Sub */}
            <p
              style={{
                fontSize: 15,
                color: "#9e9e9e",
                lineHeight: 1.6,
                maxWidth: 420,
                marginBottom: 40,
              }}
            >
              Give your coding agent eyes and hands on the live build —
              across web, Electron, Android, and iOS. Pure computer-use.
              Structured findings. No Playwright.
            </p>

            {/* CTA */}
            <div className="flex flex-col gap-3 w-full">
              <div
                style={{
                  background: "#242424",
                  border: "1px solid #3a3a3a",
                  padding: "16px 22px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 16,
                  width: "100%",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 16,
                    color: "#f0f0f0",
                    letterSpacing: "-0.01em",
                  }}
                >
                  <span style={{ color: "#15C78D" }}>$</span>{" "}
                  <span style={{ color: "#f0f0f0" }}>npm install</span>{" "}
                  <span style={{ color: "#15C78D" }}>inspector-mcp</span>
                </span>
                <CopyButton text="npm install inspector-mcp" />
              </div>

              <a
                href="https://github.com"
                style={{
                  padding: "14px 22px",
                  border: "1px solid #3a3a3a",
                  color: "#909090",
                  fontSize: 14,
                  fontFamily: "var(--font-geist-mono)",
                  textDecoration: "none",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  transition: "border-color 0.15s, color 0.15s",
                  width: "100%",
                }}
                onMouseEnter={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.borderColor = "#555";
                  el.style.color = "#f0f0f0";
                }}
                onMouseLeave={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.borderColor = "#3a3a3a";
                  el.style.color = "#6b6b6b";
                }}
              >
                View on GitHub →
              </a>
            </div>
          </motion.div>

          {/* Right — Loop visualization */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
          >
            <InspectorViz />
            <div
              className="mt-3 flex gap-4 justify-end"
              style={{
                fontFamily: "var(--font-geist-mono)",
                fontSize: 10,
                color: "#686868",
                letterSpacing: "0.1em",
              }}
            >
              <span>PERCEIVE</span>
              <span>→</span>
              <span>GROUND</span>
              <span>→</span>
              <span>ACT</span>
              <span>→</span>
              <span>VERIFY</span>
            </div>
          </motion.div>
        </div>
      </div>

      {/* Bottom rule */}
      <div
        className="absolute bottom-0 left-0 right-0"
        style={{ borderBottom: "1px solid #2e2e2e" }}
      />
    </section>
  );
}
