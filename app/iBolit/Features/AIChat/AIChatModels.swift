import Foundation

enum Urgency: String { case routine, recommend, urgent, emergency }

struct ChatMessage: Identifiable, Hashable {
    let id: String
    let isUser: Bool
    let text: String
    let date: Date
    var urgency: Urgency? = nil
    var specialty: String? = nil

    var author: String { isUser ? "You" : "iBolit AI" }
    var timeLabel: String { Self.formatter.string(from: date) }
    private static let formatter: DateFormatter = { let f = DateFormatter(); f.dateFormat = "HH:mm"; return f }()

    init(id: String = UUID().uuidString, isUser: Bool, text: String, date: Date = Date(), urgency: Urgency? = nil, specialty: String? = nil) {
        self.id = id; self.isUser = isUser; self.text = text; self.date = date; self.urgency = urgency; self.specialty = specialty
    }

    /// Tolerant mapping: the spec types these bodies as free-form objects.
    init?(json: JSONValue) {
        let node = json.find("assistant_message", "reply", "message", "answer") ?? json
        guard let text = node.string ?? node.str("text", "content", "body") else { return nil }
        let role = (node.str("role", "author", "sender") ?? "assistant").lowercased()
        self.init(
            id: node.str("id") ?? UUID().uuidString,
            isUser: role == "user" || role == "patient",
            text: text,
            date: node.str("created_at", "sent_at").flatMap(Self.parseDate) ?? Date(),
            urgency: json.str("urgency").flatMap { Urgency(rawValue: $0.lowercased()) },
            specialty: { () -> String? in
                guard let s = json.find("recommended_specialty", "suggested_specialty", "specialty") else { return nil }
                return s.string ?? s.str("name", "title")
            }()
        )
    }

    private static func parseDate(_ s: String) -> Date? {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: s) ?? ISO8601DateFormatter().date(from: s)
    }
}
