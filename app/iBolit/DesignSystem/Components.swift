import SwiftUI

struct CardModifier: ViewModifier {
    var fill: Color = Theme.card
    func body(content: Content) -> some View {
        content.background(fill, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            .shadow(color: .black.opacity(0.04), radius: 8, y: 2)
    }
}
extension View { func card(fill: Color = Theme.card) -> some View { modifier(CardModifier(fill: fill)) } }

struct PrimaryButton: View {
    let title: String
    var systemImage: String? = nil
    var fill: Color = Theme.primary
    var isLoading = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if isLoading { ProgressView().tint(.white) }
                else {
                    if let systemImage { Image(systemName: systemImage) }
                    Text(title).font(.system(size: 16, weight: .semibold))
                }
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 50)
            .background(fill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .disabled(isLoading)
    }
}

struct SectionHeader: View {
    let title: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    var body: some View {
        HStack {
            Text(title).font(.titleSection).foregroundStyle(Theme.textPrimary)
            Spacer()
            if let actionTitle, let action {
                Button(actionTitle, action: action).font(.system(size: 14, weight: .semibold))
            }
        }
    }
}

struct Chip: View {
    let text: String
    var body: some View {
        Text(text).font(.caption1).foregroundStyle(Theme.textSecondary)
            .padding(.horizontal, 10).padding(.vertical, 5)
            .background(Theme.chip, in: Capsule())
    }
}

struct BrandHeader: View {
    var showAvatar = false
    var initials = ""
    var onBell: () -> Void
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "waveform.path.ecg")
                .font(.system(size: 16, weight: .bold)).foregroundStyle(.white)
                .frame(width: 32, height: 32).background(Theme.primary, in: RoundedRectangle(cornerRadius: 9))
            Text("iBolit").font(.system(size: 20, weight: .bold)).foregroundStyle(Theme.textPrimary)
            Spacer()
            Button(action: onBell) { Image(systemName: "bell").foregroundStyle(Theme.primary) }
            if showAvatar {
                Text(initials).font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.primary)
                    .frame(width: 36, height: 36).background(Theme.mintStrong, in: Circle())
            }
        }
    }
}

/// Generic async state used by every ViewModel.
enum Loadable<T> {
    case idle, loading, loaded(T), failed(String)
    var value: T? { if case .loaded(let v) = self { v } else { nil } }
    var isLoading: Bool { if case .loading = self { true } else { false } }
}

struct StateView<T, Content: View>: View {
    let state: Loadable<T>
    var retry: () -> Void
    @ViewBuilder var content: (T) -> Content
    var body: some View {
        switch state {
        case .idle, .loading: ProgressView().frame(maxWidth: .infinity).padding(40)
        case .failed(let msg):
            VStack(spacing: 12) {
                Text(msg).font(.bodySecondary).foregroundStyle(Theme.textSecondary).multilineTextAlignment(.center)
                Button("Retry", action: retry).buttonStyle(.borderedProminent)
            }.padding(24)
        case .loaded(let v): content(v)
        }
    }
}
