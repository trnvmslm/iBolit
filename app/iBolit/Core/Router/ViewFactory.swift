import SwiftUI

/// Maps routes to concrete screens and wires their ViewModels. The only place that knows both.
@MainActor
struct ViewFactory {
    let container: AppContainer

    @ViewBuilder
    func rootView(for tab: AppTab) -> some View {
        switch tab {
        case .home: HomeView(viewModel: container.makeHomeViewModel())
        case .services: ServicesView(viewModel: container.makeServicesViewModel(), isRoot: true)
        case .consultations: ConsultationsView(viewModel: container.makeConsultationsViewModel())
        case .medCard: MedCardView(viewModel: container.makeMedCardViewModel())
        case .profile: ProfileView(viewModel: container.makeProfileViewModel())
        }
    }

    @ViewBuilder
    func view(for route: Route) -> some View {
        switch route {
        case .aiChat(let id): AIChatView(viewModel: container.makeAIChatViewModel(conversationID: id))
        case .services(let category): ServicesView(viewModel: container.makeServicesViewModel(category: category), isRoot: false)
        case .booking(_, let title): ComingSoonView(title: "Book: \(title)")
        case .doctors(let specialty): DoctorsView(viewModel: DoctorsViewModel(api: container.api, specialty: specialty))
        case .consultation(let id): ComingSoonView(title: "Consultation \(id.prefix(6))")
        case .reminders: ComingSoonView(title: "Reminders")
        case .articles: ComingSoonView(title: "Health articles")
        case .notifications: ComingSoonView(title: "Notifications")
        }
    }

    @ViewBuilder
    func view(for sheet: SheetRoute) -> some View {
        switch sheet {
        case .emergency: EmergencySheet(router: container.router)
        }
    }

    @ViewBuilder
    func view(for route: FullScreenRoute) -> some View {
        switch route {
        case .videoCall(let id): ComingSoonView(title: "Video \(id.prefix(6))")
        }
    }
}
