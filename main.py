#!/usr/bin/env python3
"""Werewolf agent (heuristic, no model calls) for make.fun werewolf-agent-01.

Pure Python 3.13, standard library only. Polls the env's /observe endpoint and
answers every pending decision with deterministic heuristics built from the
game's public log plus the agent's private record (seer results, last
protection, partner's night votes). No model calls, no wall clock in any
request, no unseeded randomness: every choice is a function of the view and
MAKEFUN_TRIAL_SEED, so a trial replays byte for byte.

Roles: 15 games as werewolf, 5 seer, 5 doctor, 5 villager per trial, against
seven claude-haiku-5-5 house players. Score is the mean of the wolf win rate
and the village win rate, so the agent must play both sides well.

STRATEGY, in brief
------------------
Suspicion is scored from the public log (see suspicion()): voting to exile a
revealed villager raises it, voting to exile a revealed wolf lowers it
sharply, accusing a seat in speech raises it, and defending a revealed wolf
raises it more. A separate "threat" score measures how dangerous a seat is
to the wolves: players who voted a wolf out, accused a wolf in speech, or
speak up a lot are the seer's likeliest seats and the wolves' best kills.

- Werewolf: the two wolves must agree on one kill or nobody dies, so the
  second wolf to vote always agrees with the partner's pick for the night.
  Otherwise kill the highest-threat living non-wolf (the likeliest seer /
  the most trusted villager) -- never a seat the village is about to exile
  anyway (that kill would be wasted), and never the partner. By day, accuse
  the most suspicious villager, bandwagon the leading suspect at the vote,
  defend the partner when the partner is pushed, and never vote or accuse
  the partner.
- Seer: inspect the most suspicious uninspected seat. A found wolf is
  announced at once, with the evidence (their votes), and voted at once.
  A seer with no wolf found yet does not claim -- an early claim paints a
  target on the seer and the wolves kill them.
- Doctor: protect the highest-threat villager (the likeliest seer, or the
  player the wolves most want dead), never the same seat two nights running
  and never themself (the rules forbid both).
- Villager: vote the most suspicious seat, bandwagoning the plurality leader
  among the suspects so the day actually exiles someone instead of tying.
  Speak only with evidence (a vote record or an accusation trail), else pass:
  noise helps the wolves.

Robustness: every target is checked against the decision's options, every
statement is cut to max_chars, a refused /act is retried once with a safe
fallback (pass / abstain) so a game never stalls on a bad answer, and a
failed /observe backs off briefly instead of hammering a struggling env.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ENV_URL = os.environ.get("MAKEFUN_ENV_URL", "").rstrip("/")
SEED = os.environ.get("MAKEFUN_TRIAL_SEED", "werewolf")

ACCUSE_WORDS = ("wolf", "werewolf", "sus", "suspicious", "kill", "exile",
                "vote out", "lynch")
DEFEND_WORDS = ("trust", "innocent", "not a wolf", "not wolf", "clear",
                "villager", "believe")


def rng_for(game, label):
    """Deterministic seeded integer for (game, label); replay-safe."""
    h = hashlib.sha256(f"{SEED}|{game}|{label}".encode()).digest()
    return int.from_bytes(h[:8], "big")


def post(path, body):
    req = urllib.request.Request(
        ENV_URL + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return {"_error": e.code, "_body": json.loads(e.read().decode())}
        except Exception:
            return {"_error": e.code}
    except Exception:
        return {"_error": "unreachable"}


def alive_players(view):
    return [p for p in view.get("players", []) if p.get("alive")]


def revealed(view):
    """seat -> role for players whose role was revealed by death."""
    out = {}
    for p in view.get("players", []):
        if not p.get("alive") and p.get("role"):
            out[p["seat"]] = p["role"]
    return out


def _name_hit(text, name):
    return re.search(r"\b" + re.escape(name.lower()) + r"\b", text) is not None


def suspicion(view):
    """Suspicion score per seat, from the public log.

    +2  voted to exile a revealed villager / seer / doctor
    -4  voted to exile a revealed wolf (cleared: they tried to kill a wolf)
    +1  accused in a speech (name + an accusation word), capped at +3
    +2  defended a revealed wolf in speech (name + a defence word)
    +1  accused a revealed villager in speech (wrong accusation)
    +1  passed in debate 3+ times (wolves go quiet; small weight)
    """
    rev = revealed(view)
    score = {}
    log = view.get("log", []) or []
    names = {p["seat"]: p["name"] for p in view.get("players", [])}
    accuse_count = {}
    passes = {}
    for e in log:
        kind = e.get("kind")
        if kind == "vote":
            tgt = e.get("target")
            voter = e.get("seat")
            if tgt is not None and tgt in rev:
                if rev[tgt] == "werewolf":
                    score[voter] = score.get(voter, 0) - 4
                else:
                    score[voter] = score.get(voter, 0) + 2
        elif kind == "speech":
            text = (e.get("text") or "").lower()
            for seat, name in names.items():
                if not _name_hit(text, name):
                    continue
                if any(w in text for w in ACCUSE_WORDS):
                    accuse_count[seat] = accuse_count.get(seat, 0) + 1
                    if seat in rev:
                        # accusing a revealed villager was wrong; accusing a
                        # revealed wolf was right
                        score[seat] = score.get(seat, 0) + (1 if rev[seat] != "werewolf" else -1)
                elif any(w in text for w in DEFEND_WORDS) and seat in rev and rev[seat] == "werewolf":
                    score[e["seat"]] = score.get(e["seat"], 0) + 2
        elif kind == "pass":
            passes[e["seat"]] = passes.get(e["seat"], 0) + 1
    for seat, n in accuse_count.items():
        score[seat] = score.get(seat, 0) + min(n, 3)
    for seat, n in passes.items():
        if n >= 3:
            score[seat] = score.get(seat, 0) + 1
    return score


def threat(view, score):
    """How dangerous a seat is to the wolves (likeliest seer / trusted voice).

    Built from the negative of suspicion (trusted players) plus vocal
    participation and correct accusations of wolves.
    """
    rev = revealed(view)
    log = view.get("log", []) or []
    names = {p["seat"]: p["name"] for p in view.get("players", [])}
    value = {}
    for seat in names:
        value[seat] = -score.get(seat, 0)
    for e in log:
        kind = e.get("kind")
        if kind == "speech":
            text = (e.get("text") or "").lower()
            value[e["seat"]] = value.get(e["seat"], 0) + 1  # vocal
            for seat, name in names.items():
                if seat in rev and rev[seat] == "werewolf" and _name_hit(text, name) \
                        and any(w in text for w in ACCUSE_WORDS):
                    value[e["seat"]] = value.get(e["seat"], 0) + 2
        elif kind == "vote":
            tgt = e.get("target")
            if tgt is not None and tgt in rev and rev[tgt] == "werewolf":
                value[e["seat"]] = value.get(e["seat"], 0) + 2
    return value


def todays_votes(view):
    """seat -> votes cast so far today (current day's vote entries)."""
    day = view.get("day")
    tally = {}
    for e in view.get("log", []) or []:
        if e.get("kind") == "vote" and e.get("day") == day and e.get("target") is not None:
            tally[e["target"]] = tally.get(e["target"], 0) + 1
    return tally


def pick_ranked(score, candidates, game, label, prefer_high=True):
    """Best candidate by score (high first, or low first), ties by seed."""
    if not candidates:
        return None
    def key(s):
        base = -score.get(s, 0) if prefer_high else score.get(s, 0)
        return (base, rng_for(game, f"{label}:{s}") % 1000)
    return sorted(candidates, key=key)[0]


def known_wolf(view, cands):
    """A live seat the seer has inspected and found to be a werewolf."""
    for r in (view.get("seerResults") or []):
        if r.get("werewolf") and r.get("seat") in cands:
            return r["seat"]
    return None


def vote_target(view, cands, game, score):
    """Vote: a known wolf first; else bandwagon the plurality leader among
    the suspects (a tie exiles nobody, so piling on the leader matters),
    else the most suspicious seat."""
    wolf = known_wolf(view, cands)
    if wolf is not None:
        return wolf
    tally = todays_votes(view)
    leaders = [s for s in cands if tally.get(s, 0) > 0 and score.get(s, 0) >= 1]
    if leaders:
        return pick_ranked(tally, leaders, game, "bandwagon", prefer_high=True)
    return pick_ranked(score, cands, game, "vote", prefer_high=True)


def decide(game, decision, options, max_chars, view):
    you = view.get("you", {}) or {}
    role = you.get("role")
    me = you.get("seat")
    partner = (you.get("partner") or {}).get("seat")
    alive = [p["seat"] for p in alive_players(view) if p["seat"] != me]
    sc = suspicion(view)
    th = threat(view, sc)

    if decision == "kill":
        # Coordinate: if the partner already named a target tonight, agree
        # -- disagreeing kills nobody. Night n is day n in the view.
        night = view.get("day")
        for v in (view.get("wolfVotes") or []):
            if v.get("night") == night and v.get("seat") == partner and v.get("target"):
                return {"target": v["target"]}
        # Kill the highest-threat living non-wolf, but not a seat the village
        # is about to exile anyway (suspicion >= 5: that kill is wasted).
        cands = [s for s in alive if s != partner and sc.get(s, 0) < 5]
        if not cands:
            cands = [s for s in alive if s != partner]
        return {"target": pick_ranked(th, cands, game, "kill", prefer_high=True)}

    if decision == "protect":
        last = (view.get("lastProtect") or {}).get("seat")
        cands = [s for s in alive if s != last]
        # Protect the villager the wolves most want dead: the likeliest
        # seer / most trusted voice. Never self, never the last protect.
        return {"target": pick_ranked(th, cands, game, "protect", prefer_high=True)}

    if decision == "inspect":
        done = {r.get("seat") for r in (view.get("seerResults") or [])}
        cands = [s for s in alive if s not in done]
        return {"target": pick_ranked(sc, cands, game, "inspect", prefer_high=True)}

    if decision == "vote":
        cands = [s for s in (options or alive) if s != partner]
        if not cands:
            return {"target": None}
        return {"target": vote_target(view, cands, game, sc)}

    if decision == "speak":
        alive_seats = {p["seat"] for p in alive_players(view)}
        # Seer with a live found wolf: announce it with the evidence.
        if role == "seer":
            wolf = known_wolf(view, list(alive_seats))
            if wolf is not None:
                return {"text": (
                    f"I checked seat {wolf} last night and they are a werewolf. "
                    f"Look at their votes -- they pushed villagers out. Vote seat {wolf} today."
                )[:max_chars]}
        # Werewolf: if the partner is being pushed, counter-accuse their
        # accuser; else accuse the most suspicious villager.
        if role == "werewolf":
            cands = [s for s in alive if s != partner]
            tgt = pick_ranked(sc, cands, game, "accuse", prefer_high=True)
            if tgt is None:
                return {"pass": True}
            # Is the partner the top suspect? Then the accuser is the threat.
            if sc.get(partner, 0) >= 3 and sc.get(partner, 0) >= sc.get(tgt, 0):
                lines = [
                    f"Seat {partner} has done nothing wrong. The people pushing them are the ones to watch.",
                    f"I do not buy the case on seat {partner}. It looks like a wolf pushing a villager out.",
                ]
                return {"text": lines[rng_for(game, f"defend:{view.get('day')}") % len(lines)][:max_chars]}
            lines = [
                f"Seat {tgt} has been acting strange all game. I think we should look at them today.",
                f"I am not convinced by seat {tgt}. Their votes do not add up -- they keep pushing villagers.",
                f"Seat {tgt} keeps dodging questions and deflecting. Worth a closer look before we vote.",
                f"Look at seat {tgt}'s voting record. Every exile they pushed was a villager. That is the pattern.",
            ]
            return {"text": lines[rng_for(game, f"speak:{view.get('day')}") % len(lines)][:max_chars]}
        # Villager / doctor: share the top suspect only with real evidence.
        cands = [s for s in alive]
        tgt = pick_ranked(sc, cands, game, "accuse", prefer_high=True)
        if tgt is not None and sc.get(tgt, 0) >= 2:
            tally = todays_votes(view)
            if tally.get(tgt, 0) > 0:
                text = (f"Seat {tgt} already has votes and their record is bad -- "
                        f"they voted villagers out. I would vote seat {tgt}.")
            else:
                text = (f"Seat {tgt} looks the most suspicious to me from the votes so far. "
                        f"I would vote them.")
            return {"text": text[:max_chars]}
        return {"pass": True}

    return {"target": None}


def act_safe(game, decision, answer):
    """Send one /act; on refusal retry once with a safe fallback."""
    body = {"game": game, "decision": decision}
    body.update(answer)
    r = post("/act", body)
    if r.get("_error"):
        fb = {"game": game, "decision": decision}
        if decision == "speak":
            fb["pass"] = True
        else:
            fb["target"] = None
        post("/act", fb)


def main():
    if not ENV_URL:
        print("MAKEFUN_ENV_URL not set", file=sys.stderr)
        return 1
    while True:
        obs = post("/observe", {})
        if obs.get("_error"):
            # Env hiccup: back off briefly instead of hammering it. The
            # sleep is local only -- nothing about it reaches any request,
            # so replay determinism is unaffected.
            time.sleep(2)
            continue
        if obs.get("done"):
            print("trial done")
            return 0
        pending = obs.get("pending") or []
        if not pending:
            continue
        for p in pending:
            game = p["game"]
            dec = p["decision"]
            view = p.get("view") or {}
            options = p.get("options")
            ans = decide(game, dec, options, p.get("max_chars") or 500, view)
            # Never send a target the env did not offer.
            if "target" in ans and ans["target"] is not None and options \
                    and ans["target"] not in options:
                ans = {"target": None}
            act_safe(game, dec, ans)
    return 0


if __name__ == "__main__":
    sys.exit(main())
