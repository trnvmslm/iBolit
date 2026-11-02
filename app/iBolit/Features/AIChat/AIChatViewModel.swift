import SwiftUI
import Combine

@MainActor
final class AIChatViewModel: ObservableObject {
    @Published private(set) var messages: [ChatMessage] = []
    @Published var input = ""
    @Published private(set) var isSending = false
    @Published private(set) var isStarting = false

    private let service: AIChatService
    private let router: Router
    private var conversationID: String?

    init(service: AIChatService, router: Router, conversationID: String?) {
        self.service = service; self.router = router; self.conversationID = conversationID
    }

    var canSend: Bool { !input.trimmingCharacters(in: .whitespaces).isEmpty && !isSending && conversationID != nil }

    func start() async {
        guard messages.isEmpty else { return }
        isStarting = true; defer { isStarting = false }
        do {
            if let id = conversationID { messages = try await service.load(id) }
            else {
                let started = try await service.start()
                conversationID = started.id; messages = started.messages
            }
        } catch { router.show(error: error) }
    }

    func send() async {
        guard canSend, let id = conversationID else { return }
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        input = ""; isSending = true; defer { isSending = false }
        messages.append(ChatMessage(isUser: true, text: text))
        do {
            let reply = try await service.send(text, in: id)
            messages.append(reply)
            if reply.urgency == .emergency { router.present(.emergency) }
        } catch { router.show(error: error) }
    }

    // MARK: Navigation intents
    func seeSpecialists(_ specialty: String?) { router.push(.doctors(specialty: specialty)) }
    func callEmergency() { router.present(.emergency) }
    func close() { router.pop() }
}
