# FreeCompute product site

A static Astro site with a landing page and a current V1 setup guide. All content
is rendered as HTML; small native browser scripts add screenshot tabs, a dialog,
and copy buttons. The CLI, GUI experiments, private config and Kaggle session are
independent of this site. No analytics, third-party embeds or remote font requests
are included. Fonts are self-hosted IBM Plex Sans and Mono (OFL).

## Run locally

Use Node **22.12+** from this directory:

```powershell
npm ci
npm run dev
```

Open the address printed by Astro (normally `http://127.0.0.1:4321`).

```powershell
npm run build
npm run preview
```

`dist/` is the complete static output. No application server, Python process,
API key or remote GPU is needed to view the site. Nothing is deployed by these
commands.

## Verify

```powershell
npx playwright install chromium
npm run build
npm test
```

The suite checks desktop/mobile layout, real images, screenshot keyboard controls,
dialog focus, clipboard success/refusal, reduced motion, automated WCAG A/AA rules,
guide/downloads, and the page with JavaScript disabled. It serves the production
build on loopback port 4321, reusing the local preview when present. A manual screen-reader audit remains separate from
automated accessibility checks.

From the repository root, retain the required backend check:

```powershell
python -m unittest discover -s tests/unit -p "test_*.py"
```

## Design decisions and evidence

- Public, static product page. Developer desktop use; discovery must also work on
  a small phone over 4G. No user analytics or research statistics were assumed.
- Quiet slate/blue palette, CSS color/spacing tokens, fluid typography, thin
  dividers, subtle static grid/grain, small radii and short hover transitions.
- WCAG 2.2 AA is the implementation target. The site maintainer owns future
  content accessibility; keyboard, contrast and automated checks are performed
  during implementation. Screenshots also have descriptive alt text/captions.
- Targets, not promises: LCP <= 1.2 s for the static profile, INP <= 200 ms,
  CLS <= 0.1, under 30 KB gzipped page JavaScript, Lighthouse performance >= 95
  and accessibility 100. Lab runs are recorded separately; there is no field p75
  dataset yet.
- Astro was chosen for prerendered HTML, native interactions and build-time image
  optimization. React/Next/Tailwind are not required for this content-only page.
- Product copy is grounded in the current `README.md`, `SECURITY.md`, CLI command
  registry/tool approval code, configuration sample, and live acceptance record.
  Historical live evidence is not a new benchmark. Colab is manual integration;
  full 65,536-token input and live image deployment are not certified.

Skills actually read: `ui-design-system`, `ux-researcher-designer`,
`senior-frontend`, `landing-page-generator`, `performance-profiler`,
`zero-hallucination-coder`, `playwright-pro`, and `pw-review`. The user's visual and
evidence requirements override generic gradients, testimonial/pricing templates,
and unnecessary staged confirmation rituals in those skills.

## Real product images

`src/assets/` contains byte-identical copies of these user-supplied screenshots:

| Asset | Original capture | What it demonstrates |
| --- | --- | --- |
| `coding.png` | `Screenshot 2026-10-04 102535.png` | Java code returned in the real CLI |
| `inspection.png` | `Screenshot 2026-10-04 103111.png` | File inspection and a proposed test command; permission pending |
| `research.png` | `Screenshot 2026-10-04 102816.png` | A real `search_web` event; answer not independently fact-checked |
| `status.png` | `Screenshot 2026-10-04 103137.png` | Observed GPU data and explicit unknown metrics |

No generated screenshot, reconstructed terminal UI, staged pass or synthetic GPU
output is included. The command-palette capture was omitted because it contains a
personal absolute workspace path. The output-only capture was redundant; its
session timing is not promoted as a benchmark. The short session reference in
the inspection/research captures is an opaque local history label, not a key or
authentication token. No live tunnel URL or credential is visible in these assets.
Astro generates responsive WebP delivery images; the PNG originals remain unchanged
for full-size inspection. The Linux desktop reference informed the palette only.

## Source preview downloads

GitHub's default branch was older than this V1 checkout when inspected.
`scripts/prepare-downloads.mjs` prepares real, clearly labeled beta source assets
before dev/check/build, using **committed HEAD** and an explicit tracked-path
allowlist. This includes the Python CLI, current notebooks, skills, tests and
knowledgebase. Private `.env`, `config.yaml`, state, GUI experiments, site assets,
models and untracked files are excluded. No Git state is changed.

The source ZIP, unchanged canonical notebook, SHA256 checksums and provenance JSON
are generated into ignored `public/downloads/`; metadata goes into ignored
`src/data/downloads.json`. Build from a full FreeCompute Git checkout. The guide
instructs users to install that source snapshot rather than assuming GitHub main
contains this V1 CLI. Inspect any backend source changes before rebuilding this
public bundle. These are preview artifacts, not a published release/signature.

## Hosting later

Serve `dist/` from a static host. When the public URL is chosen, set `SITE_URL` for
canonical/Open Graph URLs. Set `BASE_PATH` (for example `/FreeCompute/`) if the
host serves a subpath, then rebuild. Neither a domain nor a deployment was assumed.
Use HTTPS on the host. GPU-worker credentials never belong in site environment
variables or browser JavaScript.
