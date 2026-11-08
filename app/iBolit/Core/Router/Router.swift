import SwiftUI
import Combine

/// Single source of truth for navigation. ViewModels call it; views only render its state.
@MainActor
final class Router: ObservableObject {
    @Published private(set) var root: RootRoute = .launch
    @Published var selectedTab: AppTab = .home
    @Published var paths: [AppTab: [Route]] = Dictionary(uniqueKeysWithValues: AppTab.allCases.map { ($0, []) })
    @Published var sheet: SheetRoute?
    @Published var fullScreen: FullScreenRoute?
    @Published var alert: AlertItem?

    // MARK: Root
    func setRoot(_ root: RootRoute) {
        if root == .auth { resetAll() }
        self.root = root
    }

    // MARK: Stack
    func push(_ route: Route, on tab: AppTab? = nil) {
        let target = tab ?? selectedTab
        if let tab { selectedTab = tab }
        paths[target, default: []].append(route)
    }
    func pop(on tab: AppTab? = nil) {
        let target = tab ?? selectedTab
        guard !(paths[target] ?? []).isEmpty else { return }
        paths[target]?.removeLast()
    }
    func popToRoot(on tab: AppTab? = nil) { paths[tab ?? selectedTab] = [] }

    func binding(for tab: AppTab) -> Binding<[Route]> {
        Binding(get: { self.paths[tab] ?? [] }, set: { self.paths[tab] = $0 })
    }

    // MARK: Tabs
    func select(_ tab: AppTab) {
        if tab == selectedTab { popToRoot(on: tab) }   // re-tap resets stack
        selectedTab = tab
    }

    // MARK: Modal
    func present(_ sheet: SheetRoute) { self.sheet = sheet }
    func present(_ fullScreen: FullScreenRoute) { self.fullScreen = fullScreen }
    func dismissModal() { sheet = nil; fullScreen = nil }
    func show(error: Error) {
        alert = AlertItem(title: "Something went wrong", message: (error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
    }

    // MARK: External
    func call(_ number: String) {
        guard let url = URL(string: "tel://\(number)") else { return }
        UIApplication.shared.open(url)
    }

    func resetAll() {
        for tab in AppTab.allCases { paths[tab] = [] }
        selectedTab = .home
        sheet = nil; fullScreen = nil
    }
}
