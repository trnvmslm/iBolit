import Foundation

/// Untyped JSON. The OpenAPI schema declares most response bodies as free-form objects,
/// so features map this into typed domain models in one place (see `*Mapper` helpers).
enum JSONValue: Decodable, Hashable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else if let v = try? c.decode([String: JSONValue].self) { self = .object(v) }
        else { throw DecodingError.dataCorruptedError(in: c, debugDescription: "Unsupported JSON") }
    }

    var string: String? {
        switch self {
        case .string(let s): s
        case .number(let n): n.rounded() == n ? String(Int(n)) : String(n)
        case .bool(let b): String(b)
        default: nil
        }
    }
    var double: Double? {
        switch self {
        case .number(let n): n
        case .string(let s): Double(s)
        default: nil
        }
    }
    var int: Int? { double.map(Int.init) }
    var bool: Bool? { if case .bool(let b) = self { b } else { nil } }
    var array: [JSONValue]? { if case .array(let a) = self { a } else { nil } }
    var object: [String: JSONValue]? { if case .object(let o) = self { o } else { nil } }
    var isNull: Bool { if case .null = self { true } else { false } }

    subscript(key: String) -> JSONValue? { object?[key] }

    /// First non-null value found for any of `keys`, searching breadth-first through nested objects.
    func find(_ keys: String...) -> JSONValue? { find(keys) }
    func find(_ keys: [String]) -> JSONValue? {
        var queue: [JSONValue] = [self]
        var depth = 0
        while !queue.isEmpty, depth < 6 {
            var next: [JSONValue] = []
            for node in queue {
                guard let obj = node.object else { continue }
                for k in keys { if let v = obj[k], !v.isNull { return v } }
                next.append(contentsOf: obj.values)
            }
            queue = next; depth += 1
        }
        return nil
    }

    /// Array under any of `keys`; or `self` if it is already an array; or under common envelope keys.
    func list(_ keys: String...) -> [JSONValue] {
        if let a = array { return a }
        if let v = find(keys), let a = v.array { return a }
        if let v = find(["items", "results", "data"]), let a = v.array { return a }
        return []
    }

    func str(_ keys: String...) -> String? { find(keys)?.string }
}
