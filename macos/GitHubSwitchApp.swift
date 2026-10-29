import AppKit
import SwiftUI

struct Account: Identifiable, Decodable, Sendable, Hashable {
    var id: String { keyword }
    let keyword: String
    let username: String
    let name: String
    let email: String
    let sshKey: String
    let isDefault: Bool
    let isActive: Bool

    enum CodingKeys: String, CodingKey {
        case keyword, username, name, email
        case sshKey = "ssh_key"
        case isDefault = "is_default"
        case isActive = "is_active"
    }
}

struct ListResponse: Decodable, Sendable {
    let defaultKeyword: String?
    let active: String?
    let accounts: [Account]

    enum CodingKeys: String, CodingKey {
        case defaultKeyword = "default"
        case active, accounts
    }
}

struct StatusResponse: Decodable, Sendable {
    let activeKeyword: String?
    let defaultKeyword: String?
    let gitName: String
    let gitEmail: String
    let sshKey: String?
    let ghUser: String?
    let ghInvalid: Bool
    let inSync: Bool

    enum CodingKeys: String, CodingKey {
        case activeKeyword = "active_keyword"
        case defaultKeyword = "default_keyword"
        case gitName = "git_name"
        case gitEmail = "git_email"
        case sshKey = "ssh_key"
        case ghUser = "gh_user"
        case ghInvalid = "gh_invalid"
        case inSync = "in_sync"
    }
}

struct SwitchResponse: Decodable, Sendable {
    let keyword: String
    let warnings: [String]
    let sshCheck: String?
    let ghMessage: String?

    enum CodingKeys: String, CodingKey {
        case keyword, warnings
        case sshCheck = "ssh_check"
        case ghMessage = "gh_message"
    }
}

struct AddResponse: Decodable, Sendable {
    let keyword: String
    let username: String
    let message: String
    let publicKey: String?
    let publicKeyPath: String?

    enum CodingKeys: String, CodingKey {
        case keyword, username, message
        case publicKey = "public_key"
        case publicKeyPath = "public_key_path"
    }
}

struct RemoveResponse: Decodable, Sendable {
    let removed: String
    let notes: [String]
}

struct DefaultResponse: Decodable, Sendable {
    let keyword: String
}

struct KeyResponse: Decodable, Sendable {
    let keyword: String
    let username: String
    let publicKey: String
    let publicKeyPath: String

    enum CodingKeys: String, CodingKey {
        case keyword, username
        case publicKey = "public_key"
        case publicKeyPath = "public_key_path"
    }
}

struct KeyPresentation: Identifiable, Equatable {
    let id = UUID()
    let keyword: String
    let username: String
    let publicKey: String
    let path: String
}

struct Banner: Equatable {
    var text: String
    var warning: Bool

    init(text: String, warning: Bool) {
        self.text = text
        self.warning = warning
    }

    init(response: SwitchResponse) {
        var lines = ["\(response.keyword) is the active account."]
        if let message = response.ghMessage, !response.warnings.contains(message) {
            lines.append(message)
        }
        if let ssh = response.sshCheck, !response.warnings.contains(ssh) {
            lines.append(ssh)
        }
        lines.append(contentsOf: response.warnings)
        text = lines.joined(separator: "\n")
        warning = !response.warnings.isEmpty
    }
}

struct EngineError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct Engine: Sendable {
    var python: String
    var script: String

    func json<T: Decodable>(_ arguments: [String], as type: T.Type) throws -> T {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [script] + arguments
        var environment = ProcessInfo.processInfo.environment
        let prefix = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        if let current = environment["PATH"], !current.isEmpty {
            environment["PATH"] = prefix + ":" + current
        } else {
            environment["PATH"] = prefix
        }
        process.environment = environment
        let output = Pipe()
        let error = Pipe()
        process.standardOutput = output
        process.standardError = error
        try process.run()
        process.waitUntilExit()
        let stdout = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let stderr = String(data: error.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let trimmed = stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        if let data = trimmed.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let message = object["error"] as? String,
           process.terminationStatus != 0 || (object["ok"] as? Bool) == false {
            throw EngineError(message: message)
        }
        guard process.terminationStatus == 0, let data = trimmed.data(using: .utf8) else {
            let message = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            throw EngineError(message: message.isEmpty ? "GitHub Switch could not complete that action." : message)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw EngineError(message: "Could not read the ghsw response.")
        }
    }
}

enum Paths {
    static let projectScript = "/Users/nipunmadhushan/personalProj/ghsw/ghsw.py"
    static let python = "/opt/homebrew/bin/python3"

