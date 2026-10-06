# Hardwood Tickets build: START HERE (resume guide)

You are the Implementation Agent continuing Noel's "Hardwood Tickets" frontend build. Read these, in order:

1. `design/hardwood/STATE.md`: where the build is right now and the exact next steps (Checkpoint D).
2. `design/hardwood/RUNBOOK.md`: how to run, test, screenshot, commit, push and deploy a preview.
3. `design/hardwood/ARCHITECTURE.md`: the file map and module contracts (who calls what).
4. `design/hardwood/DECISIONS.md`: spec conflicts and how they were resolved. Don't re-litigate them.
5. Only when you need a detail: the handoff spec at `C:\Users\noel9\Desktop\nba-predictor\handoff\`
   (untracked on main, read-only). Its README "Designer rulings" override everything else.

## The job (one paragraph)
Build two static pages (Tonight `/`, The model `/model`) as vanilla HTML/CSS/ES modules in `public/`, per the
handoff. No frameworks, no build step, no CDN. The CSP is strict: no inline script or style and no `style=""` attributes;
use `el.style.setProperty`. Develop against sample mode (`?sample=1`, `public/sample/*.json`). Keep
`tests/contract_shapes.py` and `scripts/build_sample_data.py` in sync with API fields. Escape all API text.
`/legacy` must keep working. One colorway, and reduced motion is honoured everywhere.

## Hard rules from Noel (ask him before any of these)
- Never commit to, merge into or push `main`. Never `vercel deploy --prod`. Never write to the live Supabase project or apply
  migrations. Never print `.env`.
- Work happens on branch `hardwood-build` in the worktree `C:\Users\noel9\Desktop\nba-predictor.worktrees\hardwood-build`.
  Noel approved pushing this branch and creating PREVIEW deployments from it.
- Stop at each checkpoint (A, B, C, D) and report briefly. Speed and token use matter: lean subagent briefs,
  check only what changed, run the full Playwright suite once per checkpoint with a timeout.
- Keep these docs current as you go (Noel's request), so a fresh agent can resume.

## How Noel likes reports
Short. What changed, where to look (preview link and screenshots), and the open questions. Plain, specific wording.
