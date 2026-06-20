"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 transition-colors duration-200"
      style={{
        borderBottom: scrolled ? "1px solid #2e2e2e" : "1px solid transparent",
        background: scrolled ? "rgba(17,17,17,0.94)" : "transparent",
        backdropFilter: scrolled ? "blur(12px)" : "none",
      }}
    >
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        <span
          className="text-sm tracking-widest uppercase"
          style={{ fontFamily: "var(--font-geist-mono)", color: "#fafafa" }}
        >
          INSPECTOR
        </span>

        <div className="flex items-center gap-8">
          <Link
            href="#how-it-works"
            className="text-xs tracking-widest uppercase transition-colors"
            style={{
              fontFamily: "var(--font-geist-mono)",
              color: "#909090",
            }}
            onMouseEnter={(e) =>
              ((e.target as HTMLElement).style.color = "#fafafa")
            }
            onMouseLeave={(e) =>
              ((e.target as HTMLElement).style.color = "#6b6b6b")
            }
          >
            Docs
          </Link>
          <Link
            href="https://github.com"
            className="text-xs tracking-widest uppercase transition-colors"
            style={{
              fontFamily: "var(--font-geist-mono)",
              color: "#909090",
            }}
            onMouseEnter={(e) =>
              ((e.target as HTMLElement).style.color = "#fafafa")
            }
            onMouseLeave={(e) =>
              ((e.target as HTMLElement).style.color = "#6b6b6b")
            }
          >
            GitHub
          </Link>
          <div
            className="px-3 py-1.5 text-xs"
            style={{
              fontFamily: "var(--font-geist-mono)",
              border: "1px solid #3a3a3a",
              color: "#15C78D",
              background: "rgba(229,255,0,0.05)",
            }}
          >
            v0.1.0-alpha
          </div>
        </div>
      </div>
    </nav>
  );
}