    static var script: String {
        guard let url = Bundle.main.url(forResource: "cli", withExtension: "path"),
              let text = try? String(contentsOf: url, encoding: .utf8) else {
            return projectScript
        }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? projectScript : trimmed
    }
}

@MainActor
@Observable
final class AppModel {
    var accounts: [Account] = []
    var selection: String?
    var status: StatusResponse?
    var banner: Banner?
    var busy = false
    var errorMessage: String?
    var showAdd = false
    var pendingRemove: String?
    var keyPresentation: KeyPresentation?
    private var requestID = 0
    let engine = Engine(python: Paths.python, script: Paths.script)

    func refresh() {
        requestID += 1
        let request = requestID
        busy = true
        Task {
            await reload(request: request)
        }
    }

    func useSelected() {
        guard let selection else { return }
        use(selection)
    }

    func use(_ keyword: String) {
        guard !busy else { return }
        busy = true
        banner = nil
        Task {
            do {
                let response = try await runJSON(["use", keyword, "--json"], as: SwitchResponse.self)
                banner = Banner(response: response)
                selection = keyword
                await reload()
            } catch {
                errorMessage = error.localizedDescription
                busy = false
            }
        }
    }

    func makeDefaultSelected() {
        guard let selection else { return }
        makeDefault(selection)
    }

    func makeDefault(_ keyword: String) {
        guard !busy else { return }
        busy = true
        Task {
            do {
                let response = try await runJSON(["default", keyword, "--json"], as: DefaultResponse.self)
                banner = Banner(text: "\(response.keyword) is the default account.", warning: false)
                await reload()
            } catch {
                errorMessage = error.localizedDescription
                busy = false
            }
        }
    }

    func removeSelected() {
        guard let pendingRemove else { return }
        let keyword = pendingRemove
        self.pendingRemove = nil
        remove(keyword)
    }

    func remove(_ keyword: String) {
        guard !busy else { return }
        busy = true
        Task {
            do {
                let response = try await runJSON(["remove", keyword, "--yes", "--json"], as: RemoveResponse.self)
                let notes = response.notes.joined(separator: "\n")
                let text = notes.isEmpty ? "Removed \(response.removed)." : "Removed \(response.removed).\n\(notes)"
                banner = Banner(text: text, warning: false)
                if selection == keyword {
                    selection = nil
                }
                await reload()
            } catch {
                errorMessage = error.localizedDescription
                busy = false
            }
        }
    }

    func addAccount(
        keyword: String,
        username: String,
        name: String,
        email: String,
        sshKey: String,
        generate: Bool
    ) async throws -> AddResponse {
        var args = [
            "add", keyword,
            "--username", username,
            "--name", name,
            "--email", email,
            "--ssh-key", sshKey,
            "--json",
        ]
        if generate {
            args.append("--generate-key")
        }
        return try await runJSON(args, as: AddResponse.self)
    }

    func presentCreatedKey(_ response: AddResponse) {
        if let publicKey = response.publicKey, !publicKey.isEmpty {
            keyPresentation = KeyPresentation(
                keyword: response.keyword,
                username: response.username,
                publicKey: publicKey,
                path: response.publicKeyPath ?? ""
            )
        } else {
            banner = Banner(text: response.message, warning: false)
        }
        refresh()
    }

    func copySelectedKey() {
        copyKey(selection)
    }

    func copyKey(_ keyword: String?) {
        guard let keyword else { return }
        Task {
            do {
                let response = try await runJSON(["key", keyword, "--json"], as: KeyResponse.self)
                keyPresentation = KeyPresentation(
                    keyword: response.keyword,
                    username: response.username,
                    publicKey: response.publicKey,
                    path: response.publicKeyPath
                )
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func reload(request: Int? = nil) async {
        do {
            let list = try await runJSON(["list", "--json"], as: ListResponse.self)
            let current = try await runJSON(["status", "--json"], as: StatusResponse.self)
            if let request, request != requestID {
                return
            }
            accounts = list.accounts
            status = current
            if selection == nil || !accounts.contains(where: { $0.keyword == selection }) {
                selection = current.activeKeyword ?? accounts.first?.keyword
            }
        } catch {
            if request == nil || request == requestID {
                errorMessage = error.localizedDescription
            }
        }
        if request == nil || request == requestID {
            busy = false
        }
    }

    private func runJSON<T: Decodable & Sendable>(_ args: [String], as type: T.Type) async throws -> T {
        let engine = self.engine
        return try await Task.detached {
            try engine.json(args, as: type)
        }.value
    }
}

@main
struct GitHubSwitchApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup("GitHub Switch") {
            ContentView(model: model)
        }
        .defaultSize(width: 780, height: 640)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Add Account") { model.showAdd = true }
                    .keyboardShortcut("n")
                    .disabled(model.busy)
                Button("Refresh") { model.refresh() }
                    .keyboardShortcut("r")
            }
            CommandMenu("Account") {
                Button("Use Selected Account") { model.useSelected() }
                    .keyboardShortcut(.return, modifiers: [.command])
                    .disabled(model.selection == nil || model.busy)
                Button("Set Selected as Default") { model.makeDefaultSelected() }
                    .keyboardShortcut("d")
                    .disabled(model.selection == nil || model.busy)
                Button("Copy Public Key") { model.copySelectedKey() }
                    .disabled(model.selection == nil || model.busy)
                Button("Remove Selected Account") { model.pendingRemove = model.selection }
                    .keyboardShortcut(.delete, modifiers: [.command])
                    .disabled(model.selection == nil || model.busy)
            }
        }
    }
}

