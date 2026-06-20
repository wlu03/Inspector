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
final class AppState: ObservableObject {
    @Published var settingsName: String = ""        // "Your name" on Settings
    @Published var notificationsEnabled: Bool = false
    @Published var theme: AppTheme = .system
    @Published var profileDisplayName: String = ""
    @Published var profileEmail: String = ""
}
