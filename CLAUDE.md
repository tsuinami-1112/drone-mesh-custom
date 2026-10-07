# Drone Sentinel

Working notes for the web flasher (`flasher/`) and its CI (`.github/`).
These came out of a security audit; keep them true when changing either.

- **No secrets, by design.** The site is static and the workflow runs on
  `github.token` with job-scoped permissions only. Don't add a PAT, an API
  key or a `secrets.*` reference without a reason that can't be met otherwise.
- **The page's Content-Security-Policy allows scripts from the site itself
  only.** No inline `<script>` and no CDN `<script src=...>` in
  `flasher/index.html`; page logic goes in `flasher/release.js` or another
  file that `build_site.py` copies into the site.
- **esp-web-tools is vendored at build time** by `flasher/build_site.py`,
  pinned by version and tarball SHA-256. Bump both constants together and
  preview the page. Never load it from unpkg or another CDN again.
- **Actions are pinned to full commit SHAs** with a `# vX.Y.Z` comment.
  Dependabot bumps them; give any new action the same treatment.
- **Workflow inputs reach shell steps through `env:`**, never as
  `${{ inputs.* }}` inside a `run:` script.
- **Releases carry `SHA256SUMS` and a build provenance attestation.** Keep
  both when touching the publish job.
