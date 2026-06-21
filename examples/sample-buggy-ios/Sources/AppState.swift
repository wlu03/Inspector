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
    case details
    case about
}

struct WishItem: Identifiable {
    let id = UUID()
    var name: String
    var price: String
    var symbol: String
}

/// Shared, in-memory state for the Wishlist app. No persistence and no backend —
/// every field resets to these defaults on launch, so the fixture is deterministic.
///
/// NOTE (v2 — "hard to surface"): NONE of the planted bugs emit a log. Each is a
/// subtle UI-STATE defect that only appears after a specific multi-step sequence and
/// is detectable only by reading the accessibility tree (a Text's content surfaces as
/// its AXLabel; a TextField's typed contents live in AXValue).
final class AppState: ObservableObject {
    @Published var newItemName: String = ""         // "Item name" on the Wishlist home
    @Published var theme: AppTheme = .system         // applied app-wide by RootView
    @Published var savedItemName: String = ""        // committed by Details' Continue
    @Published var savedItemPrice: String = ""
    @Published var items: [WishItem] = [
        WishItem(name: "Mechanical keyboard", price: "$120", symbol: "keyboard"),
        WishItem(name: "Noise-cancelling headphones", price: "$299", symbol: "headphones"),
        WishItem(name: "Espresso machine", price: "$450", symbol: "cup.and.saucer.fill"),
    ]
}
