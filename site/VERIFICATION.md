# Landing-page verification — 2026-10-04

Verified the production static build locally on Windows, Node 24.16.0, Astro
7.3.5 and TypeScript 6.0.3. No deployment or fresh GPU inference was performed.

## Checks

- `npm run build`: two static pages; zero type errors, warnings or hints.
- `npm test`: **20/20 passed** across desktop and mobile Chromium configurations.
  Viewport checks include 320, 390, 768, 1024, 1440 and 1920 px. Coverage includes
  image loading, keyboard tabs/skip link, dialog focus/Escape, clipboard success
  and refusal, no JavaScript, reduced motion, guide/downloads, and automated WCAG
  A/AA rules (including the wordmark label check).
- `python tests/verify_downloads.py`: hashes match, ZIP/standalone notebook bytes
  match the declared Git snapshot, private paths are excluded, notebook code
  compiles statically and has no captured outputs.
- The source ZIP was extracted and installed in a disposable directory using the
  documented PEP 517 flow. Its real CLI exposes `--remote-url` and `--workspace`.
  Application dependencies came from existing system packages; this was not a
  clean dependency-resolution or real-worker acceptance run.
- Repository `python -m unittest discover -s tests/unit -p "test_*.py"`:
  **289/289 passed** in 103.482 s.
- Repository secret scan: **191 files, zero findings**. Product captures were also
  visually inspected; originals remain byte-identical to the supplied images.
- Desktop/mobile rendered screenshots were inspected. Diagnostic captures are
  under ignored `reports/`; image decoding was confirmed before final captures.

## Performance observations

Lighthouse 13.5.0 against the production build on loopback; default simulated
mobile throttling and the desktop preset, using headless Chromium. These are
single local lab runs of the website, not inference benchmarks or field p75 data.

| Final run | Performance | Accessibility | Best practices | SEO | FCP | LCP | TBT | CLS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mobile | 100 | 100 | 100 | 100 | 1.1 s | 1.7 s | 0 ms | 0 |
| Desktop | 100 | 100 | 100 | 100 | 0.3 s | 0.4 s | 0 ms | 0 |

Initial mobile run: performance 99, FCP 1.4 s, LCP 1.7 s. Primary-font preload
reduced the measured FCP; no improvement in LCP is claimed. The aspirational
1.2 s LCP budget was not met in the mobile lab run. All three JavaScript output
files combined are 1,027 bytes gzipped (one shared 917-byte interaction module
plus tiny page entries), below the 30 KB budget. Raw reports are ignored in
`reports/lighthouse-*-final.json`.

Automated accessibility scores are not a manual screen-reader certification.
Physical-device, Safari/Firefox and field-performance checks remain distinct.

## Product evidence boundaries

The coding image is generated code in a real CLI, not a program-execution receipt.
The inspection image shows a proposed command awaiting permission, not passing
tests. The web image proves tool activity, not the factual accuracy of the sports
answer. Status is a historical observation with explicit unknown fields.
Colab is manual integration; full 65,536-token input and live image deployment
remain unverified. The current Cloudflare Quick Tunnel documentation was checked
and still lists SSE as unsupported; the guide links that primary source.

The downloadable beta source snapshot avoids relying on an older GitHub default
branch. It is prepared locally from tracked source, not a published release.
