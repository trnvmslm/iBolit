import SwiftUI
import Combine

struct MedCardSection: Identifiable { let id: String; let title: String; let lines: [String] }

@MainActor
final class MedCardViewModel: ObservableObject {
    @Published private(set) var state: Loadable<[MedCardSection]> = .idle
    private let api: APIClient
    init(api: APIClient) { self.api = api }

    func load() async {
        state = .loading
        do {
            let json = try await api.json(API.medcard)
            let keys = ["allergies", "medications", "diagnoses", "lab_results", "vaccinations", "documents"]
            let sections = keys.compactMap { key -> MedCardSection? in
                let items = json.find(key)?.array ?? []
                let lines = items.compactMap { $0.string ?? $0.str("name", "title", "kind") }
                guard !items.isEmpty else { return nil }
                return MedCardSection(id: key, title: key.replacingOccurrences(of: "_", with: " ").capitalized, lines: lines)
            }
            state = .loaded(sections)
        } catch { state = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription) }
    }
}

struct MedCardView: View {
    @StateObject var viewModel: MedCardViewModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Medical Card").font(.largeTitle1)
                StateView(state: viewModel.state, retry: { Task { await viewModel.load() } }) { sections in
                    if sections.isEmpty { Text("Your medical card is empty").foregroundStyle(Theme.textSecondary) }
                    ForEach(sections) { s in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(s.title).font(.cardTitle)
                            ForEach(s.lines, id: \.self) { Text($0).font(.bodySecondary).foregroundStyle(Theme.textSecondary) }
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(16).card()
                    }
                }
            }.padding(16)
        }
        .background(Theme.background.ignoresSafeArea()).navigationBarHidden(true)
        .task { await viewModel.load() }
    }
}
