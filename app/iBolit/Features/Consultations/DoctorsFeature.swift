import SwiftUI
import Combine

struct DoctorRow: Identifiable, Hashable {
    let id: String, name: String, specialty: String
    init?(json: JSONValue) {
        guard let id = json.str("id", "provider_id"), let name = json.str("full_name", "name") else { return nil }
        self.id = id; self.name = name
        specialty = json.find("specialty")?.string ?? json.find("specialty")?.str("name") ?? json.str("specialty_name") ?? ""
    }
}

@MainActor
final class DoctorsViewModel: ObservableObject {
    @Published private(set) var state: Loadable<[DoctorRow]> = .idle
    let specialty: String?
    private let api: any APIClientProtocol
    init(api: any APIClientProtocol, specialty: String?) { self.api = api; self.specialty = specialty }

    func load() async {
        state = .loading
        do { state = .loaded(try await api.json(API.Doctors.list(specialty: specialty)).list("doctors").compactMap(DoctorRow.init(json:))) }
        catch { state = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription) }
    }
}

struct DoctorsView: View {
    @StateObject var viewModel: DoctorsViewModel
    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                StateView(state: viewModel.state, retry: { Task { await viewModel.load() } }) { rows in
                    ForEach(rows) { d in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(d.name).font(.cardTitle)
                            Text(d.specialty).font(.bodySecondary).foregroundStyle(Theme.textSecondary)
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(16).card()
                    }
                }
            }.padding(16)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle(viewModel.specialty ?? "Specialists").navigationBarTitleDisplayMode(.inline)
        .task { await viewModel.load() }
    }
}
