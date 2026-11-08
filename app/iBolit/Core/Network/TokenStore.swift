import Foundation
import Security

protocol TokenStore: AnyObject {
    var accessToken: String? { get set }
    var refreshToken: String? { get set }
    func clear()
}

final class KeychainTokenStore: TokenStore, @unchecked Sendable {
    private let service = "kz.ibolit.app.tokens"
    private let lock = NSLock()

    var accessToken: String? { get { read("access") } set { write(newValue, "access") } }
    var refreshToken: String? { get { read("refresh") } set { write(newValue, "refresh") } }
    func clear() { accessToken = nil; refreshToken = nil }

    private func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key]
    }
    private func read(_ key: String) -> String? {
        lock.lock(); defer { lock.unlock() }
        var q = query(key); q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }
    private func write(_ value: String?, _ key: String) {
        lock.lock(); defer { lock.unlock() }
        SecItemDelete(query(key) as CFDictionary)
        guard let value, let data = value.data(using: .utf8) else { return }
        var q = query(key); q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(q as CFDictionary, nil)
    }
}
