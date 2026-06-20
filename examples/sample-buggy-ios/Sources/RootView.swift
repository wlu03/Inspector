import SwiftUI

/// Hosts the navigation stack shared by all three screens. Settings is the
/// root; Profile and About are pushed onto `path`. The `path` binding is also
/// what BUG-05 abuses to route to the wrong screen.
struct RootView: View {
    @StateObject private var app = AppState()
    @State private var path: [Route] = []

    var body: some View {
        NavigationStack(path: $path) {
            SettingsView()
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .profile: ProfileView()
                    case .about: AboutView(path: $path)
                    }
                }
        }
        .environmentObject(app)
        .preferredColorScheme(app.theme.colorScheme)   // Theme picker actually works
    }
}
