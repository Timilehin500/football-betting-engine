"""
Quantitative Football Betting Engine - Flask API
Serverless backend for Vercel deployment.
Computes 5-game rolling statistics and generates scored betting tickets.
"""

from flask import Flask, jsonify, request
import pandas as pd
import numpy as np
import os
import io
import logging

# ── Try to import requests (optional at import time, required at data-fetch time) ──
try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─────────────────────────────────────────────
#  CONSTANTS & CONFIGURATION
# ─────────────────────────────────────────────
MARKETS = {
    "fouls": {
        "label":     "Over 22.5 Fouls",
        "line":       22.5,
        "trigger":    28.60,
        "odds":       1.50,
        "weight":     8.5,
        "home_col":  "HF",
        "away_col":  "AF",
    },
    "cards": {
        "label":     "Over 3.5 Yellow Cards",
        "line":       3.5,
        "trigger":    5.40,
        "odds":       1.55,
        "weight":     8.5,
        "home_col":  "HY",
        "away_col":  "AY",
    },
    "sot": {
        "label":     "Over 8.5 Shots on Target",
        "line":       8.5,
        "trigger":   12.00,
        "odds":       1.80,
        "weight":     9.0,
        "home_col":  "HST",
        "away_col":  "AST",
    },
    "corners": {
        "label":     "Over 8.5 Corners",
        "line":       8.5,
        "trigger":   11.80,
        "odds":       1.55,
        "weight":     8.5,
        "home_col":  "HC",
        "away_col":  "AC",
    },
}

ROLLING_WINDOW   = 5
SCORE_THRESHOLD  = 8.5    # minimum score to qualify
BANKROLL_DEFAULT = 15000  # ₦
STAKE_PCT        = 0.01   # 1 %

# Football-Data.co.uk CSV feeds (current season 2024-25)
DATA_SOURCES = {
    "E0":  "https://www.football-data.co.uk/mmz4281/2425/E0.csv",   # Premier League
    "SP1": "https://www.football-data.co.uk/mmz4281/2425/SP1.csv",  # La Liga
    "I1":  "https://www.football-data.co.uk/mmz4281/2425/I1.csv",   # Serie A
    "D1":  "https://www.football-data.co.uk/mmz4281/2425/D1.csv",   # Bundesliga
    "F1":  "https://www.football-data.co.uk/mmz4281/2425/F1.csv",   # Ligue 1
}

# Required columns for box-score metrics
REQUIRED_COLS = ["HomeTeam", "AwayTeam", "HF", "AF", "HY", "AY", "HST", "AST", "HC", "AC"]
DATE_COLS     = ["Date"]

# Data directory (writable in local dev; Vercel /tmp is writable)
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
if not os.path.isdir(DATA_DIR):
    DATA_DIR = "/tmp/football_data"
os.makedirs(DATA_DIR, exist_ok=True)


# ─────────────────────────────────────────────
#  DATA LOADING
# ─────────────────────────────────────────────

