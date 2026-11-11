#!/usr/bin/env python3
"""Werewolf agent (heuristic, no model calls) for make.fun werewolf-agent-01.

Plays 30 games via the env at MAKEFUN_ENV_URL. Strategy:
- Werewolf: coordinate kills with partner (agree on partner's pick); kill vocal
  accusers / likely seer first. Day: deflect, accuse a villager, bandwagon the
  most-accused villager; never vote or accuse partner.
- Seer: inspect the most suspicious uninspected seat; when a wolf is found,
  push the village to exile them.
- Doctor: protect the most at-risk villager (vocal accuser / seer-like speaker),
  never the same seat two nights running, never self.
- Villager: vote the most suspicious seat by voting/accusation record.
Suspicion is tracked from the public log: voting to exile a revealed villager,
defending a revealed wolf, and being accused all raise it; voting out a revealed
wolf lowers it. All choices are deterministic functions of the view + trial seed.
"""
import hashlib, json, os, sys, urllib.request, urllib.error

ENV_URL = os.environ.get("MAKEFUN_ENV_URL", "").rstrip("/")
SEED = os.environ.get("MAKEFUN_TRIAL_SEED", "werewolf")

def rng_for(game, label):
    h = hashlib.sha256(f"{SEED}|{game}|{label}".encode()).digest()
    return int.from_bytes(h[:8], "big")

def post(path, body):
    req = urllib.request.Request(ENV_URL + path,
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return {"_error": e.code, "_body": json.loads(e.read().decode())}
        except Exception:
            return {"_error": e.code}

def alive_players(view):
    return [p for p in view.get("players", []) if p.get("alive")]

def revealed(view):
    """seat -> role for revealed (dead) players."""
    out = {}
    for p in view.get("players", []):
        if not p.get("alive") and p.get("role"):
            out[p["seat"]] = p["role"]
    return out

def suspicion(view):
    """Suspicion score per seat, from the public log."""
    rev = revealed(view)
    score = {}
    log = view.get("log", []) or []
    # who accused whom in speeches (simple keyword scan)
    names = {p["seat"]: p["name"] for p in view.get("players", [])}
    for e in log:
        k = e.get("kind")
        if k == "vote":
            tgt = e.get("target")
            if tgt is not None and tgt in rev:
                if rev[tgt] == "werewolf":
                    score[e["seat"]] = score.get(e["seat"], 0) - 3  # voted out a wolf: trust
                elif rev[tgt] in ("villager", "seer", "doctor"):
                    score[e["seat"]] = score.get(e["seat"], 0) + 2  # voted out a villager: suspicious
        elif k == "speech":
            text = (e.get("text") or "").lower()
            for seat, name in names.items():
                if name.lower() in text and ("wolf" in text or "suspicious" in text or "sus" in text or "kill" in text):
                    score[seat] = score.get(seat, 0) + 1
    # dead wolves' voters already handled; players who never voted are neutral
    return score

def pick_lowest(score, candidates, game, label, prefer_high=True):
    """Pick from candidates by suspicion (high first if prefer_high), ties by seeded order."""
    if not candidates:
        return None
    def key(s):
        return (-score.get(s, 0) if prefer_high else score.get(s, 0), rng_for(game, f"{label}:{s}") % 1000)
    return sorted(candidates, key=key)[0]

def decide(game, decision, options, max_chars, view):
    you = view.get("you", {})
    role = you.get("role")
    me = you.get("seat")
    partner = (you.get("partner") or {}).get("seat")
    alive = [p["seat"] for p in alive_players(view) if p["seat"] != me]
    sc = suspicion(view)
    rev = revealed(view)

    if decision == "kill":
        # coordinate: if partner already named a target tonight, agree with it
        wv = view.get("wolfVotes") or []
        night = view.get("day")
        for v in wv:
            if v.get("night") == night and v.get("seat") == partner and v.get("target"):
                return {"target": v["target"]}
        # else target the most suspicious (vocal accuser / likely seer) non-wolf
        cands = [s for s in alive if s != partner]
        return {"target": pick_lowest(sc, cands, game, "kill", prefer_high=True)}

    if decision == "protect":
        last = (view.get("lastProtect") or {}).get("seat")
        cands = [s for s in alive if s != last]
        # protect the most vocal / most accused villager (likely seer or target)
        return {"target": pick_lowest(sc, cands, game, "protect", prefer_high=True)}

    if decision == "inspect":
        done = {(r.get("seat")) for r in (view.get("seerResults") or [])}
        cands = [s for s in alive if s not in done]
        return {"target": pick_lowest(sc, cands, game, "inspect", prefer_high=True)}

    if decision == "vote":
        cands = [s for s in (options or alive) if s != partner]
        if not cands:
            return {"target": None}
        # as seer, if I know a wolf, vote them
        if role == "seer":
            for r in (view.get("seerResults") or []):
                if r.get("werewolf") and r.get("seat") in cands:
                    return {"target": r["seat"]}
        return {"target": pick_lowest(sc, cands, game, "vote", prefer_high=True)}

    if decision == "speak":
        # seer with a known wolf: push to exile them
        if role == "seer":
            for r in (view.get("seerResults") or []):
                if r.get("werewolf"):
                    return {"text": f"I checked seat {r['seat']} last night. They are a werewolf. We should vote them out today."[:max_chars]}
        # werewolf: accuse the most suspicious villager, deflect from partner
        if role == "werewolf":
            cands = [s for s in alive if s != partner]
            tgt = pick_lowest(sc, cands, game, "accuse", prefer_high=True)
            if tgt is not None:
                lines = [
                    f"Seat {tgt} has been acting strange. I think we should look at them today.",
                    f"I am not convinced by seat {tgt}. Their votes do not add up.",
                    f"Seat {tgt} keeps dodging questions. Worth a closer look.",
                ]
                return {"text": lines[rng_for(game, f"speak:{view.get('day')}") % len(lines)][:max_chars]}
            return {"pass": True}
        # villager/doctor: share the most suspicious seat
        cands = [s for s in alive]
        tgt = pick_lowest(sc, cands, game, "accuse", prefer_high=True)
        if tgt is not None and sc.get(tgt, 0) >= 2:
            return {"text": f"Seat {tgt} looks the most suspicious to me from the votes so far. I would vote them."[:max_chars]}
        return {"pass": True}

    return {"target": None}

def main():
    if not ENV_URL:
        print("MAKEFUN_ENV_URL not set", file=sys.stderr); return 1
    while True:
        obs = post("/observe", {})
        if obs.get("done"):
            print("trial done"); return 0
        pending = obs.get("pending") or []
        if not pending:
            # /observe holds up to 20s when nothing waits; loop again
            continue
        for p in pending:
            game = p["game"]; dec = p["decision"]
            ans = decide(game, dec, p.get("options"), p.get("max_chars") or 500, p.get("view") or {})
            body = {"game": game, "decision": dec}
            body.update(ans)
            r = post("/act", body)
            if r.get("_error"):
                # retry once with a safe fallback
                fb = {"game": game, "decision": dec}
                if dec == "speak":
                    fb["pass"] = True
                else:
                    fb["target"] = None
                post("/act", fb)
    return 0

if __name__ == "__main__":
    sys.exit(main())
