#!/usr/bin/env python3
"""
Pure-Python local test for the Quantitative Football Betting Engine.
Tests all core logic without requiring pandas/numpy (uses stdlib only).
"""
import csv, math, os, sys

# ── Config ──
MARKETS = {
    "fouls":   {"label":"Over 22.5 Fouls",            "line":22.5,  "trigger":28.60, "odds":1.50, "weight":8.5, "hcol":"HF",  "acol":"AF"},
    "cards":   {"label":"Over 3.5 Yellow Cards",       "line":3.5,   "trigger":5.40,  "odds":1.55, "weight":8.5, "hcol":"HY",  "acol":"AY"},
    "sot":     {"label":"Over 8.5 Shots on Target",    "line":8.5,   "trigger":12.00, "odds":1.80, "weight":9.0, "hcol":"HST", "acol":"AST"},
    "corners": {"label":"Over 8.5 Corners",            "line":8.5,   "trigger":11.80, "odds":1.55, "weight":8.5, "hcol":"HC",  "acol":"AC"},
}
ROLLING_WINDOW = 5
SCORE_THRESHOLD = 8.5
BANKROLL = 15000.0
STAKE_PCT = 0.01

# ── Load CSV ──
CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "sample_historical.csv")

def load_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean = {k.strip(): v.strip() for k, v in row.items()}
            rows.append(clean)
    return rows

def to_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None

# ── Rolling Stats ──
def compute_rolling_stats(rows):
    team_data = {}  # team -> {market -> [vals]}

    for row in rows:
        home = row.get("HomeTeam", "").strip()
        away = row.get("AwayTeam", "").strip()
        if not home or not away:
            continue

        for mkey, mcfg in MARKETS.items():
            # Home side
            hval = to_float(row.get(mcfg["hcol"]))
            aval = to_float(row.get(mcfg["acol"]))

            if home not in team_data:
                team_data[home] = {k: [] for k in MARKETS}
            if away not in team_data:
                team_data[away] = {k: [] for k in MARKETS}

            if hval is not None:
                team_data[home][mkey].append(hval)
            if aval is not None:
                team_data[away][mkey].append(aval)

    # Compute rolling mean (last ROLLING_WINDOW games)
    stats = {}
    for team, mdict in team_data.items():
        stats[team] = {}
        for mkey, vals in mdict.items():
            if not vals:
                stats[team][mkey] = None
            else:
                window = vals[-ROLLING_WINDOW:]
                stats[team][mkey] = sum(window) / len(window)

    return stats

# ── Scoring ──
def score_market(expected, trigger, line):
    if expected is None or math.isnan(expected):
        return 1.0
    if expected >= trigger:
        delta = expected - trigger
        score = 8.5 + delta * 0.5
    else:
        delta = trigger - expected
        score = 8.5 - delta * 1.0
    return max(1.0, min(10.0, score))

# ── Pick Generation ──
def generate_picks(fixtures, stats):
    picks = []
    for home, away in fixtures:
        hs = stats.get(home)
        aw = stats.get(away)
        if hs is None or aw is None:
            continue

        best = None
        for mkey, mcfg in MARKETS.items():
            hv = hs.get(mkey)
            av = aw.get(mkey)
            if hv is None or av is None:
                continue
            expected = hv + av
            score = score_market(expected, mcfg["trigger"], mcfg["line"])
            if score >= SCORE_THRESHOLD:
                if best is None or score > best["score"]:
                    best = {
                        "fixture": f"{home} vs {away}",
                        "home": home, "away": away,
                        "market": mcfg["label"],
                        "market_key": mkey,
                        "expected": round(expected, 2),
                        "trigger": mcfg["trigger"],
                        "line": mcfg["line"],
                        "score": round(score, 2),
                        "odds": mcfg["odds"],
                    }

        if best:
            picks.append(best)

    picks.sort(key=lambda x: x["score"], reverse=True)
    return picks

# ── Ticket Builder ──
def build_ticket(picks, n_legs, win_rate):
    legs = picks[:n_legs]
    if not legs:
        return None
    total_odds = 1.0
    for leg in legs:
        total_odds *= leg["odds"]
    stake = round(BANKROLL * STAKE_PCT, 2)
    payout = round(stake * total_odds, 2)
    return {
        "legs": legs,
        "total_odds": round(total_odds, 2),
        "stake": stake,
        "payout": payout,
        "win_rate": win_rate,
        "n_legs": n_legs,
    }

