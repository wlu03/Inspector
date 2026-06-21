import SwiftUI

/// Screen 1 — the Wishlist home. Three subtle, log-free defects (unchanged mechanics,
/// re-themed UI):
///   BUG-02 input-edge: Add Int-normalizes the item name, silently dropping leading
///          zeros ("007" -> "7") while the green "Added" still claims success.
///   BUG-03 display-format: the character counter is off-by-one (boundary-safe, so the
///          empty field reads a correct-looking "0/30" with no first-paint tell).
///   BUG-06 control-mismatch: the segmented Theme picker's onChange applies the
///          PREVIOUS selection, so the highlighted segment and the "Current theme:"
///          caption disagree by one tap.
struct WishlistView: View {
    @EnvironmentObject var app: AppState

    @State private var addedConfirmation = ""
    @State private var themeSelection: AppTheme = .system

    var body: some View {
        Form {
            Section {
                ForEach(app.items) { item in
                    HStack(spacing: 12) {
                        Image(systemName: item.symbol)
                            .foregroundStyle(.pink)
                            .frame(width: 26)
                        VStack(alignment: .leading) {
                            Text(item.name)
                            Text(item.price).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "star.fill").foregroundStyle(.yellow.opacity(0.8))
                    }
                }
            } header: {
                Label("\(app.items.count) wishes", systemImage: "gift.fill")
            }

            Section("Add a wish") {
                TextField("Item name", text: $app.newItemName)
                    .accessibilityIdentifier("settings.name.field")

                // BUG-03: off-by-one, but max(0,…) keeps the empty case at "0/30"
                // so there is no first-paint giveaway — only typing exposes it.
                Text("\(max(0, app.newItemName.count - 1))/30")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("settings.name.counter")

                Button(action: add) {
                    Label("Add", systemImage: "plus.circle.fill")
                }
                .accessibilityIdentifier("settings.save.button")

                Text(addedConfirmation)
                    .foregroundColor(.green)
                    .accessibilityIdentifier("settings.savedConfirmation")
            }

            Section("Appearance") {
                Picker("Theme", selection: $themeSelection) {
                    ForEach(AppTheme.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("settings.theme.picker")
                .onChange(of: themeSelection) { oldValue, _ in
                    // BUG-06: applies the PREVIOUS selection (oldValue) instead of the
                    // new one — the textbook onChange(old,new) swap.
                    app.theme = oldValue
                }

                Text("Current theme: \(app.theme.rawValue)")
                    .accessibilityIdentifier("settings.theme.current")
            }

            Section {
                NavigationLink("Wish Details", value: Route.details)
                NavigationLink("About", value: Route.about)
            }
        }
        .navigationTitle("My Wishlist")
    }

    private func add() {
        // BUG-02: "normalize" the name as if it were a numeric id — drops leading zeros.
        // The field is bound to $app.newItemName, so the mutated value re-renders
        // straight back into the field while "Added" still claims success.
        if let n = Int(app.newItemName) {
            app.newItemName = String(n)        // "007" -> "7"
        }
        app.items.append(WishItem(name: app.newItemName, price: "$0", symbol: "star"))
        addedConfirmation = "Added"            // honeypot: always claims success
    }
}
