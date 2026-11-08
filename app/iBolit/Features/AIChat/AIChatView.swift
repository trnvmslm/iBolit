import SwiftUI

struct AIChatView: View {
    @StateObject var viewModel: AIChatViewModel

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("iBolit AI").font(.largeTitle1)
                            Text("AI Health Assistant").foregroundStyle(Theme.textSecondary)
                            HStack {
                                Label("AI · Not a clinician", systemImage: "sparkles").font(.caption1).foregroundStyle(Theme.primary)
                                    .padding(.horizontal, 10).padding(.vertical, 6).background(Theme.mint, in: Capsule())
                                Spacer()
                                Text("Today").font(.caption1).foregroundStyle(Theme.textSecondary)
                            }
                        }
                        ForEach(viewModel.messages) { m in
                            bubble(m).id(m.id)
                            if let specialty = m.specialty, !m.isUser { recommendation(specialty) }
                            if m.urgency == .emergency { warning }
                        }
                        if viewModel.isSending || viewModel.isStarting { ProgressView().padding(.leading) }
                        disclaimer
                    }
                    .padding(16)
                }
                .onChange(of: viewModel.messages.count) { _ in
                    if let last = viewModel.messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
                }
            }
            composer
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .navigationBarTrailing) { Image(systemName: "ellipsis").foregroundStyle(Theme.primary) } }
        .toolbar(.hidden, for: .tabBar)
        .task { await viewModel.start() }
    }

    private func bubble(_ m: ChatMessage) -> some View {
        VStack(alignment: m.isUser ? .trailing : .leading, spacing: 4) {
            Text("\(m.author) · \(m.timeLabel)").font(.caption1).foregroundStyle(Theme.textSecondary)
            Text(m.text).font(.system(size: 16))
                .foregroundStyle(m.isUser ? .white : Theme.textPrimary)
                .padding(14)
                .background(m.isUser ? Theme.primary : .white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
        .frame(maxWidth: .infinity, alignment: m.isUser ? .trailing : .leading)
    }

    private func recommendation(_ specialty: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("A \(specialty.lowercased()) may help", systemImage: "brain.head.profile").font(.cardTitle)
            Text("Specialists are available today. Choose a doctor to discuss your symptoms.")
                .font(.bodySecondary).foregroundStyle(Theme.textSecondary)
            PrimaryButton(title: "See recommended specialists", systemImage: "arrow.right") { viewModel.seeSpecialists(specialty) }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.mint, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private var warning: some View {
        Button(action: viewModel.callEmergency) {
            Label("Sudden severe headache, weakness or fainting? Call Emergency 103 now.", systemImage: "exclamationmark.triangle")
                .font(.bodySecondary).foregroundStyle(Theme.emergency).multilineTextAlignment(.leading)
                .padding(14).frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.emergencyTint, in: RoundedRectangle(cornerRadius: 16))
        }.buttonStyle(.plain)
    }

    private var disclaimer: some View {
        Label("AI provides preliminary guidance and does not replace a medical professional.", systemImage: "checkmark.shield")
            .font(.bodySecondary).foregroundStyle(Theme.primaryDark)
            .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.mint, in: RoundedRectangle(cornerRadius: 16))
    }

    private var composer: some View {
        HStack(spacing: 10) {
            Image(systemName: "plus").foregroundStyle(Theme.primary)
            TextField("Tell me more…", text: $viewModel.input, axis: .vertical).lineLimit(1...4)
            Image(systemName: "mic").foregroundStyle(Theme.primary)
            Button { Task { await viewModel.send() } } label: {
                Image(systemName: "arrow.up").foregroundStyle(.white).frame(width: 34, height: 34)
                    .background(Theme.primary, in: RoundedRectangle(cornerRadius: 10))
            }.disabled(!viewModel.canSend)
        }
        .padding(12).background(.white, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .padding(.horizontal, 16).padding(.vertical, 8)
    }
}
