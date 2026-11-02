import SwiftUI
import Combine

struct ConsultationRow: Identifiable, Hashable {
    let id: String, title: String, subtitle: String, when: String
    init?(json: JSONValue) {
        guard let id = json.str("id", "consultation_id") else { return nil }
        self.id = id
        title = json.find("service", "provider", "doctor")?.str("name", "title", "full_name") ?? json.str("title", "service_name") ?? "Consultation"
        subtitle = json.str("status", "mode", "type") ?? ""
        when = json.str("starts_at", "scheduled_at", "date") ?? ""
    }
}

@MainActor
final class ConsultationsViewModel: ObservableObject {
    enum Tab: String, CaseIterable { case upcoming, past }
    @Published var tab: Tab = .upcoming { didSet { Task { await load() } } }
    @Published private(set) var state: Loadable<[ConsultationRow]> = .idle
    private let api: APIClient, router: Router
    init(api: APIClient, router: Router) { self.api = api; self.router = router }

    func load() async {
        state = .loading
        do { state = .loaded(try await api.json(API.Consultations.list(tab: tab.rawValue)).list("consultations").compactMap(ConsultationRow.init(json:))) }
        catch { state = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription) }
    }
    func open(_ row: ConsultationRow) { router.push(.consultation(id: row.id)) }
}

struct ConsultationsView: View {
    @StateObject var viewModel: ConsultationsViewModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Consultations").font(.largeTitle1)
                Picker("", selection: $viewModel.tab) {
                    Text("Upcoming").tag(ConsultationsViewModel.Tab.upcoming)
                    Text("Past").tag(ConsultationsViewModel.Tab.past)
                }.pickerStyle(.segmented)
                StateView(state: viewModel.state, retry: { Task { await viewModel.load() } }) { rows in
                    if rows.isEmpty { Text("Nothing here yet").foregroundStyle(Theme.textSecondary).frame(maxWidth: .infinity).padding() }
                    ForEach(rows) { row in
                        Button { viewModel.open(row) } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(row.title).font(.cardTitle)
                                Text(row.when).font(.bodySecondary).foregroundStyle(Theme.textSecondary)
                                if !row.subtitle.isEmpty { Chip(text: row.subtitle.capitalized) }
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(16).card()
                        }.buttonStyle(.plain)
                    }
                }
            }.padding(16)
        }
        .background(Theme.background.ignoresSafeArea()).navigationBarHidden(true)
        .task { await viewModel.load() }
    }
}
