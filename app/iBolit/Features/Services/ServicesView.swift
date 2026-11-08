import SwiftUI

struct ServicesView: View {
    @StateObject var viewModel: ServicesViewModel
    let isRoot: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if isRoot { BrandHeader(onBell: viewModel.openNotifications) }
                VStack(alignment: .leading, spacing: 4) {
                    Text(viewModel.title).font(.largeTitle1).foregroundStyle(Theme.textPrimary)
                    if isRoot { Text("Explore services in Almaty").foregroundStyle(Theme.textSecondary) }
                }
                HStack {
                    Image(systemName: "magnifyingglass").foregroundStyle(Theme.textSecondary)
                    TextField("Search services or specialists", text: $viewModel.search)
                    Image(systemName: "slider.horizontal.3").foregroundStyle(Theme.textSecondary)
                }
                .padding(14).background(.white, in: RoundedRectangle(cornerRadius: 14))

                if isRoot && viewModel.search.isEmpty {
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible())], spacing: 12) {
                        ForEach(viewModel.categories) { cat in
                            Button { viewModel.open(cat) } label: {
                                VStack(alignment: .leading, spacing: 18) {
                                    Image(systemName: cat.icon).foregroundStyle(cat.isEmergency ? Theme.emergency : Theme.primary)
                                    Text(cat.name).font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.textPrimary)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading).padding(16)
                                .card(fill: cat.isEmergency ? Theme.emergencyTint : Theme.card)
                            }.buttonStyle(.plain)
                        }
                    }
                }

                SectionHeader(title: viewModel.sectionTitle)
                StateView(state: viewModel.services, retry: { Task { await viewModel.reload() } }) { items in
                    if items.isEmpty {
                        Text("No services found").foregroundStyle(Theme.textSecondary).frame(maxWidth: .infinity).padding()
                    }
                    ForEach(items) { item in serviceCard(item) }
                }
            }
            .padding(.horizontal, 16).padding(.bottom, 24)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationBarHidden(isRoot)
        .navigationBarTitleDisplayMode(.inline)
        .task { await viewModel.load() }
    }

    private func serviceCard(_ s: ServiceItem) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(s.name).font(.system(size: 20, weight: .bold)).foregroundStyle(Theme.textPrimary)
            Text(s.summary).font(.bodySecondary).foregroundStyle(Theme.textSecondary)
            HStack {
                Text(s.priceText).font(.system(size: 18, weight: .bold))
                Spacer()
                if let m = s.durationMinutes { Chip(text: "\(m) min") }
            }
            if !s.availabilityText.isEmpty { Text(s.availabilityText).font(.bodySecondary).foregroundStyle(Theme.textSecondary) }
            PrimaryButton(title: "Book") { viewModel.book(s) }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).card()
    }
}
