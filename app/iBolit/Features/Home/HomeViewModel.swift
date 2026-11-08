import SwiftUI
import Combine

@MainActor
final class HomeViewModel: ObservableObject {
    @Published private(set) var state: Loadable<HomeContent> = .idle
    private let service: HomeService
    private let router: Router

    init(service: HomeService, router: Router) { self.service = service; self.router = router }

    var dateLine: String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US"); f.dateFormat = "EEEE, d MMMM"
        return f.string(from: Date()).uppercased()
    }
    var greeting: String {
        switch Calendar.current.component(.hour, from: Date()) {
        case 5..<12: "Good morning"
        case 12..<18: "Good afternoon"
        default: "Good evening"
        }
    }

    func load() async {
        if state.value == nil { state = .loading }
        do { state = .loaded(try await service.load()) }
        catch { state = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription) }
    }

    func complete(_ reminder: Reminder) async {
        guard var content = state.value, let i = content.reminders.firstIndex(of: reminder) else { return }
        content.reminders[i].isCompleted = true
        state = .loaded(content)                       // optimistic
        do { try await service.complete(reminder.id) }
        catch {
            content.reminders[i].isCompleted = false
            state = .loaded(content)
            router.show(error: error)
        }
    }

    // MARK: Navigation intents
    func askAI() { router.push(.aiChat(conversationID: nil)) }
    func emergency() { router.present(.emergency) }
    func openNotifications() { router.push(.notifications) }
    func videoCall() { router.push(.services(category: .telehealth), on: .services) }
    func bookConsultation() { router.select(.services) }
    func chatWithSpecialist() { router.push(.doctors(specialty: nil)) }
    func anonymousConsultation() { router.push(.aiChat(conversationID: nil)) }
    func allReminders() { router.push(.reminders) }
    func allArticles() { router.push(.articles) }
}
