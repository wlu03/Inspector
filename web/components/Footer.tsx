"use client";

export default function Footer() {
  return (
    <footer style={{ borderTop: "1px solid #2e2e2e" }}>
      <div
        className="max-w-6xl mx-auto px-6 py-10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6"
      >
        <div className="flex flex-col gap-2">
          <span
            style={{
              fontFamily: "var(--font-geist-mono)",
              fontSize: 12,
              color: "#fafafa",
              letterSpacing: "0.15em",
              textTransform: "uppercase",
            }}
          >
            INSPECTOR
          </span>
          <span
            style={{
              fontFamily: "var(--font-geist-mono)",
              fontSize: 10,
              color: "#595959",
              letterSpacing: "0.05em",
            }}
          >
            inspector-mcp v0.1.0-alpha · MIT
          </span>
        </div>

        <div
          className="flex items-center gap-8"
          style={{
            fontFamily: "var(--font-geist-mono)",
            fontSize: 11,
            color: "#5a5a5a",
            letterSpacing: "0.08em",
          }}
        >
          {["GitHub", "Docs", "Discord", "Changelog"].map((link) => (
            <a
              key={link}
              href="#"
              style={{ color: "#5a5a5a", textDecoration: "none", transition: "color 0.15s" }}
              onMouseEnter={(e) => ((e.target as HTMLElement).style.color = "#fafafa")}
              onMouseLeave={(e) => ((e.target as HTMLElement).style.color = "#5a5a5a")}
            >
              {link}
            </a>
          ))}
        </div>
      </div>
    </footer>
  );
}
