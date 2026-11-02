import SwiftUI
import UIKit
import Combine

/// Owns tokens and the login/signup/logout calls.
@MainActor
final class SessionManager: ObservableObject {
    private let api: APIClient
    private let tokenStore: TokenStore
    init(api: APIClient, tokenStore: TokenStore) { self.api = api; self.tokenStore = tokenStore }

    private var deviceID: String { UIDevice.current.identifierForVendor?.uuidString ?? "unknown" }
    private var deviceName: String { UIDevice.current.name }

    func login(phone: String, password: String) async throws {
        let json = try await api.json(API.Auth.login(phone: phone, password: password, deviceID: deviceID, deviceName: deviceName))
        try store(json)
    }

    func signup(phone: String, password: String, fullName: String) async throws {
        let meta = try await api.json(API.meta)
        let docs = meta.find("legal_documents", "documents")?.array?.compactMap { doc -> String? in
            if let s = doc.string { return s }
            guard let key = doc.str("key", "type", "slug"), let v = doc.str("version") else { return nil }
            return "\(key):\(v)"
        } ?? ["terms_of_service:1.0", "privacy_policy:1.0"]
        let json = try await api.json(API.Auth.signup(phone: phone, password: password, fullName: fullName, documents: docs, deviceID: deviceID, deviceName: deviceName))
        try store(json)
    }

    func logout() async {
        try? await api.run(API.Auth.logout)
        expire()
    }

    func expire() { tokenStore.clear() }

    private func store(_ json: JSONValue) throws {
        guard let access = json.str("access", "access_token"), let refresh = json.str("refresh", "refresh_token") else {
            throw APIError.decoding(URLError(.cannotParseResponse))
        }
        tokenStore.accessToken = access
        tokenStore.refreshToken = refresh
    }
}

@MainActor
final class AuthViewModel: ObservableObject {
    @Published var phone = "+7 "
    @Published var password = ""
    @Published var fullName = ""
    @Published var isSignup = false
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    private let session: SessionManager
    private let router: Router
    init(session: SessionManager, router: Router) { self.session = session; self.router = router }

    var canSubmit: Bool { phone.count > 6 && password.count > 3 && (!isSignup || !fullName.isEmpty) }

    func submit() async {
        isLoading = true; errorMessage = nil
        defer { isLoading = false }
        do {
            if isSignup { try await session.signup(phone: phone, password: password, fullName: fullName) }
            else { try await session.login(phone: phone, password: password) }
            router.setRoot(.main)
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}
