# Windows Standalone Desktop Packaging & ThetaData V3 WebSocket Guide

**Document ID:** `DOC-WINDOWS-DESKTOP-PACKAGING-v1.0`  
**App Target:** `trade_dashboard_app` (Streamlit-First Broker-Grade Trading Command Center)  
**Deployment Modality:** Native Windows 64-bit Executable (`.exe`) via PyInstaller & Microsoft Edge WebView2 (`pywebview`)  
**Real-Time Data Pipeline:** Local ThetaData Terminal v3 Live WebSocket Stream (`ws://127.0.0.1:25503/v3/ws`)  

---

## 1. Architectural Overview

The desktop distribution model packages the Streamlit web engine and all trading engines into a native Windows application while preserving strict engine/UI separation:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TradeDashboardApp.exe                           │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                 Microsoft Edge Chromium WebView2               │   │
│   │               (Native Desktop Hardware-Accelerated UI)         │   │
│   └───────────────────────────────▲────────────────────────────────┘   │
│                                   │ Localhost HTTP / WS                │
│   ┌───────────────────────────────┴────────────────────────────────┐   │
│   │                Embedded Streamlit Engine Daemon                │   │
│   │     (streamlit.web.bootstrap.run on localhost:8501-8599)      │   │
│   └───────────────────────────────▲────────────────────────────────┘   │
│                                   │ Thread-safe Typed Service Layer    │
│   ┌───────────────────────────────┴────────────────────────────────┐   │
│   │                   Core Trading & Data Engines                  │   │
│   │  • trade_data_options.streaming (ThetaData v3 WebSocket client)│   │
│   │  • trade_paper (Simulated portfolio ledger & positions)        │   │
│   │  • trade_agents (LangGraph cyclic DAG & debate stream)         │   │
│   │  • trade_hedge (Delta trimming & gamma neutralizer)            │   │
│   │  • trade_macro (Skip-days & copper:gold macro regime)          │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Technical Characteristics
1. **Zero Browser Tab Clutter:** Renders directly inside a dedicated Windows OS window frame with minimize, maximize, and custom icon controls.
2. **Deterministic Port Binding:** Automatically discovers available ports (`find_free_port()`) on `127.0.0.1` to prevent collisions with existing services.
3. **Clean Lifecycle Management:** Closing the native desktop window immediately terminates the embedded Streamlit daemon process and thread-safe WebSocket connections.
4. **Fail-Soft Fallbacks:** If `pywebview` or the Edge WebView2 runtime is missing (e.g. headless servers), the launcher falls back seamlessly to opening the system default browser.

---

## 2. ThetaData V3 Live WebSocket Pipeline

The real-time options data feed connects to the local Java terminal without passing or handling credentials:

### Pipeline Architecture
* **Client (`trade_data_options.streaming.ThetaDataWebSocketClient`):**
  * Asynchronous client running on a dedicated daemon thread.
  * Connects to `ws://127.0.0.1:25503/v3/ws`.
  * Automatically re-subscribes active contracts across reconnects with exponential backoff.
  * Supports high-fidelity offline simulation mode for local testing without the Java terminal.
* **0DTE Coordinator (`trade_data_options.streaming.ThetaData0DTEStreamingPipeline`):**
  * Subscribes to ATM Call and Put legs for target symbols (`SPX`, `SPY`).
  * Asynchronously matches arriving quotes into `LiveStraddleQuote`.
  * Re-evaluates expected move decay ratio ($decay = \frac{C_t + P_t}{EM_{open}}$) via `trade_data_options.em_decay`.
  * Fires latched callbacks the instant decay drops $\le 0.83$ (the pre-registered 83.0% hypothesis threshold).

---

## 3. Prerequisites & Development Setup

### System Requirements
* Windows 10 (Build 1809+) or Windows 11 64-bit.
* Microsoft Edge WebView2 Runtime (installed by default on Windows 10/11).
* Python 3.11 – 3.13 64-bit.

### Installation
From the root workspace:

```powershell
# Install packaging and UI runtime dependencies
pip install pyinstaller pywebview pythonnet streamlit websockets
```

---

## 4. Running the Desktop App in Development

You can launch the native desktop window directly from source without compiling:

```powershell
# Method 1: Via package CLI flag
python -m trade_dashboard_app --desktop

# Method 2: Via dedicated desktop module
python -m trade_dashboard_app.desktop

# Method 3: Via registered console script
trade-dashboard-app-desktop
```

### Command-Line Arguments
| Argument | Description | Default |
| :--- | :--- | :--- |
| `--port <int>` | Custom port for embedded Streamlit server | Auto-allocated (8501+) |
| `--host <str>` | Host address to bind | `127.0.0.1` |
| `--width <int>` | Initial desktop window width | `1440` |
| `--height <int>` | Initial desktop window height | `900` |
| `--browser` | Force launch in default system browser instead of WebView2 | `False` |

---

## 5. Compiling the Standalone Windows Executable

The project includes an automated build pipeline that verifies test suite integrity before generating the standalone executable.

### One-Click Build Command

```powershell
# Using Python build script
python scripts/build_windows_exe.py

# Or using PowerShell runner
.\scripts\build_windows_exe.ps1
```

### Build Options
* `--clean`: Purges previous PyInstaller build caches and output directories.
* `--skip-tests`: Bypasses pre-build pytest validation (recommended only for rapid iteration).

### Output Artifacts
The compiled application is written to:
```
dist/TradeDashboardApp/
├── TradeDashboardApp.exe     # Standalone native launcher executable
├── _internal/                # Bundled Python runtime, DLLs, Edge WebView2 hooks
└── streamlit/static/         # Embedded frontend HTML/JS/CSS assets
```

---

## 6. PyInstaller Spec Details (`packaging/trade_dashboard_app.spec`)

* **Asset Collection:** Bundles all Streamlit static web assets (`streamlit/static`), font bundles, and `app.py` via `collect_data_files`.
* **Submodule Discovery:** Collects all dynamic internal packages (`trade_dashboard_app`, `trade_data_options`, `trade_paper`, `trade_agents`, `trade_hedge`, `trade_macro`, `trade_risk_premium`).
* **Hidden Imports:** Explicitly declares `webview`, `clr`, `clr_loader`, `pythonnet`, `websockets`, `pyarrow`, `altair`, and `pydeck`.
* **Distribution Mode:** `onedir` distribution is utilized for optimal startup performance and reliable Windows DLL discovery with `pythonnet`.

---

## 7. Windows Code Signing & Distribution (Production Notes)

For production distribution across field devices:
1. **Digital Signing (Authenticode):**
   ```powershell
   signtool sign /f "certs/TradeSuiteCert.pfx" /p "<password>" /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 "dist/TradeDashboardApp/TradeDashboardApp.exe"
   ```
2. **Windows Defender SmartScreen:** Code signing with an EV or standard code-signing certificate prevents Windows Defender untrusted binary warnings when running on clean field tablets.
3. **Packaging into an Installer (Optional):** The `dist/TradeDashboardApp` directory can be packaged into a single setup wizard using Inno Setup or WiX Toolset.

---

## 8. Verification & Test Suite

All desktop components, port finders, and spec integrity checks are covered by automated unit tests:

```powershell
# Run desktop-specific tests
python -m pytest tests/test_dashboard_desktop.py -v

# Run streaming pipeline tests
python -m pytest tests/test_data_options_streaming.py -v

# Run full dashboard test suite
python -m pytest tests/test_dashboard_app.py -v
```
