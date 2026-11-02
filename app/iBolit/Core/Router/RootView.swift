import SwiftUI

struct RootView: View {
    @EnvironmentObject private var router: Router
    @EnvironmentObject private var container: AppContainer

    var body: some View {
        Group {
            switch router.root {
            case .launch: ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.background)
            case .auth: LoginView(viewModel: container.makeAuthViewModel())
            case .main: MainTabView()
            }
        }
        .animation(.easeInOut, value: router.root)
        .sheet(item: $router.sheet) { sheet in
            ViewFactory(container: container).view(for: sheet)
        }
        .fullScreenCover(item: $router.fullScreen) { route in
            ViewFactory(container: container).view(for: route)
        }
        .alert(item: $router.alert) { item in
            Alert(title: Text(item.title), message: item.message.map(Text.init), dismissButton: .default(Text(item.buttonTitle)))
        }
    }
}

struct MainTabView: View {
    @EnvironmentObject private var router: Router
    @EnvironmentObject private var container: AppContainer

    var body: some View {
        TabView(selection: Binding(get: { router.selectedTab }, set: { router.select($0) })) {
            ForEach(AppTab.allCases) { tab in
                NavigationStack(path: router.binding(for: tab)) {
                    ViewFactory(container: container).rootView(for: tab)
                        .navigationDestination(for: Route.self) { route in
                            ViewFactory(container: container).view(for: route)
                        }
                }
                .tabItem { Label(tab.title, systemImage: tab.icon) }
                .tag(tab)
            }
        }
    }
}
