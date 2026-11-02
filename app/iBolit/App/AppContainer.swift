import SwiftUI
import Combine

/// Composition root: owns long-lived dependencies and builds ViewModels.
@MainActor
final class AppContainer: ObservableObject {
    let router = Router()
    let tokenStore: TokenStore
    let session: SessionManager
    let api: APIClient

    init() {
        let store = KeychainTokenStore()
        self.tokenStore = store
        let api = APIClient(baseURL: AppConfig.baseURL, tokenStore: store)
        self.api = api
        self.session = SessionManager(api: api, tokenStore: store)
        let router = self.router
        let session = self.session
        Task { await api.setOnSessionExpired { await MainActor.run { session.expire(); router.setRoot(.auth) } } }
        router.setRoot(store.accessToken == nil ? .auth : .main)
    }

    // MARK: ViewModel factories
    func makeAuthViewModel() -> AuthViewModel { AuthViewModel(session: session, router: router) }
    func makeHomeViewModel() -> HomeViewModel { HomeViewModel(service: HomeService(api: api), router: router) }
    func makeServicesViewModel(category: ServiceCategory? = nil) -> ServicesViewModel {
        ServicesViewModel(service: ServicesService(api: api), router: router, category: category)
    }
    func makeAIChatViewModel(conversationID: String?) -> AIChatViewModel {
        AIChatViewModel(service: AIChatService(api: api), router: router, conversationID: conversationID)
    }
    func makeConsultationsViewModel() -> ConsultationsViewModel { ConsultationsViewModel(api: api, router: router) }
    func makeMedCardViewModel() -> MedCardViewModel { MedCardViewModel(api: api) }
    func makeProfileViewModel() -> ProfileViewModel { ProfileViewModel(api: api, session: session, router: router) }
}

enum AppConfig {
    static var baseURL: URL {
        let raw = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String ?? "http://localhost:8000"
        return URL(string: raw)!
    }
}
