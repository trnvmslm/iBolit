//
//  NetworkService.swift
//  iBolit
//
//  Created by Асан Мырзахметов on 19.10.2026.
//

import Foundation

class NetworkService: APIService {
    static let shared = NetworkService()
    
    private init() {}
    
    private let baseURL = "http://localhost:8000/api"
    
    private func request<T: Decodable>(
        endpoint: String,
        method: String = "GET",
        body: Data? = nil,
        requiresAuth: Bool = false
    ) async throws -> T {
        guard let url = URL(string: baseURL + endpoint) else {
            throw URLError(.badURL)
        }
        
        var request = URLRequest(url:url)
        request.httpMethod = method
        request.httpBody = body
        
        request.setValue(
            "application/json",
            forHTTPHeaderField:"Content-Type"
        )
        
        if requiresAuth {
            guard let token = TokenStorage.shared.token else {
                throw URLError(.userAuthenticationRequired)
            }
            request.setValue(
                "Bearer \(token)",
                forHTTPHeaderField: "Authorization"
            )
        }
        
        let (data, response) = try await URLSession.shared.data(for:request)
        
        print("➡️", request.httpMethod ?? "", request.url?.absoluteString ?? "")
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        
        print("STATUS:", httpResponse.statusCode)
        
        switch httpResponse.statusCode {
        case 200...299:
            do {
                return try JSONDecoder().decode(T.self, from: data)
            } catch {
                throw URLError(.badServerResponse)
            }
        default:
            throw URLError(.badServerResponse)
        }
        
    }
}
