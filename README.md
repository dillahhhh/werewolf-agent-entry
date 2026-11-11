# Werewolf agent (heuristic, no model calls) — make.fun bounty (werewolf-agent-01)

A rule-based Werewolf agent in pure Python (stdlib only). It polls the env's
/observe endpoint and answers every pending decision with deterministic
heuristics from the game's public log:

- Werewolf: coordinate kills with the partner (agree on the partner's pick);
  otherwise kill the most suspicious villager. Day: deflect, accuse a
  villager, bandwagon the most-accused villager; never vote or accuse partner.
- Seer: inspect the most suspicious uninspected seat; when a wolf is found,
  push the village to exile them.
- Doctor: protect the most at-risk villager, never the same seat twice running.
- Villager: vote the most suspicious seat by voting/accusation record.

Suspicion is scored from the log: voting to exile a revealed villager and
being accused raise it; voting out a revealed wolf lowers it. All choices are
deterministic functions of the view + MAKEFUN_TRIAL_SEED (no clock, no model
calls, so the trial replays identically).
