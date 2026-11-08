import SwiftUI

struct ComingSoonView: View {
    let title: String
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "hammer").font(.largeTitle).foregroundStyle(Theme.primary)
            Text(title).font(.cardTitle)
            Text("This screen has no design yet.").font(.bodySecondary).foregroundStyle(Theme.textSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.background)
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
    }
}

struct EmergencySheet: View {
    let router: Router
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "phone.arrow.up.right.fill").font(.system(size: 40)).foregroundStyle(Theme.emergency)
            Text("Emergency 103").font(.largeTitle1)
            Text("Call now if you have a sudden severe headache, chest pain, weakness or fainting.")
                .multilineTextAlignment(.center).foregroundStyle(Theme.textSecondary)
            PrimaryButton(title: "Call 103", systemImage: "phone.fill", fill: Theme.emergency) {
                router.call("103")
            }
            Button("Close") { router.dismissModal() }
        }
        .padding(24).presentationDetents([.medium])
    }
}
