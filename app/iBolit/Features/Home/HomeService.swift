import Foundation

struct HomeService {
    let api: APIClient

    func load() async throws -> HomeContent {
        let json = try await api.json(API.home)
        var name = json.find("user", "profile")?.str("first_name", "name", "full_name") ?? json.str("first_name")
        if name == nil {
            let me = try? await api.json(API.me)
            name = me?.str("first_name", "full_name", "name")
        }
        let reminders = (json.find("reminders", "smart_reminders")?.list() ?? []).compactMap(Reminder.init(json:))
        let articleJSON = json.find("articles", "featured_article", "picked_articles", "news")
        let article = (articleJSON?.array?.first ?? articleJSON).flatMap(Article.init(json:))
        return HomeContent(firstName: name?.components(separatedBy: " ").first ?? "", reminders: reminders, article: article)
    }

    func complete(_ id: String) async throws {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
        try await api.run(API.Reminders.complete(id: id, date: f.string(from: Date())))
    }
}
