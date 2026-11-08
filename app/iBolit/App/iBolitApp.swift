//
//  iBolitApp.swift
//  iBolit
//
//  Created by Асан Мырзахметов on 28.09.2026.
//

import SwiftUI

@main
struct iBolitApp: App {
    
    @StateObject private var container = AppContainer()
    
    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(container)
                .environmentObject(container.router)
                .tint(Theme.primary)
        }
    }
}