struct ContentView: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            if let banner = model.banner {
                Text(banner.text)
                    .font(.callout)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(
                        (banner.warning ? Color.orange : Color.green).opacity(0.16),
                        in: RoundedRectangle(cornerRadius: 8)
                    )
            }
            Group {
                if model.accounts.isEmpty {
                    ContentUnavailableView(
                        "No GitHub accounts",
                        systemImage: "arrow.left.arrow.right",
                        description: Text("Add each GitHub account with a keyword such as work or personal.")
                    )
                } else {
                    List(model.accounts, selection: $model.selection) { account in
                        AccountRow(account: account)
                            .tag(account.keyword)
                            .contextMenu {
                                Button("Use") { model.use(account.keyword) }
                                Button("Set as Default") { model.makeDefault(account.keyword) }
                                Button("Copy Public Key") { model.copyKey(account.keyword) }
                                Divider()
                                Button("Remove") { model.pendingRemove = account.keyword }
                            }
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            if let account = model.accounts.first(where: { $0.keyword == model.selection }) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("\(account.name) · \(account.username)")
                        .font(.subheadline.weight(.semibold))
                    Text(account.email)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(account.sshKey)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }

            HStack {
                Button("Add Account") { model.showAdd = true }
                    .disabled(model.busy)
                Button("Use") { model.useSelected() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.selection == nil || model.busy)
                Button("Set Default") { model.makeDefaultSelected() }
                    .disabled(model.selection == nil || model.busy)
                Button("Copy Public Key") { model.copySelectedKey() }
                    .disabled(model.selection == nil || model.busy)
                Spacer()
                if model.busy {
                    ProgressView().controlSize(.small)
                }
                Button("Remove", role: .destructive) {
                    model.pendingRemove = model.selection
                }
                .disabled(model.selection == nil || model.busy)
            }

            Text("Shortcuts: ⌘N add, ⌘R refresh, ⌘↩ use, ⌘D default, ⌘⌫ remove")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(minWidth: 700, minHeight: 520)
        .onAppear { model.refresh() }
        .sheet(isPresented: $model.showAdd) {
            AddAccountSheet(model: model)
        }
        .sheet(item: $model.keyPresentation) { item in
            KeySheet(item: item)
        }
        .confirmationDialog(
            "Remove \(model.pendingRemove ?? "this account")?",
            isPresented: Binding(
                get: { model.pendingRemove != nil },
                set: { if !$0 { model.pendingRemove = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button("Remove", role: .destructive) { model.removeSelected() }
            Button("Cancel", role: .cancel) { model.pendingRemove = nil }
        } message: {
            Text("This removes the keyword from GitHub Switch. The SSH key file stays on this Mac.")
        }
        .alert(
            "GitHub Switch",
            isPresented: Binding(
                get: { model.errorMessage != nil },
                set: { if !$0 { model.errorMessage = nil } }
            )
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("GitHub Switch")
                    .font(.title2.bold())
                if let status = model.status {
                    Text(commitLine(status))
                    Text(sshLine(status))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(cliLine(status))
                        .font(.caption)
                        .foregroundStyle(status.ghInvalid ? Color.orange : Color.secondary)
                    if status.activeKeyword != nil && !status.inSync {
                        Text("The active keyword does not match the current Git name, email, or SSH key. Use the account again to reapply it.")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text("Active: \(model.status?.activeKeyword ?? "none")")
                Text("Default: \(model.status?.defaultKeyword ?? "none")")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    private func commitLine(_ status: StatusResponse) -> String {
        if status.gitName.isEmpty && status.gitEmail.isEmpty {
            return "Commits: not configured"
        }
        return "Commits: \(status.gitName) <\(status.gitEmail)>"
    }

    private func sshLine(_ status: StatusResponse) -> String {
        "SSH key: \(status.sshKey ?? "not set by GitHub Switch")"
    }

    private func cliLine(_ status: StatusResponse) -> String {
        guard let user = status.ghUser else {
            return "GitHub CLI: not logged in"
        }
        if status.ghInvalid {
            return "GitHub CLI: \(user) — saved token is invalid"
        }
        return "GitHub CLI: \(user)"
    }
}

struct AccountRow: View {
    let account: Account

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(account.keyword)
                    .font(.headline)
                Text("\(account.username) · \(account.email)")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if account.isActive {
                Badge(text: "Active", tint: .blue)
            }
            if account.isDefault {
                Badge(text: "Default", tint: Color.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}

struct Badge: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(tint.opacity(0.15), in: Capsule())
            .foregroundStyle(tint)
    }
}

struct AddAccountSheet: View {
    @Environment(\.dismiss) private var dismiss
    var model: AppModel
    @State private var keyword = ""
    @State private var username = ""
    @State private var name = ""
    @State private var email = ""
    @State private var sshKey = "~/.ssh/id_ed25519_"
    @State private var generate = true
    @State private var saving = false
    @State private var localError: String?

    var body: some View {
        NavigationStack {
            Form {
                TextField("Keyword", text: $keyword, prompt: Text("work or personal"))
                TextField("GitHub username", text: $username)
                TextField("Commit name", text: $name)
                TextField("Commit email", text: $email)
                TextField("SSH private key", text: $sshKey)
                Toggle("Generate the SSH key if it is missing", isOn: $generate)
                if let localError {
                    Text(localError)
                        .foregroundStyle(.red)
                        .font(.callout)
                }
            }
            .navigationTitle("Add Account")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .disabled(saving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Adding…" : "Add") { submit() }
                        .disabled(!canSubmit || saving)
                }
            }
        }
        .frame(width: 520, height: 360)
        .onChange(of: keyword) { _, value in
            if sshKey.hasPrefix("~/.ssh/id_ed25519_") {
                let slug = value.lowercased().filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
                sshKey = "~/.ssh/id_ed25519_\(slug)"
            }
        }
    }

    private var canSubmit: Bool {
        !keyword.trimmingCharacters(in: .whitespaces).isEmpty
            && !username.trimmingCharacters(in: .whitespaces).isEmpty
            && !name.trimmingCharacters(in: .whitespaces).isEmpty
            && !email.trimmingCharacters(in: .whitespaces).isEmpty
            && !sshKey.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private func submit() {
        saving = true
        localError = nil
        let values = (keyword, username, name, email, sshKey, generate)
        Task {
            do {
                let response = try await model.addAccount(
                    keyword: values.0.trimmingCharacters(in: .whitespaces),
                    username: values.1.trimmingCharacters(in: .whitespaces),
                    name: values.2.trimmingCharacters(in: .whitespaces),
                    email: values.3.trimmingCharacters(in: .whitespaces),
                    sshKey: values.4.trimmingCharacters(in: .whitespaces),
                    generate: values.5
                )
                saving = false
                dismiss()
                model.presentCreatedKey(response)
            } catch {
                localError = error.localizedDescription
                saving = false
            }
        }
    }
}

struct KeySheet: View {
    let item: KeyPresentation
    @Environment(\.dismiss) private var dismiss
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Add this key to \(item.username)")
                .font(.title2.bold())
            Text("Open GitHub → Settings → SSH and GPG keys, then add the public key to that account. Afterward, log the account into GitHub CLI once from Terminal.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            ScrollView {
                Text(item.publicKey)
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(minHeight: 80, maxHeight: 120)
            Text("gh auth login --hostname github.com --git-protocol ssh --skip-ssh-key")
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
            if !item.path.isEmpty {
                Text(item.path)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            HStack {
                Button(copied ? "Copied" : "Copy Key") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(item.publicKey, forType: .string)
                    copied = true
                }
                Button("Open GitHub Settings") {
                    if let url = URL(string: "https://github.com/settings/keys") {
                        NSWorkspace.shared.open(url)
                    }
                }
                Spacer()
                Button("Done") { dismiss() }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(20)
        .frame(width: 580)
    }
}
