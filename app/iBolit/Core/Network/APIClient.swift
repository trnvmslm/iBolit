import Foundation

/// URLSession client with Bearer auth and single-flight refresh on 401.
protocol APIClientProtocol: Sendable {
    func json(_ endpoint: Endpoint) async throws -> JSONValue
    func run(_ endpoint: Endpoint) async throws
    func setOnSessionExpired(_ handler: @escaping @Sendable () async -> Void) async
}

actor APIClient: APIClientProtocol {
    private let baseURL: URL
    private let tokenStore: TokenStore
    private let session: URLSession
    private let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }()
    private var refreshTask: Task<Void, Error>?
    private var onSessionExpired: (@Sendable () async -> Void)?

    init(baseURL: URL, tokenStore: TokenStore, session: URLSession = .shared) {
        self.baseURL = baseURL; self.tokenStore = tokenStore; self.session = session
    }

    func setOnSessionExpired(_ handler: @escaping @Sendable () async -> Void) { onSessionExpired = handler }

    func send<T: Decodable>(_ endpoint: Endpoint, as type: T.Type = T.self) async throws -> T {
        let data = try await perform(endpoint)
        do { return try decoder.decode(T.self, from: data) } catch { throw APIError.decoding(error) }
    }

    /// For endpoints whose body is untyped or empty.
    func json(_ endpoint: Endpoint) async throws -> JSONValue {
        let data = try await perform(endpoint)
        if data.isEmpty { return .null }
        return try decoder.decode(JSONValue.self, from: data)
    }

    func run(_ endpoint: Endpoint) async throws { _ = try await perform(endpoint) }

    // MARK: Core
    private func perform(_ endpoint: Endpoint, isRetry: Bool = false) async throws -> Data {
        let request = try makeRequest(endpoint)
        let data: Data, response: URLResponse
        do { (data, response) = try await session.data(for: request) }
        catch { throw APIError.transport(error) }
        guard let http = response as? HTTPURLResponse else { throw APIError.http(status: -1) }

        switch http.statusCode {
        case 200..<300: return data
        case 401 where endpoint.requiresAuth && !isRetry && tokenStore.refreshToken != nil:
            try await refreshTokens()
            return try await perform(endpoint, isRetry: true)
        case 401 where endpoint.requiresAuth:
            await onSessionExpired?()
            throw APIError.unauthorized
        default:
            if let problem = try? decoder.decode(Problem.self, from: data) { throw APIError.problem(problem, status: http.statusCode) }
            throw APIError.http(status: http.statusCode)
        }
    }

    private func refreshTokens() async throws {
        if let task = refreshTask { return try await task.value }
        let task = Task<Void, Error> {
            guard let refresh = tokenStore.refreshToken else { throw APIError.unauthorized }
            do {
                let pair: TokenPair = try await self.send(API.Auth.refresh(refresh))
                tokenStore.accessToken = pair.access
                tokenStore.refreshToken = pair.refresh
            } catch {
                tokenStore.clear()
                await onSessionExpired?()
                throw APIError.unauthorized
            }
        }
        refreshTask = task
        defer { refreshTask = nil }
        try await task.value
    }

    private func makeRequest(_ e: Endpoint) throws -> URLRequest {
        guard var comps = URLComponents(url: baseURL.appendingPathComponent(e.path), resolvingAgainstBaseURL: false) else { throw APIError.invalidURL }
        if !e.query.isEmpty { comps.queryItems = e.query }
        guard let url = comps.url else { throw APIError.invalidURL }
        var r = URLRequest(url: url)
        r.httpMethod = e.method.rawValue
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        r.setValue(Locale.preferredLanguages.first, forHTTPHeaderField: "Accept-Language")
        if e.requiresAuth, let t = tokenStore.accessToken { r.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        if let body = e.body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        return r
    }
}

struct TokenPair: Decodable { let access: String; let refresh: String }

private struct AnyEncodable: Encodable {
    let value: any Encodable
    init(_ v: any Encodable) { value = v }
    func encode(to encoder: Encoder) throws { try value.encode(to: encoder) }
}
