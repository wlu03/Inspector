"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

const VW = 580;
const VH = 430;

const BOXES = [
  { id: 1, label: "logo / home",     x: 30,  y: 12,  w: 62,  h: 20 },
  { id: 2, label: "email input",     x: 163, y: 203, w: 254, h: 34 },
  { id: 3, label: "password input",  x: 163, y: 261, w: 254, h: 34 },
  { id: 4, label: "Sign in button",  x: 163, y: 315, w: 254, h: 38 },
  { id: 5, label: "forgot password", x: 326, y: 243, w: 91,  h: 13 },
  { id: 6, label: "sign up",         x: 354, y: 383, w: 44,  h: 13 },
];

const TARGET_ID = 4;
const TARGET_CX = 255;
const TARGET_CY = 334;

type Phase = "idle" | "boxes" | "cursor" | "click" | "finding";

export default function InspectorViz() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [visibleCount, setVisibleCount] = useState(0);
  const [cursorX, setCursorX] = useState(500);
  const [cursorY, setCursorY] = useState(60);
  const [clicked, setClicked] = useState(false);
  const [showFinding, setShowFinding] = useState(false);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const t = (fn: () => void, ms: number) => timers.push(setTimeout(fn, ms));

    const run = () => {
      setPhase("idle");
      setVisibleCount(0);
      setClicked(false);
      setShowFinding(false);
      setCursorX(500);
      setCursorY(60);

      t(() => setPhase("boxes"), 600);
      BOXES.forEach((_, i) => t(() => setVisibleCount(i + 1), 800 + i * 240));

      const afterBoxes = 800 + BOXES.length * 240;
      t(() => { setPhase("cursor"); setCursorX(TARGET_CX); setCursorY(TARGET_CY); }, afterBoxes + 400);
      t(() => { setPhase("click"); setClicked(true); }, afterBoxes + 1100);
      t(() => { setPhase("finding"); setShowFinding(true); }, afterBoxes + 1700);
      t(run, afterBoxes + 5800);
    };

    run();
    return () => timers.forEach(clearTimeout);
  }, []);

  const isActive = phase === "click" || phase === "finding";

  return (
    <div
      style={{
        background: "#0a0a0c",
        border: "1px solid #252528",
        overflow: "hidden",
        position: "relative",
        boxShadow: "0 32px 80px rgba(0,0,0,0.8)",
      }}
    >
      {/* Browser chrome */}
      <div
        style={{
          background: "#111113",
          borderBottom: "1px solid #1e1e22",
          height: 40,
          display: "flex",
          alignItems: "center",
          padding: "0 14px",
          gap: 10,
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          {["#ff5f56", "#ffbd2e", "#27c93f"].map((c) => (
            <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />
          ))}
        </div>
        <div
          style={{
            flex: 1, maxWidth: 300, margin: "0 auto",
            background: "#0a0a0c", border: "1px solid #1e1e22",
            borderRadius: 4, padding: "3px 10px",
            display: "flex", alignItems: "center", gap: 6,
          }}
        >
          <svg width="8" height="10" viewBox="0 0 8 10" fill="none">
            <rect x="1" y="4" width="6" height="6" rx="1" fill="#27c93f" />
            <path d="M2 4V3a2 2 0 114 0v1" stroke="#27c93f" strokeWidth="1.2" fill="none" />
          </svg>
          <span style={{ fontFamily: "var(--font-geist-mono)", fontSize: 11, color: "#7a7a7a" }}>
            localhost:3000<span style={{ color: "#909090" }}>/login</span>
          </span>
        </div>
        <div
          style={{
            fontFamily: "var(--font-geist-mono)", fontSize: 9,
            letterSpacing: "0.12em", textTransform: "uppercase", marginLeft: "auto",
            color: phase === "finding" ? "#ff4040" : phase === "click" ? "#ff4040" : "#333",
            transition: "color 0.3s",
          }}
        >
          {phase === "idle" && "·"}
          {phase === "boxes" && "perceive"}
          {phase === "cursor" && "ground"}
          {phase === "click" && "act"}
          {phase === "finding" && "finding ✗"}
        </div>
      </div>

      {/* App viewport */}
      <div style={{ position: "relative", width: "100%", paddingBottom: `${(VH / VW) * 100}%` }}>
        <svg
          viewBox={`0 0 ${VW} ${VH}`}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* Page background */}
          <rect width={VW} height={VH} fill="#0d0d10" />

          {/* Subtle dot grid */}
          <defs>
            <pattern id="dg" width="22" height="22" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="0.9" fill="#1e1e24" />
            </pattern>
          </defs>
          <rect width={VW} height={VH} fill="url(#dg)" />

          {/* ── Top nav ── */}
          <rect x={0} y={0} width={VW} height={44} fill="#111113" />
          <rect x={0} y={44} width={VW} height={1} fill="#1e1e22" />
          {/* Logo */}
          <rect x={32} y={14} width={16} height={16} rx={4} fill="#7ab8ff" />
          <text x={52} y={26} fill="#f1f5f9" fontSize={12} fontWeight="700" fontFamily="system-ui, sans-serif">Acme</text>
          {/* Nav links */}
          <text x={368} y={26} fill="#4a5568" fontSize={11} fontFamily="system-ui, sans-serif">Pricing</text>
          <text x={416} y={26} fill="#4a5568" fontSize={11} fontFamily="system-ui, sans-serif">Docs</text>
          <rect x={454} y={13} width={58} height={20} rx={4} fill="#7ab8ff" />
          <text x={483} y={26} fill="white" fontSize={10} fontWeight="600" fontFamily="system-ui, sans-serif" textAnchor="middle">Sign up</text>

          {/* ── Login card ── */}
          {/* Glow behind card */}
          <ellipse cx={290} cy={270} rx={180} ry={120} fill="rgba(122,184,255,0.04)" />
          {/* Card */}
          <rect x={150} y={68} width={280} height={360} rx={12} fill="#111113" stroke="#1e1e22" strokeWidth={1} />

          {/* Logo mark */}
          <rect x={270} y={92} width={40} height={40} rx={10} fill="#7ab8ff" />
          {/* Acme logo: clean checkmark */}
          <path
            d="M281 112 L287 119 L299 104"
            fill="none"
            stroke="white"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Heading */}
          <text x={290} y={152} textAnchor="middle" fill="#f1f5f9" fontSize={15} fontWeight="700" fontFamily="system-ui, sans-serif">Welcome back</text>
          <text x={290} y={170} textAnchor="middle" fill="#475569" fontSize={10} fontFamily="system-ui, sans-serif">Sign in to your account to continue</text>

          {/* Email label */}
          <text x={163} y={196} fill="#64748b" fontSize={10} fontWeight="600" fontFamily="system-ui, sans-serif">Email address</text>
          {/* Email input */}
          <rect x={163} y={203} width={254} height={34} rx={6} fill="#0d0d10" stroke="#252528" strokeWidth={1} />
          <text x={175} y={224} fill="#374151" fontSize={11} fontFamily="system-ui, sans-serif">you@example.com</text>

          {/* Password label + forgot */}
          <text x={163} y={254} fill="#64748b" fontSize={10} fontWeight="600" fontFamily="system-ui, sans-serif">Password</text>
          <text x={417} y={254} textAnchor="end" fill="#7ab8ff" fontSize={10} fontFamily="system-ui, sans-serif">Forgot password?</text>
          {/* Password input */}
          <rect x={163} y={261} width={254} height={34} rx={6} fill="#0d0d10" stroke="#252528" strokeWidth={1} />
          {[0,1,2,3,4,5,6,7].map(i => (
            <circle key={i} cx={179 + i * 12} cy={278} r={2.8} fill="#2d2d34" />
          ))}

          {/* Sign in button */}
          <rect
            x={163} y={315} width={254} height={38} rx={6}
            fill={isActive ? "#5a9eff" : "#7ab8ff"}
            opacity={isActive ? 1 : 0.95}
          />
          {isActive && (
            <rect x={163} y={315} width={254} height={38} rx={6} fill="none" stroke="#ff4040" strokeWidth={1.5} />
          )}
          <text x={290} y={338} textAnchor="middle" fill="white" fontSize={12} fontWeight="600" fontFamily="system-ui, sans-serif">
            {isActive ? "Signing in..." : "Sign in →"}
          </text>

          {/* Divider */}
          <line x1={163} y1={372} x2={258} y2={372} stroke="#1e1e22" strokeWidth={1} />
          <text x={290} y={376} textAnchor="middle" fill="#2d2d34" fontSize={9} fontFamily="system-ui, sans-serif">OR</text>
          <line x1={322} y1={372} x2={417} y2={372} stroke="#1e1e22" strokeWidth={1} />

          {/* Sign up */}
          <text x={232} y={394} fill="#374151" fontSize={10} fontFamily="system-ui, sans-serif">Don&apos;t have an account?</text>
          <text x={355} y={394} fill="#7ab8ff" fontSize={10} fontWeight="600" fontFamily="system-ui, sans-serif">Sign up</text>

          {/* ── Set-of-Mark overlays ── */}
          {BOXES.map((box, i) => {
            if (i >= visibleCount) return null;
            const isTarget = box.id === TARGET_ID;
            return (
              <motion.g key={box.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.18 }}>
                <rect
                  x={box.x} y={box.y} width={box.w} height={box.h}
                  fill={isTarget ? "rgba(255,64,64,0.22)" : "rgba(21,199,141,0.07)"}
                  stroke={isTarget ? "#ff4040" : "#15C78D"}
                  strokeWidth={isTarget ? 1.5 : 1}
                />
                <rect x={box.x} y={box.y - 13} width={14} height={13} fill={isTarget ? "#ff4040" : "#15C78D"} />
                <text
                  x={box.x + 7} y={box.y - 3}
                  textAnchor="middle" fill="white"
                  fontSize={8} fontWeight="bold" fontFamily="monospace"
                >
                  {box.id}
                </text>
              </motion.g>
            );
          })}

          {/* ── Cursor ── */}
          {phase !== "idle" && phase !== "boxes" && (
            <motion.g
              initial={{ x: 500, y: 60, opacity: 0 }}
              animate={{ x: cursorX, y: cursorY, opacity: 1 }}
              transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
            >
              {clicked && (
                <motion.circle cx={0} cy={0} r={4} fill="none" stroke="#ff4040" strokeWidth={1.5}
                  initial={{ r: 4, opacity: 0.9 }} animate={{ r: 22, opacity: 0 }} transition={{ duration: 0.4 }}
                />
              )}
              <path d="M0,0 L0,14 L3.5,10.5 L6,16 L8,15 L5.5,9.5 L10,9.5 Z" fill="#f0f0f0" stroke="#0a0a0c" strokeWidth={0.8} />
            </motion.g>
          )}
        </svg>

      </div>

      {/* Finding card — below the mockup viewport */}
      <AnimatePresence>
        {showFinding && (
          <motion.div
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 30, opacity: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            style={{
              background: "rgba(255,64,64,0.06)", borderTop: "2px solid #ff4040",
              padding: "14px 20px 16px",
              fontFamily: "var(--font-geist-mono)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{
                background: "#ff4040", color: "#fff", fontSize: 11,
                fontWeight: 700, padding: "3px 8px", letterSpacing: "0.12em",
                flexShrink: 0,
              }}>CRASH</span>
              <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, color: "#f0f0f0", marginRight: 16 }}>
                  Login flow fails — NullPointerException on submit
                </span>
                <span style={{ display: "inline-flex", gap: 16, flexWrap: "nowrap" }}>
                  {([
                    ["element", "#4", "#ff4040"],
                    ["frame", "012", "#888"],
                    ["reproduced", "3/3", "#ff4040"],
                    ["confidence", "HIGH", "#ff4040"],
                  ] as [string, string, string][]).map(([label, value, color]) => (
                    <span key={label} style={{ fontSize: 13, color: "#7a7a7a" }}>
                      {label} <span style={{ color }}>{value}</span>
                    </span>
                  ))}
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
