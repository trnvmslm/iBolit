import Foundation

struct Problem: Decodable {
    struct FieldError: Decodable { let field: String?; let message: String?; let code: String? }
    let type: String?
    let title: String?
    let status: Int?
    let code: String?
    let detail: String?
    let errors: [FieldError]?
}

enum APIError: LocalizedError {
    case invalidURL
    case transport(Error)
    case unauthorized
    case problem(Problem, status: Int)
    case http(status: Int)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL: "Invalid URL."
        case .transport(let e): e.localizedDescription
        case .unauthorized: "Your session has expired. Please sign in again."
        case .problem(let p, _):
            if let fields = p.errors, !fields.isEmpty {
                fields.compactMap { $0.message }.joined(separator: "\n")
            } else { p.detail ?? p.title ?? "Request failed." }
        case .http(let s): "Server error (\(s))."
        case .decoding: "Unexpected server response."
        }
    }
}
