"use client";

import { motion, useInView } from "framer-motion";
import { useRef } from "react";

const TIERS = [
  {
    name: "Open",
    price: "Free",
    sub: "OSS · MIT",
    features: [
      "MCP server loop",
      "Web + Electron adapters",
      "Local trace artifacts",
      "Local replay viewer",
      "Structured findings JSON",
    ],
    cta: "npm install inspector-mcp",
    ctaHref: "#",
    accent: false,
  },
  {
    name: "Pro",
    price: "Coming soon",
    sub: "Early access",
    features: [
      "Everything in Open",
      "Hosted dashboard",
      "Run history + trends",
      "Android + iOS adapters",
      "CI / async mode",
    ],
    cta: "Join waitlist →",
    ctaHref: "#waitlist",
    accent: true,
  },
  {
    name: "Team",
    price: "Coming soon",
    sub: "Early access",
    features: [
      "Everything in Pro",
      "Shared run history",
      "Sign-off workflows",
      "PR gate integration",
      "Priority support",
    ],
    cta: "Contact us →",
    ctaHref: "mailto:hello@inspector.dev",
    accent: false,
  },
];

export default function PricingSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <section id="pricing" style={{ borderBottom: "1px solid #2e2e2e" }}>
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
          // 005 · PRICING
        </div>
        <h2
          style={{
            fontSize: "clamp(20px, 3vw, 36px)",
            fontWeight: 800,
            letterSpacing: "-0.025em",
            color: "#fafafa",
            marginBottom: 12,
          }}
        >
          Open plumbing. Paid intelligence.
        </h2>
        <p
          style={{
            fontSize: 14,
            color: "#909090",
            marginBottom: 48,
            maxWidth: 480,
            lineHeight: 1.6,
          }}
        >
          The loop is open source. The dashboard — history, trends, CI
          integration, team sign-off — is the paid layer.
        </p>

        <div
          ref={ref}
          className="grid grid-cols-1 md:grid-cols-3 gap-px"
          style={{ border: "1px solid #2e2e2e" }}
        >
          {TIERS.map((tier, i) => (
            <motion.div
              key={tier.name}
              initial={{ opacity: 0, y: 16 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.4, delay: i * 0.1 }}
              className="flex flex-col p-8"
              style={{
                background: tier.accent ? "#262626" : "#1e1e1e",
                borderRight: "1px solid #2e2e2e",
                borderBottom: "1px solid #2e2e2e",
                outline: tier.accent ? "1px solid #3a3a3a" : "none",
              }}
            >
              <div className="mb-6">
                <div
                  style={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 11,
                    letterSpacing: "0.15em",
                    color: tier.accent ? "#15C78D" : "#555",
                    textTransform: "uppercase",
                    marginBottom: 12,
                  }}
                >
                  {tier.name}
                </div>
                <div
                  style={{
                    fontSize: "clamp(22px, 3vw, 32px)",
                    fontWeight: 800,
                    letterSpacing: "-0.02em",
                    color: "#fafafa",
                  }}
                >
                  {tier.price}
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 10,
                    color: "#686868",
                    marginTop: 4,
                    letterSpacing: "0.08em",
                  }}
                >
                  {tier.sub}
                </div>
              </div>

              <ul className="flex flex-col gap-3 flex-1 mb-8">
                {tier.features.map((f) => (
                  <li
                    key={f}
                    className="flex items-start gap-3"
                    style={{ fontSize: 13, color: "#9e9e9e", lineHeight: 1.4 }}
                  >
                    <span style={{ color: tier.accent ? "#15C78D" : "#333", flexShrink: 0 }}>
                      —
                    </span>
                    {f}
                  </li>
                ))}
              </ul>

              <a
                href={tier.ctaHref}
                style={{
                  display: "block",
                  padding: "11px 16px",
                  textAlign: "center",
                  fontFamily: "var(--font-geist-mono)",
                  fontSize: 12,
                  letterSpacing: "0.05em",
                  textDecoration: "none",
                  border: tier.accent ? "1px solid #15C78D" : "1px solid #3a3a3a",
                  color: tier.accent ? "#15C78D" : "#555",
                  background: tier.accent ? "rgba(229,255,0,0.05)" : "transparent",
                  transition: "all 0.15s",
                }}
                onMouseEnter={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.background = tier.accent ? "rgba(229,255,0,0.12)" : "#2e2e2e";
                  if (!tier.accent) el.style.color = "#fafafa";
                }}
                onMouseLeave={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.background = tier.accent ? "rgba(229,255,0,0.05)" : "transparent";
                  if (!tier.accent) el.style.color = "#555";
                }}
              >
                {tier.cta}
              </a>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
