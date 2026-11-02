import Foundation

struct ServiceCategory: Identifiable, Hashable {
    let id: String          // slug sent as ?category=
    let name: String

    var icon: String {
        let k = (id + name).lowercased()
        if k.contains("general") { return "stethoscope" }
        if k.contains("diagnos") { return "viewfinder" }
        if k.contains("special") { return "person.2" }
        if k.contains("lab") { return "testtube.2" }
        if k.contains("vaccin") { return "syringe" }
        if k.contains("emergen") { return "light.beacon.max" }
        if k.contains("vet") { return "pawprint" }
        if k.contains("tele") { return "video" }
        return "cross.case"
    }
    var isEmergency: Bool { (id + name).lowercased().contains("emergen") }

    init(id: String, name: String) { self.id = id; self.name = name }
    init?(json: JSONValue) {
        guard let name = json.str("name", "title") else { return nil }
        self.name = name
        self.id = json.str("slug", "id", "code") ?? name
    }

    static let telehealth = ServiceCategory(id: "telehealth", name: "Telehealth")
    /// Shown while/if the API returns no categories (matches the design).
    static let fallback: [ServiceCategory] = [
        .init(id: "general-medicine", name: "General Medicine"), .init(id: "diagnostics", name: "Diagnostics"),
        .init(id: "specialists", name: "Specialists"), .init(id: "laboratory", name: "Laboratory"),
        .init(id: "vaccination", name: "Vaccination"), .init(id: "emergency", name: "Emergency"),
        .init(id: "veterinary", name: "Veterinary"), .telehealth
    ]
}

struct ServiceItem: Identifiable, Hashable {
    let id: String
    let name: String
    let summary: String
    let priceText: String
    let durationMinutes: Int?
    let availabilityText: String

    init?(json: JSONValue) {
        guard let id = json.str("id", "service_id"), let name = json.str("name", "title") else { return nil }
        self.id = id; self.name = name
        summary = json.str("summary", "description", "subtitle") ?? ""
        durationMinutes = json.find("duration_minutes", "duration_min", "duration")?.int
        if let amount = json.find("price", "price_amount", "price_kzt")?.double {
            let f = NumberFormatter(); f.numberStyle = .decimal; f.groupingSeparator = ","
            priceText = "\(f.string(from: NSNumber(value: amount)) ?? "\(Int(amount))") ₸"
        } else { priceText = json.str("price_label") ?? "" }
        if let label = json.str("availability_label", "availability_text") { availabilityText = label }
        else if let n = json.find("providers_count", "available_count", "specialists_count")?.int {
            availabilityText = "\(n) specialist\(n == 1 ? "" : "s") available"
        } else { availabilityText = "" }
    }
}
