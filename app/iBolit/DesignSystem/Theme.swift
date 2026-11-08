import SwiftUI

enum Theme {
    static let primary = Color(hex: 0x0B7F6E)
    static let primaryDark = Color(hex: 0x0A6B5D)
    static let background = Color(hex: 0xF4F7F8)
    static let card = Color.white
    static let textPrimary = Color(hex: 0x12262D)
    static let textSecondary = Color(hex: 0x6B7C85)
    static let mint = Color(hex: 0xE0F2EB)
    static let mintStrong = Color(hex: 0xD2EBE2)
    static let emergency = Color(hex: 0xC7424F)
    static let emergencyTint = Color(hex: 0xFDEBEC)
    static let chip = Color(hex: 0xEEF2F3)

    static let radius: CGFloat = 18
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

extension Font {
    static let largeTitle1 = Font.system(size: 28, weight: .bold)
    static let titleSection = Font.system(size: 20, weight: .bold)
    static let cardTitle = Font.system(size: 17, weight: .semibold)
    static let bodySecondary = Font.system(size: 14)
    static let caption1 = Font.system(size: 12, weight: .medium)
}
