import Foundation

/// In-memory fake backend for demos/previews. Mirrors the JSON shapes the app's mappers read.
/// Enable with Info.plist `USE_MOCK_API = YES` or the `-mockAPI` launch argument.
actor MockAPIClient: APIClientProtocol {
    private let latency: UInt64
    private var completedReminders: Set<String> = []
    private var chats: [String: [[String: Any]]] = [:]
    private var chatCounter = 0
    private var onExpired: (@Sendable () async -> Void)?

    init(latency: TimeInterval = 0.35) { self.latency = UInt64(latency * 1_000_000_000) }

    func setOnSessionExpired(_ handler: @escaping @Sendable () async -> Void) { onExpired = handler }

    func run(_ endpoint: Endpoint) async throws { _ = try await json(endpoint) }

    func json(_ e: Endpoint) async throws -> JSONValue {
        try? await Task.sleep(nanoseconds: latency)
        let path = e.path.replacingOccurrences(of: "/api/v1", with: "")
        let q = Dictionary(e.query.map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
        let body = (e.body.flatMap { try? JSONEncoder().encode(AnyEnc($0)) })
            .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]

        switch (e.method, path) {
        // MARK: Auth
        case (.post, "/auth/login"):
            guard (body["password"] as? String ?? "").count >= 4 else { throw problem(401, "authentication_failed", "Invalid phone or password.") }
            return try tokens()
        case (.post, "/auth/signup"):
            return try tokens()
        case (.post, "/auth/token/refresh"): return try tokens()
        case (.post, "/auth/logout"): return .null

        // MARK: Meta & legal
        case (.get, "/meta"): return try obj(["emergency_number": "103"])

        // MARK: Profile
        case (.get, "/me"): return try obj(["full_name": "Ilkhan Demo", "phone": "+7 701 234 56 78"])

        // MARK: Home
        case (.get, "/home"):
            let reminders: [[String: Any]] = [
                ["id": "r1", "title": "Vitamin D3", "subtitle": "1 capsule · after breakfast", "kind": "medication", "time_label": "08:00"],
                ["id": "r2", "title": "Neurology consultation", "subtitle": "Dr. Amina · video consultation", "kind": "appointment", "time_label": "16:30"],
                ["id": "r3", "title": "Annual health check", "subtitle": "Recommended this month", "kind": "checkup", "time_label": "12 Oct"]
            ].map { var r = $0; r["completed"] = completedReminders.contains($0["id"] as! String); return r }
            return try obj(["user": ["first_name": "Ilkhan"],
                            "reminders": ["status": "ok", "items": reminders],
                            "articles": ["status": "ok", "items": [[
                                "slug": "small-habits", "title": "Small habits, healthier days", "category_name": "Prevention",
                                "read_minutes": 4, "summary": "Five everyday changes that support your long-term wellbeing."]]]])
        case (.post, _) where path.hasPrefix("/reminders/") && path.hasSuffix("/complete"):
            completedReminders.insert(path.components(separatedBy: "/")[2]); return .null

        // MARK: Services
        case (.get, "/services/categories"):
            return try obj(["items": Self.categories.map { ["slug": $0.0, "name": $0.1] }])
        case (.get, "/services"):
            let text = (q["q"] ?? "").lowercased()
            let items = Self.services.filter {
                (q["category"] == nil || $0["category"] as? String == q["category"])
                && (text.isEmpty || ($0["name"] as! String).lowercased().contains(text))
            }
            return try obj(["items": items])

        // MARK: AI assistant
        case (.post, "/ai/conversations"):
            chatCounter += 1; let id = "mock-conv-\(chatCounter)"
            let greeting = "Hello, Ilkhan. Tell me how you're feeling and when your symptoms started."
            chats[id] = [message("assistant", greeting)]
            return try obj(["id": id, "greeting": greeting])
        case (.get, _) where path.hasPrefix("/ai/conversations/"):
            return try obj(["messages": chats[path.components(separatedBy: "/")[3]] ?? []])
        case (.post, _) where path.hasSuffix("/messages") && path.hasPrefix("/ai/conversations/"):
            let id = path.components(separatedBy: "/")[3]
            let text = (body["text"] as? String ?? "")
            var reply = aiReply(for: text)
            chats[id, default: []] += [message("user", text), reply["assistant_message"] as! [String: Any]]
            reply["conversation_id"] = id
            return try obj(reply)

        // MARK: Consultations / doctors / medcard
        case (.get, "/consultations"):
            return try obj(["items": q["tab"] == "past"
                ? [["id": "c0", "title": "General check-up", "status": "completed", "starts_at": "2026-09-14 11:00"]]
                : [["id": "c1", "title": "Neurology consultation · Dr. Amina", "status": "scheduled", "starts_at": "Today, 16:30"],
                   ["id": "c2", "title": "Complete blood count", "status": "scheduled", "starts_at": "12 Nov, 09:15"]]])
        case (.get, "/doctors"):
            let all: [[String: Any]] = [
                ["id": "d1", "full_name": "Dr. Amina Seitova", "specialty": "Neurologist"],
                ["id": "d2", "full_name": "Dr. Timur Nurlanov", "specialty": "Neurologist"],
                ["id": "d3", "full_name": "Dr. Dana Omarova", "specialty": "General practitioner"]]
            let s = q["specialty"]?.lowercased()
            return try obj(["items": all.filter { s == nil || ($0["specialty"] as! String).lowercased() == s }])
        case (.get, "/medcard"):
            return try obj(["allergies": ["Penicillin", "Pollen"], "medications": ["Vitamin D3 · 1 capsule daily"],
                            "diagnoses": ["Seasonal rhinitis"], "lab_results": ["Complete blood count · 2 Oct"],
                            "vaccinations": ["Influenza 2025", "Tetanus 2023"], "documents": []])

        default: throw problem(404, "not_found", "Mock has no handler for \(e.method.rawValue) \(path).")
        }
    }

    // MARK: Helpers
    private func tokens() throws -> JSONValue { try obj(["access": "mock-access-token", "refresh": "mock-refresh-token"]) }

    private func message(_ role: String, _ text: String) -> [String: Any] {
        ["id": UUID().uuidString, "role": role, "text": text, "created_at": ISO8601DateFormatter().string(from: Date())]
    }

    private func aiReply(for input: String) -> [String: Any] {
        let t = input.lowercased()
        if ["chest pain", "faint", "can't breathe", "sudden severe", "unconscious"].contains(where: { t.contains($0) }) {
            return ["assistant_message": message("assistant", "These symptoms can be serious. Please call Emergency 103 now."), "urgency": "emergency"]
        }
        if ["headache", "dizz", "migraine", "numb"].contains(where: { t.contains($0) }) {
            return ["assistant_message": message("assistant", "Based on your description, you may want to consult a neurologist. Would you like to book a consultation?"),
                    "urgency": "recommend", "recommended_specialty": "Neurologist"]
        }
        if ["cough", "fever", "sore throat", "cold"].contains(where: { t.contains($0) }) {
            return ["assistant_message": message("assistant", "This sounds like a common respiratory infection. A general practitioner can examine you."),
                    "urgency": "recommend", "recommended_specialty": "General practitioner"]
        }
        return ["assistant_message": message("assistant", "Thanks. Can you tell me when it started and whether anything makes it better or worse?"), "urgency": "routine"]
    }

    private func problem(_ status: Int, _ code: String, _ detail: String) -> APIError {
        .problem(Problem(type: nil, title: detail, status: status, code: code, detail: detail, errors: nil), status: status)
    }

    private func obj(_ value: Any) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: JSONSerialization.data(withJSONObject: value))
    }

    private struct AnyEnc: Encodable { let v: any Encodable; init(_ v: any Encodable) { self.v = v }; func encode(to e: Encoder) throws { try v.encode(to: e) } }

    private static let categories = [("general-medicine", "General Medicine"), ("diagnostics", "Diagnostics"), ("specialists", "Specialists"),
        ("laboratory", "Laboratory"), ("vaccination", "Vaccination"), ("emergency", "Emergency"), ("veterinary", "Veterinary"), ("telehealth", "Telehealth")]

    private static let services: [[String: Any]] = [
        ["id": "s1", "name": "Neurology consultation", "summary": "Headache, dizziness and nerve health", "price": 12000, "duration_minutes": 30, "providers_count": 3, "category": "specialists"],
        ["id": "s2", "name": "Complete blood count", "summary": "A clear picture of your general health", "price": 3500, "duration_minutes": 15, "providers_count": 2, "category": "laboratory"],
        ["id": "s3", "name": "Seasonal flu vaccination", "summary": "Protect yourself and your family", "price": 6000, "duration_minutes": 20, "providers_count": 4, "category": "vaccination"],
        ["id": "s4", "name": "Video visit with a GP", "summary": "See a doctor from home", "price": 5000, "duration_minutes": 20, "providers_count": 6, "category": "telehealth"],
        ["id": "s5", "name": "Abdominal ultrasound", "summary": "Non-invasive imaging", "price": 9000, "duration_minutes": 25, "providers_count": 2, "category": "diagnostics"]]
}
