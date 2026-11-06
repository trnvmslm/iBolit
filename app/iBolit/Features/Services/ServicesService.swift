import Foundation

struct ServicesService {
    let api: any APIClientProtocol
    func categories() async throws -> [ServiceCategory] {
        try await api.json(API.Services.categories).list("categories").compactMap(ServiceCategory.init(json:))
    }
    func services(query: String?, category: String?) async throws -> [ServiceItem] {
        try await api.json(API.Services.list(query: query, category: category)).list("services").compactMap(ServiceItem.init(json:))
    }
}
