# Screenshots — capture guide

This is a DevSecOps/infra project, so the evidence is the **pipeline**, not a web UI.
Grab two screenshots from GitHub and drop them here with these exact filenames (the main
README references them):

| Filename | What to capture | Where |
|---|---|---|
| `01-pr-blocked.png` | **The money shot** — the bad PR blocked: gitleaks + trivy red, checks failing | https://github.com/Abheenash/secure-container-pipeline/pull/1 → **Checks** tab (or the run below) |
| `02-pipeline-green.png` | The pipeline passing on `main` — all three gates green | the green run link below |

**Direct run links:**
- Blocked (bad PR): https://github.com/Abheenash/secure-container-pipeline/actions/runs/28985635630
- Green (main): https://github.com/Abheenash/secure-container-pipeline/actions/runs/28985555459

**Capture (macOS):** `Cmd+Shift+4`, drag over the browser window. Save/rename into this
folder, then:

```bash
git add docs/screenshots/*.png && git commit -m "docs: add pipeline screenshots" && git push
```

Once pushed, they render in the main README's Screenshots section.

**Tip:** for `01-pr-blocked.png`, the clearest single frame is the PR's **Checks** tab
showing the red ✗ on "gitleaks (secrets)" and "trivy (image + deps)" — that's the
pipeline stopping a secret, in one image.
