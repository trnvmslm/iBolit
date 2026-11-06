import Foundation

struct AIChatService {
    let api: any APIClientProtocol

    struct Started { let id: String; let messages: [ChatMessage] }

    func start() async throws -> Started {
        let json = try await api.json(API.AI.start)
        guard let id = json.str("id", "conversation_id") else { throw APIError.decoding(URLError(.cannotParseResponse)) }
        var messages = json.find("messages")?.array?.compactMap(ChatMessage.init(json:)) ?? []
        if messages.isEmpty, let greeting = json.str("greeting", "greeting_text") {
            messages = [ChatMessage(isUser: false, text: greeting)]
        }
        return Started(id: id, messages: messages)
    }

    func load(_ id: String) async throws -> [ChatMessage] {
        try await api.json(API.AI.conversation(id)).find("messages")?.array?.compactMap(ChatMessage.init(json:)) ?? []
    }

    func send(_ text: String, in id: String) async throws -> ChatMessage {
        let json = try await api.json(API.AI.send(conversationID: id, text: text))
        guard let reply = ChatMessage(json: json) else { throw APIError.decoding(URLError(.cannotParseResponse)) }
        return reply
    }
}