def _fetch_remote_csv(url: str) -> pd.DataFrame | None:
    """Download a CSV from Football-Data.co.uk."""
    if not HAS_REQUESTS:
        logger.warning("requests library not available; skipping remote fetch")
        return None
    try:
        resp = req_lib.get(url, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), on_bad_lines="skip", low_memory=False)
        return df
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def _load_local_csv(path: str) -> pd.DataFrame | None:
    """Load a local CSV file safely."""
    try:
        df = pd.read_csv(path, on_bad_lines="skip", low_memory=False)
        return df
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows with all required box-score columns populated."""
    if df is None or df.empty:
        return pd.DataFrame()

    # Normalise column names (strip whitespace)
    df.columns = [c.strip() for c in df.columns]

    # Keep only rows that have at least the metric columns
    metric_cols = [c for c in REQUIRED_COLS if c not in ("HomeTeam", "AwayTeam")]
    available   = [c for c in REQUIRED_COLS if c in df.columns]

    if len(available) < len(REQUIRED_COLS):
        missing = set(REQUIRED_COLS) - set(available)
        logger.warning("Columns missing in source: %s", missing)
        # Drop missing metric cols from required set; keep what we have
        needed = [c for c in REQUIRED_COLS if c in df.columns]
        if "HomeTeam" not in needed or "AwayTeam" not in needed:
            return pd.DataFrame()
        df = df[needed].copy()
    else:
        df = df[REQUIRED_COLS].copy()

    # Convert metrics to numeric; coerce errors to NaN
    for col in df.columns:
        if col not in ("HomeTeam", "AwayTeam"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop rows missing team names or ALL metric values
    df = df.dropna(subset=["HomeTeam", "AwayTeam"])
    df = df.dropna(how="all", subset=[c for c in df.columns if c not in ("HomeTeam", "AwayTeam")])

    return df.reset_index(drop=True)


def load_historical_data() -> pd.DataFrame:
    """
    Load historical match data.

    Priority:
    1. User-uploaded file in data/ directory (any .csv)
    2. Cached remote CSVs in data/
    3. Fresh remote fetch from Football-Data.co.uk
    """
    frames = []

    # 1. Check data/ for user-uploaded or cached files
    if os.path.isdir(DATA_DIR):
        for fname in os.listdir(DATA_DIR):
            if fname.lower().endswith(".csv"):
                path = os.path.join(DATA_DIR, fname)
                df   = _load_local_csv(path)
                cleaned = _clean_dataframe(df)
                if not cleaned.empty:
                    cleaned["_source"] = fname
                    frames.append(cleaned)
                    logger.info("Loaded %d rows from %s", len(cleaned), fname)

    # 2. Remote fetch (and cache) if no local data or not enough rows
    total_local = sum(len(f) for f in frames)
    if total_local < 50:
        for key, url in DATA_SOURCES.items():
            cache_path = os.path.join(DATA_DIR, f"{key}.csv")
            # Use cache if it exists and is < 6 hours old
            use_cache = False
            if os.path.exists(cache_path):
                age_secs = os.path.getmtime(cache_path)
                import time
                if (time.time() - age_secs) < 21600:
                    use_cache = True

            if use_cache:
                df = _load_local_csv(cache_path)
            else:
                df = _fetch_remote_csv(url)
                if df is not None:
                    try:
                        df.to_csv(cache_path, index=False)
                    except Exception:
                        pass

            cleaned = _clean_dataframe(df)
            if not cleaned.empty:
                cleaned["_source"] = key
                frames.append(cleaned)
                logger.info("Loaded %d rows from %s (%s)", len(cleaned), key, "cache" if use_cache else "remote")

    if not frames:
        logger.error("No historical data available.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Total historical rows loaded: %d", len(combined))
    return combined


# ─────────────────────────────────────────────
#  ROLLING STATISTICS ENGINE
# ─────────────────────────────────────────────

def compute_team_rolling_stats(df: pd.DataFrame) -> dict:
    """
    Compute 5-game rolling means for each team across all four market metrics.

    Returns a dict keyed by team name, value = dict of market_key → rolling mean.
    """
    if df.empty:
        return {}

    team_stats: dict[str, dict] = {}

    all_teams = pd.concat([df["HomeTeam"], df["AwayTeam"]]).unique()

    for team in all_teams:
        home_rows = df[df["HomeTeam"] == team]
        away_rows = df[df["AwayTeam"] == team]

        team_stats[team] = {}

        for mkey, mcfg in MARKETS.items():
            hcol = mcfg["home_col"]
            acol = mcfg["away_col"]

            # Build a unified series of the team's "total" stat per game
            home_vals = home_rows[hcol].dropna() if hcol in home_rows.columns else pd.Series(dtype=float)
            away_vals = away_rows[acol].dropna() if acol in away_rows.columns else pd.Series(dtype=float)

            all_vals = pd.concat([home_vals, away_vals]).reset_index(drop=True)

            if len(all_vals) == 0:
                team_stats[team][mkey] = np.nan
            elif len(all_vals) < ROLLING_WINDOW:
                team_stats[team][mkey] = float(all_vals.mean())
            else:
                # Rolling mean of last 5 games
                team_stats[team][mkey] = float(all_vals.iloc[-ROLLING_WINDOW:].mean())

    return team_stats


# ─────────────────────────────────────────────
#  SCORING ENGINE
# ─────────────────────────────────────────────

def score_market(expected: float, trigger: float, line: float) -> float:
    """
    Score a single market on a 1.0–10.0 scale.

    Logic:
    - At the trigger threshold → 8.5
    - Scales linearly above/below trigger (clamped to [1.0, 10.0])
    - Each 1-unit above trigger adds ~0.5 points (up to 10.0)
    - Each 1-unit below trigger subtracts ~1.0 point (down to 1.0)
    """
    if np.isnan(expected):
        return 1.0

    above_line = expected - line

    if expected >= trigger:
        # Score from 8.5 upward
        delta = expected - trigger
        score = 8.5 + (delta * 0.5)
    else:
        # Score below 8.5
        delta = trigger - expected
        score = 8.5 - (delta * 1.0)

    return float(np.clip(score, 1.0, 10.0))


def generate_fixture_picks(fixtures: list[dict], team_stats: dict) -> list[dict]:
    """
    For each upcoming fixture, compute expected stats and score all markets.
    Returns picks with score >= SCORE_THRESHOLD, sorted by score descending.
    """
    picks = []

    for fix in fixtures:
        home = fix.get("home_team", "").strip()
        away = fix.get("away_team", "").strip()

        if not home or not away:
            continue

        home_s = team_stats.get(home)
        away_s = team_stats.get(away)

        if home_s is None or away_s is None:
            logger.warning("No stats for %s or %s", home, away)
            continue

        best_pick = None

        for mkey, mcfg in MARKETS.items():
            h_val = home_s.get(mkey, np.nan)
            a_val = away_s.get(mkey, np.nan)

            if np.isnan(h_val) or np.isnan(a_val):
                continue

            expected = h_val + a_val
            score    = score_market(expected, mcfg["trigger"], mcfg["line"])

            candidate = {
                "home_team":   home,
                "away_team":   away,
                "fixture":     f"{home} vs {away}",
                "market_key":  mkey,
                "market":      mcfg["label"],
                "line":        mcfg["line"],
                "expected":    round(expected, 2),
                "trigger":     mcfg["trigger"],
                "score":       round(score, 2),
                "odds":        mcfg["odds"],
                "weight":      mcfg["weight"],
            }

            if score >= SCORE_THRESHOLD:
                if best_pick is None or score > best_pick["score"]:
                    best_pick = candidate

        if best_pick:
            picks.append(best_pick)

    # Sort by score descending
    picks.sort(key=lambda x: x["score"], reverse=True)
    return picks


# ─────────────────────────────────────────────
#  TICKET BUILDER
# ─────────────────────────────────────────────

def build_ticket(picks: list[dict], strategy: str, bankroll: float) -> dict:
    """
    Build accumulator ticket from top picks.

    strategy: "5-odds" → top 3 picks  |  "10-odds" → top 4 picks
    """
    n_legs   = 3 if strategy == "5-odds" else 4
    win_rate = 0.3674 if strategy == "5-odds" else 0.2565
    legs     = picks[:n_legs]

    if not legs:
        return {
            "strategy":   strategy,
            "legs":       [],
            "total_odds": 0,
            "stake":      0,
            "payout":     0,
            "win_rate":   win_rate,
            "bankroll":   bankroll,
        }

    total_odds = 1.0
    for leg in legs:
        total_odds *= leg["odds"]

    stake  = round(bankroll * STAKE_PCT, 2)
    payout = round(stake * total_odds, 2)

    return {
        "strategy":   strategy,
        "n_legs":     n_legs,
        "legs":       legs,
        "total_odds": round(total_odds, 2),
        "stake":      stake,
        "payout":     payout,
        "win_rate":   win_rate,
        "bankroll":   bankroll,
    }


# ─────────────────────────────────────────────
#  DEFAULT FIXTURE GENERATOR
# ─────────────────────────────────────────────

def _default_fixtures(df: pd.DataFrame) -> list[dict]:
    """
    When no fixtures are supplied, synthesise upcoming fixtures from
    the most-recently-seen teams in the dataset (last 10 home/away pairs).
    This is the 'demo mode' – in production the client supplies fixtures.
    """
    if df.empty:
        return []

    recent = df.tail(20)[["HomeTeam", "AwayTeam"]].drop_duplicates()
    fixtures = []
    seen = set()
    for _, row in recent.iterrows():
        h, a = row["HomeTeam"], row["AwayTeam"]
        pair = (h, a)
        # Reverse the pair to simulate a future fixture
        future = (a, h)
        if future not in seen and h != a:
            fixtures.append({"home_team": a, "away_team": h})
            seen.add(future)
        if len(fixtures) >= 10:
            break

    # Pad with original pairings if needed
    for _, row in recent.iterrows():
        h, a = row["HomeTeam"], row["AwayTeam"]
        pair = (h, a)
        if pair not in seen:
            fixtures.append({"home_team": h, "away_team": a})
            seen.add(pair)
        if len(fixtures) >= 20:
            break

    return fixtures


# ─────────────────────────────────────────────
#  FLASK ROUTES
# ─────────────────────────────────────────────

@app.route("/api/ticket", methods=["GET", "POST"])
def api_ticket():
    """
    Main betting engine endpoint.

    POST body (JSON) — all optional:
    {
        "bankroll": 15000,
        "strategy": "5-odds" | "10-odds",
        "fixtures": [{"home_team": "Arsenal", "away_team": "Chelsea"}, ...]
    }
    """
    # Parse request
    if request.method == "POST":
        body     = request.get_json(force=True, silent=True) or {}
    else:
        body = {}

    bankroll = float(body.get("bankroll", BANKROLL_DEFAULT))
    strategy = body.get("strategy", "5-odds")
    if strategy not in ("5-odds", "10-odds"):
        strategy = "5-odds"

    fixtures_input = body.get("fixtures", [])

    # Load data & compute stats
    df = load_historical_data()

    if df.empty:
        return jsonify({
            "error":     "No historical data available. Data sources unreachable.",
            "status":    "no_data",
            "ticket":    None,
            "all_picks": [],
        }), 503

    team_stats = compute_team_rolling_stats(df)
    n_teams    = len(team_stats)

    # Use supplied fixtures or fall back to auto-generated demo fixtures
    fixtures = fixtures_input if fixtures_input else _default_fixtures(df)

    if not fixtures:
        return jsonify({"error": "No fixtures to evaluate.", "status": "no_fixtures"}), 400

    # Generate picks
    all_picks = generate_fixture_picks(fixtures, team_stats)

    # Build both tickets
    ticket_5  = build_ticket(all_picks, "5-odds",  bankroll)
    ticket_10 = build_ticket(all_picks, "10-odds", bankroll)

    # Primary ticket based on requested strategy
    primary_ticket = ticket_5 if strategy == "5-odds" else ticket_10

    return jsonify({
        "status":       "ok",
        "n_teams":      n_teams,
        "n_fixtures":   len(fixtures),
        "n_picks":      len(all_picks),
        "ticket":       primary_ticket,
        "ticket_5":     ticket_5,
        "ticket_10":    ticket_10,
        "all_picks":    all_picks,
        "bankroll":     bankroll,
        "strategy":     strategy,
        "data_sources": list(team_stats.keys())[:10],
    })


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "engine": "Quantitative Football Betting Engine v1.0"})


@app.route("/api/teams", methods=["GET"])
def api_teams():
    """Return all teams with their rolling stats."""
    df = load_historical_data()
    if df.empty:
        return jsonify({"teams": [], "error": "No data"}), 503

    stats = compute_team_rolling_stats(df)
    result = []
    for team, s in stats.items():
        result.append({
            "team":    team,
            "fouls":   round(s.get("fouls",   0) or 0, 2),
            "cards":   round(s.get("cards",   0) or 0, 2),
            "sot":     round(s.get("sot",     0) or 0, 2),
            "corners": round(s.get("corners", 0) or 0, 2),
        })
    result.sort(key=lambda x: x["team"])
    return jsonify({"teams": result, "count": len(result)})


# Vercel serverless entrypoint
# (Vercel calls the module-level `app` directly via the WSGI handler)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
