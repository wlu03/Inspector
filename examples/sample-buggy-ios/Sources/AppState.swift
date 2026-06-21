import SwiftUI

enum AppTheme: String, CaseIterable, Identifiable {
    case light = "Light"
    case dark = "Dark"
    case system = "System"

    var id: String { rawValue }

    var colorScheme: ColorScheme? {
        switch self {
        case .light: return .light
        case .dark: return .dark
        case .system: return nil
        }
    }
}

enum Route: Hashable {
    case profile
    case about
}

/// Shared, in-memory app state. No persistence and no backend — every field
/// resets to these defaults on launch, so the fixture is fully deterministic.
///
/// NOTE (v2 — "hard to surface"): NONE of the planted bugs emit a log. Each is a
/// subtle UI-STATE defect that only appears after a specific multi-step sequence
/// and is detectable only by reading the accessibility tree carefully (a Text's
/// content surfaces as its AXLabel; a TextField's typed contents live in AXValue).
final class AppState: ObservableObject {
    @Published var settingsName: String = ""        // "Your name" on Settings
    @Published var theme: AppTheme = .system        // applied app-wide by RootView
    @Published var profileDisplayName: String = ""  // committed by Profile's Continue
    @Published var profileEmail: String = ""
}
