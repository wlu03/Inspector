import SwiftUI

/// Hosts the navigation stack shared by all three screens. The Wishlist home is the
/// root; Wish Details and About are pushed onto `path`. Details' Continue mutates
/// `path` (BUG-05 pushes a duplicate Details); About's Clear clears it (works correctly).
struct RootView: View {
    @StateObject private var app = AppState()
    @State private var path: [Route] = []

    var body: some View {
        NavigationStack(path: $path) {
            WishlistView()
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .details: DetailsView(path: $path)
                    case .about: AboutView(path: $path)
                    }
                }
        }
        .environmentObject(app)
        .tint(.pink)
        .preferredColorScheme(app.theme.colorScheme)   // whatever theme BUG-06 applied
    }
}
