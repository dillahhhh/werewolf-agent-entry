# Werewolf agent (heuristic, no model calls) — make.fun bounty (werewolf-agent-01)

A rule-based Werewolf agent in pure Python (stdlib only). It polls the env's
`/observe` endpoint and answers every pending decision with deterministic
heuristics built from the game's public log plus its private record (seer
results, last protection, partner's night votes). No model calls, no wall
clock in any request, no unseeded randomness: every choice is a function of
the view and `MAKEFUN_TRIAL_SEED`, so a trial replays identically.

## How it reads the table

Two scores are maintained from the public log:

- **Suspicion** — voting to exile a revealed villager raises it (+2);
  voting to exile a revealed wolf lowers it sharply (-4, the seat tried to
  kill a wolf); being accused in a speech raises it (+1 each, capped at +3);
  defending a revealed wolf raises it (+2); accusing a revealed villager
  raises it (+1); passing in debate 3+ times raises it (+1, wolves go
  quiet). Names are matched on word boundaries so short names cannot
  false-positive inside other words.
- **Threat** — how dangerous a seat is to the wolves: the negative of
  suspicion (trusted players) plus vocal participation plus correct
  accusations of wolves. The highest-threat seats are the likeliest seer
  and the wolves' best kills — and the doctor's best protects.

## Strategy per role

- **Werewolf.** The two wolves must agree on one kill or nobody dies, so
  the second wolf to vote always agrees with the partner's pick for the
  night. Otherwise it kills the highest-threat living non-wolf — the
  likeliest seer / most trusted villager — but never a seat the village is
  about to exile anyway (suspicion ≥ 5: that kill would be wasted), and
  never the partner. By day it accuses the most suspicious villager with
  varied natural lines, defends the partner when the partner is pushed,
  bandwagons the leading suspect at the vote, and never votes or accuses
  the partner.
- **Seer.** Inspects the most suspicious uninspected seat. A found wolf is
  announced at once, with the evidence (their votes), and voted at once.
  A seer with no wolf found yet does not claim — an early claim paints a
  target on the seer and the wolves kill them.
- **Doctor.** Protects the highest-threat villager (the likeliest seer, or
  the player the wolves most want dead), never the same seat two nights
  running and never themself, as the rules require.
- **Villager.** Votes the most suspicious seat, bandwagoning the plurality
  leader among the suspects so the day actually exiles someone instead of
  tying (a tie exiles nobody). Speaks only with evidence — a vote record
  or an accusation trail — and otherwise passes, because noise helps the
  wolves.

## Robustness

- Every target is checked against the decision's `options` before sending;
  an out-of-options target becomes an abstention instead of a refusal.
- Every statement is cut to `max_chars` (≤ 500 after folding).
- A refused `/act` is retried once with a safe fallback (pass / abstain)
  so a game never stalls on a bad answer.
- A failed `/observe` backs off briefly instead of hammering the env.
- The loop exits only when the env reports `done`, so all 30 games finish.

## Verified

`python3 -m py_compile main.py` passes. Decision paths were mock-tested
against a hand-built view (dead revealed villager + dead revealed wolf,
vote/speech history): suspicion, threat, wolf kill + partner agreement,
seer vote/speak on a found wolf, doctor protect rotation, villager
bandwagon vote, and inspect all return the expected seats.
