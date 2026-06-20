"use client";

import { motion } from "framer-motion";
import { useInView } from "framer-motion";
import { useRef } from "react";

const STATEMENTS = [
  {
    n: "01",
    text: "The agent wrote your UI.",
  },
  {
    n: "02",
    text: "Nobody tested it.",
  },
  {
    n: "03",
    text: "You're still the QA engineer.",
  },
];

function Statement({ n, text, index }: { n: string; text: string; index: number }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, x: -20 }}
      animate={inView ? { opacity: 1, x: 0 } : {}}
      transition={{ duration: 0.5, delay: index * 0.12, ease: [0.22, 1, 0.36, 1] }}
      className="flex items-baseline gap-6 py-8"
      style={{ borderBottom: "1px solid #2e2e2e" }}
    >
      <span
        style={{
          fontFamily: "var(--font-geist-mono)",
          fontSize: 11,
          color: "#595959",
          letterSpacing: "0.1em",
          flexShrink: 0,
          minWidth: 28,
        }}
      >
        {n}
      </span>
      <span
        style={{
          fontSize: "clamp(28px, 4vw, 56px)",
          fontWeight: 400,
          letterSpacing: "0em",
          lineHeight: 1.15,
          color: "#f0f0f0",
          fontFamily: "var(--font-playfair), Georgia, serif",
        }}
      >
        {text}
      </span>
    </motion.div>
  );
}

export default function ProblemSection() {
  return (
    <section id="problem" style={{ borderBottom: "1px solid #2e2e2e" }}>
      <div className="max-w-6xl mx-auto px-6 py-24">
        <div
          className="mb-10"
          style={{
            fontFamily: "var(--font-geist-mono)",
            fontSize: 11,
            color: "#909090",
            letterSpacing: "0.15em",
            textTransform: "uppercase",
          }}
        >
          // 001 · THE PROBLEM
        </div>

        {STATEMENTS.map((s, i) => (
          <Statement key={s.n} {...s} index={i} />
        ))}

        <div className="mt-10">
          <p
            style={{
              fontSize: "clamp(14px, 2vw, 18px)",
              color: "#909090",
              maxWidth: 600,
              lineHeight: 1.6,
            }}
          >
            Playwright is browser-only. Cursor can&apos;t open your iOS app.
            The existing automation ecosystem stops at the DOM.{" "}
            <span style={{ color: "#f0f0f0" }}>
              Inspector works on anything with a screen.
            </span>
          </p>
        </div>
      </div>
    </section>
  );
}
