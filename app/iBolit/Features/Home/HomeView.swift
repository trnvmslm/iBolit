import SwiftUI

struct HomeView: View {
    @StateObject var viewModel: HomeViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                BrandHeader(showAvatar: true, initials: initials, onBell: viewModel.openNotifications)
                VStack(alignment: .leading, spacing: 4) {
                    Text(viewModel.dateLine).font(.caption1).foregroundStyle(Theme.textSecondary)
                    Text("\(viewModel.greeting)\(name)").font(.largeTitle1).foregroundStyle(Theme.textPrimary)
                    Text("A little care goes a long way.").foregroundStyle(Theme.textSecondary)
                }
                aiCard
                PrimaryButton(title: "Emergency 103", systemImage: "phone.fill", fill: Theme.emergency, action: viewModel.emergency)
                quickActions
                StateView(state: viewModel.state, retry: { Task { await viewModel.load() } }) { content in
                    VStack(alignment: .leading, spacing: 20) {
                        remindersSection(content.reminders)
                        if let article = content.article { articleSection(article) }
                    }
                }
            }
            .padding(.horizontal, 16).padding(.bottom, 24)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationBarHidden(true)
        .task { await viewModel.load() }
        .refreshable { await viewModel.load() }
    }

    private var name: String { viewModel.state.value.map { $0.firstName.isEmpty ? "" : ", \($0.firstName)" } ?? "" }
    private var initials: String { viewModel.state.value?.firstName.prefix(1).uppercased() ?? "" }

    private var aiCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("YOUR AI HEALTH ASSISTANT", systemImage: "sparkles").font(.caption1).foregroundStyle(Theme.primary)
                Spacer()
                Image(systemName: "heart.text.square").foregroundStyle(Theme.primary)
            }
            Text("What's bothering you?").font(.largeTitle1).foregroundStyle(Theme.textPrimary)
            Text("Describe your symptoms and AI will help you find the right specialist.")
                .font(.bodySecondary).foregroundStyle(Theme.textSecondary)
            PrimaryButton(title: "Ask iBolit AI", systemImage: "sparkles", action: viewModel.askAI)
        }
        .padding(18)
        .background(LinearGradient(colors: [Theme.mint, Theme.mintStrong.opacity(0.7)], startPoint: .topLeading, endPoint: .bottomTrailing),
                    in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "How can we help?")
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible())], spacing: 12) {
                tile("Video Call", "video", viewModel.videoCall)
                tile("Book Consultation", "calendar.badge.plus", viewModel.bookConsultation)
                tile("Chat with Specialist", "bubble.left", viewModel.chatWithSpecialist)
                tile("Anonymous Consultation", "shield.lefthalf.filled", viewModel.anonymousConsultation)
            }
        }
    }

    private func tile(_ title: String, _ icon: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 16) {
                Image(systemName: icon).foregroundStyle(Theme.primary)
                Text(title).font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.textPrimary).multilineTextAlignment(.leading)
            }
            .frame(maxWidth: .infinity, minHeight: 84, alignment: .topLeading).padding(16).card()
        }.buttonStyle(.plain)
    }

    private func remindersSection(_ items: [Reminder]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Smart Reminder", actionTitle: "View all", action: viewModel.allReminders)
            ForEach(items) { r in
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 12) {
                        Image(systemName: r.icon).foregroundStyle(Theme.primary)
                            .frame(width: 40, height: 40).background(Theme.mint, in: RoundedRectangle(cornerRadius: 12))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.title).font(.cardTitle)
                            Text(r.subtitle).font(.bodySecondary).foregroundStyle(Theme.textSecondary)
                        }
                        Spacer()
                        Text(r.timeLabel).font(.system(size: 15, weight: .bold)).foregroundStyle(Theme.primary)
                    }
                    HStack {
                        Chip(text: r.kindLabel)
                        Spacer()
                        if r.isCompleted {
                            Label("Completed", systemImage: "checkmark").font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.textSecondary)
                        } else {
                            Button("Mark completed") { Task { await viewModel.complete(r) } }
                                .font(.system(size: 14, weight: .semibold))
                        }
                    }
                }
                .padding(16).card().opacity(r.isCompleted ? 0.7 : 1)
            }
        }
    }

    private func articleSection(_ a: Article) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "For a healthier you", actionTitle: "All news", action: viewModel.allArticles)
            VStack(alignment: .leading, spacing: 0) {
                AsyncImage(url: a.imageURL) { $0.resizable().scaledToFill() } placeholder: { Theme.mint }
                    .frame(height: 170).clipped()
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(a.category).font(.caption1).foregroundStyle(Theme.primary)
                        Spacer()
                        if let m = a.readMinutes { Text("\(m) min read").font(.caption1).foregroundStyle(Theme.textSecondary) }
                    }
                    Text(a.title).font(.titleSection)
                    Text(a.summary).font(.bodySecondary).foregroundStyle(Theme.textSecondary)
                }.padding(16)
            }
            .card().clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        }
    }
}
