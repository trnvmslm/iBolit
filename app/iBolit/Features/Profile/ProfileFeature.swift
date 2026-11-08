import SwiftUI
import Combine

@MainActor
final class ProfileViewModel: ObservableObject {
    @Published private(set) var state: Loadable<(name: String, phone: String)> = .idle
    private let api: any APIClientProtocol, session: SessionManager, router: Router
    init(api: any APIClientProtocol, session: SessionManager, router: Router) { self.api = api; self.session = session; self.router = router }

    func load() async {
        state = .loading
        do {
            let me = try await api.json(API.me)
            state = .loaded((me.str("full_name", "name") ?? "", me.str("phone") ?? ""))
        } catch { state = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription) }
    }
    func logout() async { await session.logout(); router.setRoot(.auth) }
}

struct ProfileView: View {
    @StateObject var viewModel: ProfileViewModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Profile").font(.largeTitle1)
                StateView(state: viewModel.state, retry: { Task { await viewModel.load() } }) { me in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(me.name).font(.cardTitle)
                        Text(me.phone).foregroundStyle(Theme.textSecondary)
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(16).card()
                }
                PrimaryButton(title: "Log out", fill: Theme.emergency) { Task { await viewModel.logout() } }
            }.padding(16)
        }
        .background(Theme.background.ignoresSafeArea()).navigationBarHidden(true)
        .task { await viewModel.load() }
    }
}
