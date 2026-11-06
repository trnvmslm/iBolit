import Foundation

enum HTTPMethod: String { case get = "GET", post = "POST", put = "PUT", patch = "PATCH", delete = "DELETE" }

struct Endpoint {
    var path: String
    var method: HTTPMethod = .get
    var query: [URLQueryItem] = []
    var body: (any Encodable)? = nil
    var requiresAuth: Bool = true

    init(_ path: String, method: HTTPMethod = .get, query: [String: String?] = [:], body: (any Encodable)? = nil, requiresAuth: Bool = true) {
        self.path = path
        self.method = method
        self.query = query.compactMap { k, v in v.map { URLQueryItem(name: k, value: $0) } }.sorted { $0.name < $1.name }
        self.body = body
        self.requiresAuth = requiresAuth
    }
}

/// Typed catalogue of the endpoints used by the app (paths from the OpenAPI spec, all under /api/v1).
enum API {
    private static let v1 = "/api/v1"

    enum Auth {
        static func login(phone: String, password: String, deviceID: String, deviceName: String) -> Endpoint {
            Endpoint("\(v1)/auth/login", method: .post,
                     body: ["phone": phone, "password": password, "device_id": deviceID, "device_name": deviceName],
                     requiresAuth: false)
        }
        static func signup(phone: String, password: String, fullName: String, deviceID: String, deviceName: String) -> Endpoint {
            struct Body: Encodable {
                let phone, password, full_name: String
                /// DEMO ONLY: empty list, no consent is recorded. Remove before release.
                let accepted_documents: [String] = []
                let device_id, device_name: String
            }
            return Endpoint("\(v1)/auth/signup", method: .post,
                            body: Body(phone: phone, password: password, full_name: fullName, device_id: deviceID, device_name: deviceName),
                            requiresAuth: false)
        }
        static func refresh(_ token: String) -> Endpoint {
            Endpoint("\(v1)/auth/token/refresh", method: .post, body: ["refresh": token], requiresAuth: false)
        }
        static let logout = Endpoint("\(v1)/auth/logout", method: .post)
    }
    static let meta = Endpoint("\(v1)/meta", requiresAuth: false)
    static let home = Endpoint("\(v1)/home")
    static let me = Endpoint("\(v1)/me")
    static let emergency = Endpoint("\(v1)/emergency", requiresAuth: false)
    static let medcard = Endpoint("\(v1)/medcard")

    enum Services {
        static let categories = Endpoint("\(v1)/services/categories")
        static func list(query: String?, category: String?) -> Endpoint {
            Endpoint("\(v1)/services", query: ["q": query?.nilIfEmpty, "category": category])
        }
    }
    enum Reminders {
        static func complete(id: String, date: String) -> Endpoint {
            Endpoint("\(v1)/reminders/\(id)/complete", method: .post, body: ["date": date])
        }
    }
    enum AI {
        static let start = Endpoint("\(v1)/ai/conversations", method: .post)
        static func conversation(_ id: String) -> Endpoint { Endpoint("\(v1)/ai/conversations/\(id)") }
        static func send(conversationID: String, text: String, quickAction: String = "explain_symptoms") -> Endpoint {
            Endpoint("\(v1)/ai/conversations/\(conversationID)/messages", method: .post,
                     body: ["text": text, "quick_action": quickAction])
        }
    }
    enum Consultations {
        static func list(tab: String) -> Endpoint { Endpoint("\(v1)/consultations", query: ["tab": tab, "limit": "20"]) }
    }
    enum Doctors {
        static func list(specialty: String?) -> Endpoint { Endpoint("\(v1)/doctors", query: ["specialty": specialty]) }
    }
}

extension String {
    var nilIfEmpty: String? { trimmingCharacters(in: .whitespaces).isEmpty ? nil : self }
}
