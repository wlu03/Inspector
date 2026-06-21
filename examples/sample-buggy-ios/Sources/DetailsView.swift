import SwiftUI

/// Screen 2 — Wish Details. Three subtle, log-free defects (unchanged mechanics,
/// re-themed UI):
///   BUG-01 state-sync: the editable fields are fresh @State that is NEVER seeded back
///          from the model (.onAppear read-back missing), so a committed name is lost
///          on re-entry — while the model-backed "Saved wish" row still shows it. Two
///          nodes in the same tree contradict each other.
///   BUG-04 display-format: "Wishlist completeness" uses Int division, so 2-of-3 fields
///          truncates 66.67% to "66%" instead of rounding to "67%".
///   BUG-05 navigation-focus: Continue pushes a DUPLICATE Details before About, so
///          backing out of About lands on a blank Details and two Backs never reach the
///          Wishlist root (the stack is one screen too deep).
struct DetailsView: View {
    @EnvironmentObject var app: AppState
    @Binding var path: [Route]

    // BUG-01: fresh, view-local state — never seeded from app.savedItemName.
    @State private var itemName = ""
    @State private var price = ""
    @State private var note = ""
    @State private var didContinue = false

    var body: some View {
        Form {
            Section("Saved wish") {
                // Unconditional, model-backed: a committed name shows here even when the
                // editable field above has reverted to empty (the contradiction).
                Text(app.savedItemName.isEmpty ? "—" : app.savedItemName)
                    .accessibilityIdentifier("profile.savedName")
            }

            Section("Item") {
                TextField("Item name", text: $itemName)
                    .accessibilityIdentifier("profile.displayName.field")
                TextField("Price", text: $price)
                    .accessibilityIdentifier("profile.email.field")
                TextField("Note", text: $note)
                    .accessibilityIdentifier("profile.phone.field")

                // BUG-04: Int division truncates instead of rounding.
                Text("Wishlist \(completenessPercent)% complete")
                    .accessibilityIdentifier("profile.completeness")

                Button("Continue", action: submit)
                    .accessibilityIdentifier("profile.continue.button")
            }

            if didContinue {
                Section("Result") {
                    Text("Saved \(itemName.isEmpty ? "(empty)" : itemName)")
                        .accessibilityIdentifier("profile.result")
                }
            }
        }
        .navigationTitle("Wish Details")
        // BUG-01: NO .onAppear { itemName = app.savedItemName; price = app.savedItemPrice }
        // — the model is written on Continue but never read back into the fields.
    }

    private var completenessPercent: Int {
        let filled = [itemName, price, note]
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            .count
        return filled * 100 / 3        // BUG-04: 2/3 -> 66, not round(66.67) == 67
    }

    private func submit() {
        app.savedItemName = itemName
        app.savedItemPrice = price
        didContinue = true
        // BUG-05: should be just `path.append(.about)`. The stray duplicate Details
        // makes the stack one screen too deep, so Back never returns to the root.
        path.append(.details)
        path.append(.about)
    }
}