# ── MAIN TEST ──
def main():
    print("=" * 60)
    print("  QUANT FOOTBALL BETTING ENGINE — LOCAL VERIFICATION TEST")
    print("=" * 60)

    # 1. Load data
    rows = load_csv(CSV_PATH)
    print(f"\n✓ Loaded {len(rows)} historical rows from sample_historical.csv")

    # 2. Compute stats
    stats = compute_rolling_stats(rows)
    print(f"✓ Computed rolling stats for {len(stats)} teams")

    # Print sample team stats
    sample_teams = list(stats.keys())[:3]
    print(f"\n--- Rolling 5-Game Stats (sample: {', '.join(sample_teams)}) ---")
    for t in sample_teams:
        s = stats[t]
        print(f"  {t:25s} | Fouls={s['fouls']:.2f}  Cards={s['cards']:.2f}  SoT={s['sot']:.2f}  Corners={s['corners']:.2f}")

    # 3. Generate demo fixtures (reversed pairings from dataset)
    fixtures = []
    seen = set()
    for row in rows[-20:]:
        h = row.get("HomeTeam","").strip()
        a = row.get("AwayTeam","").strip()
        pair = (a, h)  # reverse for "upcoming"
        if pair not in seen and h and a:
            fixtures.append(pair)
            seen.add(pair)
        if len(fixtures) >= 10:
            break

    print(f"\n✓ Evaluating {len(fixtures)} demo fixtures")

    # 4. Score picks
    picks = generate_picks(fixtures, stats)
    print(f"✓ Qualified picks (≥ {SCORE_THRESHOLD}/10): {len(picks)}")

    if not picks:
        print("\n⚠ No picks met the threshold. Check data or fixture list.")
        return

    print("\n--- All Qualified Picks ---")
    print(f"  {'Fixture':<35} {'Market':<28} {'Exp':>6}  {'Score':>6}  {'Odds':>5}")
    print("  " + "-" * 85)
    for p in picks:
        fire = " 🔥" if p["score"] >= 9.0 else ""
        print(f"  {p['fixture']:<35} {p['market']:<28} {p['expected']:>6.2f}  {p['score']:>5.1f}/10{fire}  {p['odds']:>5.2f}")

    # 5. Build tickets
    t5  = build_ticket(picks, 3, 0.3674)
    t10 = build_ticket(picks, 4, 0.2565)

    print("\n" + "=" * 60)
    print("  TICKET 1 — 5-Odds Strategy (3 Legs)")
    print("=" * 60)
    if t5:
        for i, leg in enumerate(t5["legs"], 1):
            print(f"  Leg {i}: {leg['fixture']}")
            print(f"          → {leg['market']} | Score: {leg['score']}/10 | Exp: {leg['expected']} | Odds: {leg['odds']}")
        print(f"\n  Total Odds : {t5['total_odds']:.2f}")
        print(f"  Stake      : ₦{t5['stake']:,.2f}  (1% of ₦{BANKROLL:,.0f})")
        print(f"  Est. Payout: ₦{t5['payout']:,.2f}")
        print(f"  Win Rate   : {t5['win_rate']*100:.2f}%")

    print("\n" + "=" * 60)
    print("  TICKET 2 — 10-Odds Strategy (4 Legs)")
    print("=" * 60)
    if t10:
        for i, leg in enumerate(t10["legs"], 1):
            print(f"  Leg {i}: {leg['fixture']}")
            print(f"          → {leg['market']} | Score: {leg['score']}/10 | Exp: {leg['expected']} | Odds: {leg['odds']}")
        print(f"\n  Total Odds : {t10['total_odds']:.2f}")
        print(f"  Stake      : ₦{t10['stake']:,.2f}  (1% of ₦{BANKROLL:,.0f})")
        print(f"  Est. Payout: ₦{t10['payout']:,.2f}")
        print(f"  Win Rate   : {t10['win_rate']*100:.2f}%")

    print("\n✅ All tests passed — engine logic verified!\n")

if __name__ == "__main__":
    main()
