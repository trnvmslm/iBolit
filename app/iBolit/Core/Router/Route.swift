import Foundation

enum AppTab: String, CaseIterable, Identifiable, Hashable {
    case home, services, consultations, medCard, profile
    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: "Home"
        case .services: "Services"
        case .consultations: "Consultations"
        case .medCard: "Medical Card"
        case .profile: "Profile"
        }
    }
    var icon: String {
        switch self {
        case .home: "house"
        case .services: "square.grid.2x2"
        case .consultations: "video"
        case .medCard: "folder"
        case .profile: "person"
        }
    }
}

/// Top-level app state.
enum RootRoute: Hashable { case launch, auth, main }

/// Every pushable screen in the app.
enum Route: Hashable {
    case aiChat(conversationID: String?)
    case services(category: ServiceCategory?)
    case booking(serviceID: String, title: String)
    case doctors(specialty: String?)
    case consultation(id: String)
    case reminders
    case articles
    case notifications
}

enum SheetRoute: Identifiable, Hashable {
    case emergency
    var id: String { String(describing: self) }
}

enum FullScreenRoute: Identifiable, Hashable {
    case videoCall(consultationID: String)
    var id: String { String(describing: self) }
}

struct AlertItem: Identifiable {
    let id = UUID()
    let title: String
    let message: String?
    var buttonTitle: String = "OK"
}
