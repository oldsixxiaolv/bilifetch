# AGENTS.md

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues (`oldsixxiaolv/bilifetch`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five canonical triage labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`GLOSSARY.md` at the repo root and ADRs in `docs/adr/`). See `docs/agents/domain.md`.

## Git remotes & push rule

The canonical GitHub remote for this workspace is `origin` -> `oldsixxiaolv/bilifetch` (`git@github.com:oldsixxiaolv/bilifetch.git`). Before running any `git push`, always state the exact target remote, `<owner>/<repo>`, and branch to the user first.
