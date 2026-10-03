# FreeCompute local GUI

React + TypeScript + Vite client for the existing Python Core. No GPU is needed
for development. This project requires Node 22.12+ and the existing Python
dependencies; tested with Node 24.16.0 on Windows. See the
[Vite prerequisites](https://vite.dev/guide/). From the repository root:

```powershell
npm --prefix apps/gui ci
npm --prefix apps/gui run build
python -m harness.api --demo --open
```

Paste the value from the `local-api-token` file at the path printed by the
service into Connect. It is separate from the Kaggle API key. This demo uses
simulated inference with real, approval-gated tools in an external workspace.
Create a session, choose **Read → edit → test**, send, then review each approval.

For hot reload:

```powershell
python -m harness.api --demo --origin http://127.0.0.1:5173
npm --prefix apps/gui run dev
```

Open `http://127.0.0.1:5173`; connect to `http://127.0.0.1:8741`.

Checks:

```powershell
npm --prefix apps/gui run test
npm --prefix apps/gui run build
npx --prefix apps/gui playwright install chromium
npm --prefix apps/gui run e2e
python -m unittest discover -s tests/unit -p "test_*.py"
```

Browser tests start a separate disposable Core fixture on port 8749 and never
load production `.env`/worker configuration. Screenshots are in the ignored
`test-results` folder. Session persistence/auth/events/approvals and release
limits are documented in [LOCAL_API](../../knowledgebase/LOCAL_API.md) and
[V1_GUI](../../knowledgebase/V1_GUI.md). Tauri/assets packaging remains later work.
