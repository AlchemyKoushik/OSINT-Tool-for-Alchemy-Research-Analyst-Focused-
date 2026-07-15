# Shareable Client Install

## What this flow does

- Keeps the source repo private.
- Builds a zip bundle for Windows installation.
- Uses a small hosted `install.ps1` Release asset as the one-line client entry point.
- Lets you host the bundle anywhere reachable by HTTPS.
- Lets you fetch `backend/.env` from a separate secret URL at install time.
- Installs the app into a hidden `%LOCALAPPDATA%\AlchemyIndustryResearchTool` folder.
- Restricts the installed client UI to `Trends` and `Competitive Landscape (CL)` only.
- Creates a desktop shortcut and Start menu shortcut that open a 2-option TUI:
  - `1. Start the Industry Research Tool`
  - `2. Remove the Tool from Your Device`
- Adds a direct uninstall launcher at `%LOCALAPPDATA%\AlchemyIndustryResearchTool\Uninstall Alchemy Industry Research Tool.bat`.

## Important security truth

This installer can hide the folder and keep secrets out of GitHub, but if the client runs the app locally then:

- the machine still needs the runtime secrets at install/runtime,
- a determined machine owner can inspect a Python-based local install,
- true "unreadable source" requires shipping a compiled artifact instead of raw Python source.

If you want stronger code hiding, the next step is a compiled Windows build pipeline rather than a source bundle.

## Build the bundle

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\shareable_client\build_bundle.ps1
```

Current successful local output:

- folder: `E:\Koushik's Developer Side\Failsafe OSINT Tool\alchemy-shareable-client-build`
- zip: `E:\Koushik's Developer Side\Failsafe OSINT Tool\alchemy-shareable-client-build.zip`

To embed the current `backend/.env` directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\shareable_client\build_bundle.ps1 -IncludeSecrets
```

## Recommended delivery setup

Prefer:

- private GitHub repo for source,
- a GitHub Release asset named `install.ps1` for the one-line client command,
- `bootstrap_install.ps1` hosted on an HTTPS URL you control,
- the built zip hosted on an HTTPS URL you control,
- a separate HTTPS endpoint that returns the `.env` content only for a short-lived install token.
- no Administrator rights required for the normal client install path.

## One-line client command

This is the command format you will share with clients:

```powershell
irm "https://github.com/<owner>/<repo>/releases/download/<tag>/install.ps1" | iex
```

That hosted `install.ps1` should:

- download `bootstrap_install.ps1`,
- pass through `BundleUrl`, `EnvUrl`, `EnvBearerToken`, and `ExpectedSha256`,
- let `bootstrap_install.ps1` verify or install Python before downloading the bundle,
- keep the install per-user so it can complete on locked-down Windows machines.

## Generate the command automatically

Use the helper script after you upload the files:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\shareable_client\new_client_install_command.ps1 `
  -BootstrapUrl "https://your-host.example.com/bootstrap_install.ps1" `
  -BundleUrl "https://your-host.example.com/alchemy-shareable-client-build.zip" `
  -EnvUrl "https://your-secrets.example.com/client-env" `
  -EnvBearerToken "ONE_TIME_INSTALL_TOKEN" `
  -ExpectedSha256 "PUT_BUNDLE_SHA256_HERE" `
  -InstallScriptUrl "https://github.com/<owner>/<repo>/releases/download/<tag>/install.ps1" `
  -OutputInstallScriptPath ".\shareable_client\dist\install.ps1"
```

The helper prints:

- the final hosted `install.ps1` content to upload as a Release asset,
- the short client command: `irm "<GitHub Release URL>/install.ps1" | iex`

## Notes

- If you point `REDIS_URL` in `.env` to your hosted Redis, the client machine does not need a local Redis install.
- `R2` values can remain in `.env` and be fetched from your secret endpoint at install time.
- The installer prefers Python 3.11, accepts another supported 64-bit Python 3.11-3.13 if already present, and falls back to the last python.org Windows x64 installer for Python 3.11 when `winget` is unavailable.
- Python fallback is installed per-user under `%LOCALAPPDATA%\Programs\Python\Python311`, so the client does not need a machine-wide Python install.
