import SwiftUI

struct LoginView: View {
    @StateObject var viewModel: AuthViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                BrandHeader(onBell: {}).padding(.bottom, 12)
                Text(viewModel.isSignup ? "Create account" : "Welcome back").font(.largeTitle1)
                Text("A little care goes a long way.").foregroundStyle(Theme.textSecondary)

                if viewModel.isSignup { field("Full name", text: $viewModel.fullName) }
                field("Phone", text: $viewModel.phone, keyboard: .phonePad)
                SecureField("Password", text: $viewModel.password)
                    .padding().background(.white, in: RoundedRectangle(cornerRadius: 14))

                if let e = viewModel.errorMessage { Text(e).font(.bodySecondary).foregroundStyle(Theme.emergency) }

                PrimaryButton(title: viewModel.isSignup ? "Sign up" : "Log in", isLoading: viewModel.isLoading) {
                    Task { await viewModel.submit() }
                }.disabled(!viewModel.canSubmit)

                Button(viewModel.isSignup ? "I already have an account" : "Create an account") { viewModel.isSignup.toggle() }
                    .frame(maxWidth: .infinity)
            }
            .padding(20)
        }
        .background(Theme.background.ignoresSafeArea())
    }

    private func field(_ title: String, text: Binding<String>, keyboard: UIKeyboardType = .default) -> some View {
        TextField(title, text: text).keyboardType(keyboard).textInputAutocapitalization(.never)
            .padding().background(.white, in: RoundedRectangle(cornerRadius: 14))
    }
}
