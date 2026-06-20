import { createContext, useContext, useEffect, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

// Multi-screen, deliberately-buggy Expo / React Native test fixture.
//
// Three screens (Settings / Profile / About) wired with a tiny state-based
// navigator — no @react-navigation, no extra deps. Six planted bugs, each
// emitting a distinct greppable log line (console.error -> logcat / Metro)
// before its faulty behavior. See BUGS.md / bugs.json for the scored manifest.

// ---------------------------------------------------------------------------
// Shared app state (cross-screen) — standard React Context idiom.
// ---------------------------------------------------------------------------
const AppState = createContext(null);

const COLORS = {
  Light: { bg: "#ffffff", fg: "#111111", muted: "#666666" },
  Dark: { bg: "#111111", fg: "#f5f5f5", muted: "#999999" },
  System: { bg: "#f0f0f0", fg: "#222222", muted: "#777777" },
};

function useApp() {
  return useContext(AppState);
}

// ---------------------------------------------------------------------------
// Settings screen
// ---------------------------------------------------------------------------
function SettingsScreen() {
  const { name, setName, theme, setTheme } = useApp();
  const [toast, setToast] = useState("");

  // BUG-02: the toggle flips its visible label but never updates real state.
  const [notifLabel, setNotifLabel] = useState("Off"); // visual only
  const [notificationsEnabled] = useState(false); // real state, never set

  // BUG-06: log the missing-a11y-label defect deterministically on mount.
  useEffect(() => {
    console.error("missing a11y label on primary action");
  }, []);

  const onSave = () => {
    // BUG-01 (crash): log, then throw before the confirmation is shown.
    console.error("query not invalidated after save");
    const result = undefined;
    result.show(); // TypeError: undefined is not an object
    setToast("Saved"); // unreachable
  };

  const onToggleNotifications = () => {
    // BUG-02 (silent state): label flips, underlying state stays put.
    console.error("toggle state desync");
    setNotifLabel((prev) => (prev === "Off" ? "On" : "Off"));
    // note: setNotificationsEnabled intentionally never called.
  };

  const c = COLORS[theme];
  return (
    <ScrollView contentContainerStyle={{ padding: 24 }}>
      <Text style={{ fontSize: 28, fontWeight: "bold", color: c.fg }}>
        Settings
      </Text>

      <Text style={{ marginTop: 16, color: c.fg }}>Your name</Text>
      <TextInput
        placeholder="Your name"
        value={name}
        onChangeText={setName}
        style={{ borderWidth: 1, borderColor: c.muted, padding: 8, marginTop: 4 }}
      />

      {/* BUG-06: decorative element carries the obvious "Save" label/testID,
          so naive locators hit this non-interactive Text instead of the
          real button below. */}
      <View style={{ flexDirection: "row", alignItems: "center", marginTop: 16 }}>
        <Text
          testID="save-button"
          accessibilityLabel="Save"
          style={{ color: c.muted }}
        >
          Save ✓
        </Text>
      </View>

      {/* Real Save action: no testID, no accessibilityLabel, not exposed to a11y. */}
      <Pressable
        accessible={false}
        onPress={onSave}
        style={{
          backgroundColor: "#2563eb",
          padding: 12,
          borderRadius: 6,
          marginTop: 8,
          alignItems: "center",
        }}
      >
        <Text style={{ color: "#ffffff", fontWeight: "600" }}>Save</Text>
      </Pressable>

      <Text style={{ color: "green", marginTop: 12 }}>{toast}</Text>

      {/* Notifications toggle (BUG-02) */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 24,
        }}
      >
        <Text style={{ color: c.fg }}>Notifications</Text>
        <Pressable
          accessibilityLabel="Notifications toggle"
          onPress={onToggleNotifications}
          style={{ borderWidth: 1, borderColor: c.muted, padding: 8, borderRadius: 6 }}
        >
          <Text style={{ color: c.fg }}>{notifLabel}</Text>
        </Pressable>
      </View>
      <Text style={{ color: c.muted, fontSize: 12 }}>
        (underlying state: {notificationsEnabled ? "enabled" : "disabled"})
      </Text>

      {/* Theme picker (works correctly) */}
      <Text style={{ color: c.fg, marginTop: 24 }}>Theme</Text>
      <View style={{ flexDirection: "row", marginTop: 8 }}>
        {["Light", "Dark", "System"].map((t) => (
          <Pressable
            key={t}
            accessibilityLabel={`Theme ${t}`}
            onPress={() => setTheme(t)}
            style={{
              borderWidth: 1,
              borderColor: theme === t ? "#2563eb" : c.muted,
              backgroundColor: theme === t ? "#2563eb" : "transparent",
              padding: 8,
              borderRadius: 6,
              marginRight: 8,
            }}
          >
            <Text style={{ color: theme === t ? "#ffffff" : c.fg }}>{t}</Text>
          </Pressable>
        ))}
      </View>
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Profile screen
// ---------------------------------------------------------------------------
function ProfileScreen() {
  const { name, theme } = useApp();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("");

  // BUG-04: the summary should reflect the Settings name, but it reads from a
  // local (always-empty) variable instead of shared state, so it stays blank.
  const summaryName = ""; // should be `name` from context
  useEffect(() => {
    console.error("state not propagated across screens");
  }, [name]);

  const onContinue = () => {
    // BUG-03 (validation bypass): real checks are skipped; proceed regardless.
    console.error("validation skipped on submit");
    // intended: require displayName, require email containing "@".
    setStatus("Continuing… (accepted)");
  };

  const c = COLORS[theme];
  return (
    <ScrollView contentContainerStyle={{ padding: 24 }}>
      <Text style={{ fontSize: 28, fontWeight: "bold", color: c.fg }}>
        Profile
      </Text>

      <Text style={{ marginTop: 16, color: c.fg }}>Display name (required)</Text>
      <TextInput
        accessibilityLabel="Display name"
        placeholder="Display name"
        value={displayName}
        onChangeText={setDisplayName}
        style={{ borderWidth: 1, borderColor: c.muted, padding: 8, marginTop: 4 }}
      />

      <Text style={{ marginTop: 16, color: c.fg }}>Email (must contain @)</Text>
      <TextInput
        accessibilityLabel="Email"
        placeholder="Email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        style={{ borderWidth: 1, borderColor: c.muted, padding: 8, marginTop: 4 }}
      />

      <Pressable
        accessibilityLabel="Continue"
        testID="continue-button"
        onPress={onContinue}
        style={{
          backgroundColor: "#2563eb",
          padding: 12,
          borderRadius: 6,
          marginTop: 16,
          alignItems: "center",
        }}
      >
        <Text style={{ color: "#ffffff", fontWeight: "600" }}>Continue</Text>
      </Pressable>
      <Text style={{ color: "green", marginTop: 12 }}>{status}</Text>

      <View style={{ marginTop: 24, borderTopWidth: 1, borderColor: c.muted, paddingTop: 12 }}>
        <Text style={{ color: c.muted }}>Summary</Text>
        <Text accessibilityLabel="Profile summary name" style={{ color: c.fg }}>
          Name from Settings: {summaryName}
        </Text>
      </View>
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// About screen
// ---------------------------------------------------------------------------
const APP_VERSION = "1.0.0";

function AboutScreen() {
  const { theme, navigate, resetAll } = useApp();

  const onReset = () => {
    // BUG-05 (navigation defect): clears nothing, routes to a dead end.
    console.error("reset no-op, wrong route");
    // intended: resetAll(); navigate("Settings");
    navigate("__deadend__");
  };

  const c = COLORS[theme];
  return (
    <ScrollView contentContainerStyle={{ padding: 24 }}>
      <Text style={{ fontSize: 28, fontWeight: "bold", color: c.fg }}>About</Text>
      <Text style={{ marginTop: 16, color: c.fg }}>Sample Buggy Android</Text>
      <Text style={{ color: c.muted, marginTop: 4 }}>
        A deterministic test fixture for automated UI agents.
      </Text>
      <Text accessibilityLabel="Version" style={{ color: c.muted, marginTop: 4 }}>
        Version {APP_VERSION}
      </Text>

      <Pressable
        accessibilityLabel="Reset all"
        testID="reset-button"
        onPress={onReset}
        style={{
          backgroundColor: "#dc2626",
          padding: 12,
          borderRadius: 6,
          marginTop: 24,
          alignItems: "center",
        }}
      >
        <Text style={{ color: "#ffffff", fontWeight: "600" }}>Reset all</Text>
      </Pressable>
    </ScrollView>
  );
}

function DeadEndScreen() {
  const { theme } = useApp();
  const c = COLORS[theme];
  return (
    <View style={{ flex: 1, justifyContent: "center", alignItems: "center", padding: 24 }}>
      <Text style={{ color: c.muted }}>Nothing here.</Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Root: tiny state-based navigator + shared state provider.
// ---------------------------------------------------------------------------
export default function App() {
  const [screen, setScreen] = useState("Settings");
  const [name, setName] = useState("");
  const [theme, setTheme] = useState("Light");

  const navigate = (target) => setScreen(target);
  const resetAll = () => {
    setName("");
    setTheme("Light");
  };

  const c = COLORS[theme];
  const ctx = { name, setName, theme, setTheme, navigate, resetAll };

  const screens = {
    Settings: <SettingsScreen />,
    Profile: <ProfileScreen />,
    About: <AboutScreen />,
  };
  const body = screens[screen] || <DeadEndScreen />;

  return (
    <AppState.Provider value={ctx}>
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: 48 }}>
        {/* Nav bar */}
        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-around",
            borderBottomWidth: 1,
            borderColor: c.muted,
            paddingBottom: 8,
          }}
        >
          {["Settings", "Profile", "About"].map((s) => (
            <Pressable
              key={s}
              accessibilityLabel={`Nav ${s}`}
              onPress={() => navigate(s)}
              style={{ padding: 8 }}
            >
              <Text
                style={{
                  color: screen === s ? "#2563eb" : c.fg,
                  fontWeight: screen === s ? "700" : "400",
                }}
              >
                {s}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={{ flex: 1 }}>{body}</View>
      </View>
    </AppState.Provider>
  );
}
