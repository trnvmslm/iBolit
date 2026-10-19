//
//  TokenStorage.swift
//  iBolit
//
//  Created by Асан Мырзахметов on 19.10.2026.
//

import Foundation
import Combine

final class TokenStorage: ObservableObject {
    static let shared = TokenStorage()
    
    @Published var token: String? {
            didSet { UserDefaults.standard.set(token, forKey: "jwt_token") }
        }
    
    private init() {
        self.token = UserDefaults.standard.string(forKey: "jwt_token")
    }
}
