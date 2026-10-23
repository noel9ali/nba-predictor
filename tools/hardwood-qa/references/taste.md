# Noel's taste, for judging what the checks cannot

Source: project docs `agent-memory/noel-design-taste.md` and `design-session-decisions.md`. Read those if anything here is unclear.

## Look
- One strong metaphor per page (the hardwood ticket stub), one colorway, generous spacing.
- Real numbers only. Nothing on the page may be invented, rounded up to look better, or left over from sample data.
- No default-template look: no gradient blobs, no icon-in-circle feature rows, no three equal cards for the sake of three.

## Words
- Short, plain, specific. Say what the number is and what it did.
- No machine-sounding lines. Rewrite on sight: "dive into", "unlock", "seamless", "at its core", "it's worth noting", "whether you're…", "not just X, but Y".
- Spaced em dashes go. Use a comma, a colon or a full stop.
- The word "genuinely" never appears, on the page or in anything written for Noel.
- Records and scores take an en dash (4–1). Seasons take an en dash (2026–27).

## Motion
- Animate story beats only: a bet settling, a result landing, a chapter arriving. Not every card.
- Each reveal finishes inside 1.2 seconds. Stagger is capped; nothing waits behind a long queue.
- Short scroll distances. Nothing pins the page for more than about one screen.
- With reduced motion on, show the end state at once. No fades, no drawing, no counting up.
- Nothing may push the layout after first paint.

## When a check and the eye disagree
Look at the screenshot in `qa-out/shots`. If the page looks right, add `qa-ok` to the source line (for lint) or list it in `baseline.json` (for runtime) with a reason in the commit message.
