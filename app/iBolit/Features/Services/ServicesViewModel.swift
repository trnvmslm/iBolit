import SwiftUI
import Combine

@MainActor
final class ServicesViewModel: ObservableObject {
    @Published var search = "" { didSet { scheduleSearch() } }
    @Published private(set) var categories: [ServiceCategory] = ServiceCategory.fallback
    @Published private(set) var services: Loadable<[ServiceItem]> = .idle
    @Published private(set) var selectedCategory: ServiceCategory?

    private let service: ServicesService
    private let router: Router
    private var searchTask: Task<Void, Never>?

    init(service: ServicesService, router: Router, category: ServiceCategory?) {
        self.service = service; self.router = router; self.selectedCategory = category
    }

    var title: String { selectedCategory?.name ?? "Care for every day" }
    var sectionTitle: String { search.isEmpty && selectedCategory == nil ? "Recommended services" : "Services" }

    func load() async {
        if let cats = try? await service.categories(), !cats.isEmpty { categories = cats }
        await reload()
    }

    func reload() async {
        if services.value == nil { services = .loading }
        do { services = .loaded(try await service.services(query: search, category: selectedCategory?.id)) }
        catch is CancellationError { }
        catch { services = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription) }
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        searchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard !Task.isCancelled else { return }
            await self?.reload()
        }
    }

    // MARK: Navigation intents
    func open(_ category: ServiceCategory) {
        if category.isEmergency { router.present(.emergency) }
        else { router.push(.services(category: category), on: .services) }
    }
    func book(_ item: ServiceItem) { router.push(.booking(serviceID: item.id, title: item.name)) }
    func openNotifications() { router.push(.notifications) }
}
