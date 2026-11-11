# Transcript — werewolf-agent-01 entry build (Muse agent, side chat)

Agent: Muse (Asep), working for user Dillah (handle @0xnenen on make.fun).
Task: build an entry for make.fun bounty werewolf-agent-01 — "Build the best Werewolf agent".
Date: 2026-11-11 (WIB). Deadline 2026-11-11T19:00:00Z (02:00 WIB).

## Turn 1 — Read the kit and rules
- Downloaded kit from https://make.fun/c/werewolf-agent-01/kit, unpacked to ~/workspace/makefun/werewolf-agent-01-kit/.
- Read RULES.txt: 8 players (2 werewolves, 1 seer, 1 doctor, 4 villagers); 30 games per trial (15 as werewolf, 5 seer, 5 doctor, 5 villager); house players are claude-haiku-5-5 at effort low. Agent talks to the env via POST /observe and POST /act at MAKEFUN_ENV_URL. Model calls are optional and need the entrant's own API key; this entry uses NO model calls — pure heuristics, so it plays on its own code. Score: 1000 * (wolf win rate + village win rate) / 2. A prize needs a mean score above the house baseline (claude-opus-5-5, plain, no strategy). Trials replay, so every choice must be a deterministic function of the view + MAKEFUN_TRIAL_SEED (no clock, no unseeded randomness).
- Read starter/main.ts (house baseline) and the practice trial input (practice/trial-0/input/env/table.json, prompt.txt) to learn the exact view shape: view {day, phase, you {seat, name, role, alive, partner}, players [{seat, name, alive, role (null until revealed)}], seerResults, lastProtect, wolfVotes, log, outcome}; log kinds: night, dawn {died, role}, debate {order}, speech {seat, round, text}, pass, voting {order}, vote {seat, target}, exile {seat, role, tally}, end.

## Turn 2 — Design the heuristics
- Suspicion scoring from the public log: +2 when a seat votes to exile a revealed villager; -3 when a seat votes to exile a revealed wolf; +1 when a seat is accused in a speech (name + "wolf"/"suspicious"/"sus"/"kill").
- Werewolf kill: coordinate — if the partner already named a target tonight (wolfVotes), agree with it so the kill happens; otherwise kill the most suspicious living non-wolf. Never target the partner.
- Werewolf speak: accuse the most suspicious villager with a short natural line; deflect from the partner.
- Werewolf vote: bandwagon the most suspicious villager; never vote the partner.
- Seer inspect: the most suspicious uninspected seat. Seer speak: when a wolf is found, push the village to exile them.
- Doctor protect: the most at-risk villager (most suspicious/vocal), never the same seat two nights running, never self.
- Villager speak/vote: share and vote the most suspicious seat once its score reaches 2.
- Tie-breaking: seeded by SHA-256 of (MAKEFUN_TRIAL_SEED, game, label) — deterministic, replay-safe.

## Turn 3 — Write main.py (first version)
- Wrote ~/workspace/makefun/werewolf-entry/main.py (179 lines, Python 3.13 stdlib only: hashlib, json, os, sys, urllib).
- Structure: post() helper (POST JSON to env), suspicion(view), pick_lowest(), decide(game, decision, options, max_chars, view) handling kill/protect/inspect/vote/speak, and main() loop: POST /observe, answer every pending decision with POST /act (one retry with a safe fallback — pass/abstain — on refusal), exit when done is true.
- Syntax check: python3 -m py_compile main.py — OK.
- Mock test 1 (inconsistent mock, all players alive): kill/vote/speak/seer paths returned sensible shapes. Noticed the mock was wrong (dead players must have alive False), so re-tested with a correct mock.
- Mock test 2 (seat 4 dead villager, seat 7 dead werewolf; seat 5 voted out the villager, seat 2 voted out the wolf): suspicion {5: 2, 2: -3}; kill -> seat 5; vote -> seat 5; kill with partner's vote on seat 2 -> agrees on seat 2. All correct.

## Turn 4 — Revise main.py (second write)
- Found a staleness bug by reasoning: the seer speak pushed a found wolf even after that wolf was already dead, which is useless. Fixed: seer speak now only pushes a found wolf while that seat is still alive (checks alive_seats).
- Re-checked syntax (py_compile OK) and committed as a second write to main.py.

## Turn 5 — Publish
- Repo dir: ~/workspace/makefun/werewolf-entry/; files: main.py, README.md, LICENSE (MIT, from kit starter), .makefun/owner.json (claim file naming the user's Phantom wallet DFCtzctdpp5LYq324fCboMBbqQuwLB9EBKNv6eRYM1AA).
- Created public GitHub repo dillahhhh/werewolf-agent-entry via api.github.com; pushed main; HEAD 53cc81e05a2fbf7daff194ffe0bb120f6e23f03e.

This transcript was written by the agent that performed the work above, in the same session.
