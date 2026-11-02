import Foundation

struct Reminder: Identifiable, Hashable {
    let id: String
    let title: String
    let subtitle: String
    let kind: String          // raw: medication / appointment / checkup ...
    let timeLabel: String
    var isCompleted: Bool

    var kindLabel: String {
        switch kind.lowercased() {
        case "medication", "medicine": "Medication"
        case "appointment", "consultation": "Appointment"
        case "checkup", "check_up", "check-up": "Check-up"
        default: kind.capitalized
        }
    }
    var icon: String {
        switch kind.lowercased() {
        case "medication", "medicine": "pills"
        case "appointment", "consultation": "video"
        default: "checkmark.calendar"
        }
    }
    init?(json: JSONValue) {
        guard let id = json.str("id", "reminder_id") else { return nil }
        self.id = id
        title = json.str("title", "name") ?? ""
        subtitle = json.str("subtitle", "description") ?? ""
        kind = json.str("kind", "type") ?? ""
        timeLabel = json.str("time_label", "time", "due_label", "due_at", "starts_at") ?? ""
        isCompleted = json.find("completed", "is_completed", "done")?.bool ?? false
    }
}

struct Article: Identifiable, Hashable {
    let id: String
    let title: String
    let summary: String
    let category: String
    let readMinutes: Int?
    let imageURL: URL?
    init?(json: JSONValue) {
        guard let title = json.str("title") else { return nil }
        id = json.str("slug", "id") ?? title
        self.title = title
        summary = json.str("summary", "excerpt", "subtitle", "description") ?? ""
        category = json.str("category_name", "category") ?? ""
        readMinutes = json.find("read_minutes", "reading_time_min", "read_time")?.int
        imageURL = json.str("image_url", "cover_url", "image", "cover").flatMap(URL.init(string:))
    }
}

struct HomeContent {
    var firstName: String
    var reminders: [Reminder]
    var article: Article?
}
