import SwiftUI

/// Hosts the navigation stack shared by all three screens. Settings is the root;
/// Profile and About are pushed onto `path`. Profile's Continue mutates `path`
/// (BUG-05 pushes a duplicate Profile); About's Reset clears it (works correctly).
struct RootView: View {
    @StateObject private var app = AppState()
    @State private var path: [Route] = []

    var body: some View {
        NavigationStack(path: $path) {
            SettingsView()
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .profile: ProfileView(path: $path)
                    case .about: AboutView(path: $path)
                    }
                }
        }
        .environmentObject(app)
        .preferredColorScheme(app.theme.colorScheme)   // whatever theme BUG-06 applied
    }
}
