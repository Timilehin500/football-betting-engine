import os
import glob
import pandas as pd
import numpy as np
from flask import Flask, jsonify, request

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

def load_data():
    if not os.path.exists(DATA_DIR):
        return pd.DataFrame()
    files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
            df.columns = [str(c).strip().upper() for c in df.columns]
            dfs.append(df)
        except Exception:
            pass
    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()

def calculate_rolling_features(df):
    teams = {}
    if df.empty:
        return teams

    for idx, row in df.iterrows():
        home = str(row.get('HOMETEAM', '')).strip()
        away = str(row.get('AWAYTEAM', '')).strip()

        if not home or not away or home.lower() == 'nan' or away.lower() == 'nan':
            continue

        hst = float(row.get('HST', 4.0)) if pd.notnull(row.get('HST')) else 4.0
        ast = float(row.get('AST', 4.0)) if pd.notnull(row.get('AST')) else 4.0
        hc = float(row.get('HC', 5.0)) if pd.notnull(row.get('HC')) else 5.0
        ac = float(row.get('AC', 5.0)) if pd.notnull(row.get('AC')) else 5.0
        hf = float(row.get('HF', 11.0)) if pd.notnull(row.get('HF')) else 11.0
        af = float(row.get('AF', 11.0)) if pd.notnull(row.get('AF')) else 11.0
        hy = float(row.get('HY', 1.5)) if pd.notnull(row.get('HY')) else 1.5
        ay = float(row.get('AY', 1.5)) if pd.notnull(row.get('AY')) else 1.5

        if home not in teams:
            teams[home] = {'sot_for': [], 'sot_ag': [], 'corn_for': [], 'corn_ag': [], 'foul_for': [], 'foul_ag': [], 'card_for': []}
        if away not in teams:
            teams[away] = {'sot_for': [], 'sot_ag': [], 'corn_for': [], 'corn_ag': [], 'foul_for': [], 'foul_ag': [], 'card_for': []}

        teams[home]['sot_for'].append(hst)
        teams[home]['sot_ag'].append(ast)
        teams[home]['corn_for'].append(hc)
        teams[home]['corn_ag'].append(ac)
        teams[home]['foul_for'].append(hf)
        teams[home]['foul_ag'].append(af)
        teams[home]['card_for'].append(hy)

        teams[away]['sot_for'].append(ast)
        teams[away]['sot_ag'].append(hst)
        teams[away]['corn_for'].append(ac)
        teams[away]['corn_ag'].append(hc)
        teams[away]['foul_for'].append(af)
        teams[away]['foul_ag'].append(hf)
        teams[away]['card_for'].append(ay)

    stats = {}
    for t, d in teams.items():
        stats[t] = {
            'sot_for': float(np.mean(d['sot_for'][-5:])) if d['sot_for'] else 4.5,
            'sot_ag': float(np.mean(d['sot_ag'][-5:])) if d['sot_ag'] else 4.5,
            'corn_for': float(np.mean(d['corn_for'][-5:])) if d['corn_for'] else 5.0,
            'corn_ag': float(np.mean(d['corn_ag'][-5:])) if d['corn_ag'] else 5.0,
            'foul_for': float(np.mean(d['foul_for'][-5:])) if d['foul_for'] else 11.0,
            'foul_ag': float(np.mean(d['foul_ag'][-5:])) if d['foul_ag'] else 11.0,
            'card_for': float(np.mean(d['card_for'][-5:])) if d['card_for'] else 1.8
        }
    return stats

def evaluate_match_quant(home, away, stats):
    h_s = stats.get(home, {'sot_for': 4.5, 'sot_ag': 4.5, 'corn_for': 5.0, 'corn_ag': 5.0, 'foul_for': 11.0, 'foul_ag': 11.0, 'card_for': 1.8})
    a_s = stats.get(away, {'sot_for': 4.5, 'sot_ag': 4.5, 'corn_for': 5.0, 'corn_ag': 5.0, 'foul_for': 11.0, 'foul_ag': 11.0, 'card_for': 1.8})

    exp_sot = round((h_s['sot_for'] + a_s['sot_ag'] + a_s['sot_for'] + h_s['sot_ag']) / 2.0, 1)
    exp_corners = round((h_s['corn_for'] + a_s['corn_ag'] + a_s['corn_for'] + h_s['corn_ag']) / 2.0, 1)
    exp_fouls = round((h_s['foul_for'] + a_s['foul_ag'] + a_s['foul_for'] + h_s['foul_ag']) / 2.0, 1)
    exp_cards = round(h_s['card_for'] + a_s['card_for'], 1)

    candidate_markets = []

    if exp_sot >= 10.0:
        sot_score = round(min(10.0, 7.5 + (exp_sot - 10.0) * 0.5), 1)
        candidate_markets.append({
            'market': 'Over 8.5 Shots on Target',
            'exp': exp_sot,
            'line': 8.5,
            'trig': 12.0,
            'score': sot_score,
            'odd': 1.75
        })

    if exp_corners >= 10.5:
        corn_score = round(min(10.0, 7.2 + (exp_corners - 10.5) * 0.6), 1)
        candidate_markets.append({
            'market': 'Over 9.5 Corners',
            'exp': exp_corners,
            'line': 9.5,
            'trig': 12.5,
            'score': corn_score,
            'odd': 1.68
        })

    if exp_fouls >= 24.0:
        foul_score = round(min(10.0, 7.0 + (exp_fouls - 24.0) * 0.4), 1)
        candidate_markets.append({
            'market': 'Over 22.5 Total Fouls',
            'exp': exp_fouls,
            'line': 22.5,
            'trig': 26.0,
            'score': foul_score,
            'odd': 1.80
        })

    if exp_cards >= 4.2:
        card_score = round(min(10.0, 7.0 + (exp_cards - 4.2) * 0.7), 1)
        candidate_markets.append({
            'market': 'Over 3.5 Yellow Cards',
            'exp': exp_cards,
            'line': 3.5,
            'trig': 4.5,
            'score': card_score,
            'odd': 1.70
        })

    if not candidate_markets:
        base_score = round(min(8.4, 6.0 + (exp_sot / 3.0)), 1)
        candidate_markets.append({
            'market': 'Over 7.5 Shots on Target',
            'exp': exp_sot,
            'line': 7.5,
            'trig': 10.0,
            'score': base_score,
            'odd': 1.50
        })

    best_pick = max(candidate_markets, key=lambda x: x['score'])
    best_pick['match'] = f"{home} vs {away}"
    return best_pick

@app.route('/api/predict', methods=['POST', 'GET'])
def predict():
    req = request.get_json() if request.is_json else {}
    if not req:
        req = request.form.to_dict() if request.form else {}

    custom_fixtures = req.get('fixtures', [])
    bankroll = float(req.get('bankroll', 15000))
    mode = req.get('mode', '5-odds')

    df = load_data()
    team_stats = calculate_rolling_features(df)

    fixtures_to_process = []
    
    if custom_fixtures:
        for fix in custom_fixtures:
            h = str(fix.get('home', '')).strip()
            a = str(fix.get('away', '')).strip()
            if h and a and h.lower() != a.lower():
                fixtures_to_process.append((h, a))
    else:
        all_teams = list(team_stats.keys())
        seen_pairs = set()
        if len(all_teams) >= 2:
            for i in range(0, len(all_teams) - 1, 2):
                t1, t2 = all_teams[i], all_teams[i+1]
                pair_key = tuple(sorted([t1.lower(), t2.lower()]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    fixtures_to_process.append((t1, t2))
        else:
            fixtures_to_process = [("Arsenal", "Chelsea"), ("Liverpool", "Man City"), ("Real Madrid", "Barcelona")]

    evaluated_picks = []
    seen_matches = set()

    for home, away in fixtures_to_process:
        pair_key = tuple(sorted([home.lower(), away.lower()]))
        if pair_key in seen_matches:
            continue
        seen_matches.add(pair_key)

        pick = evaluate_match_quant(home, away, team_stats)
        evaluated_picks.append(pick)

    evaluated_picks.sort(key=lambda x: x['score'], reverse=True)

    qualified_picks = [p for p in evaluated_picks if p['score'] >= 8.5]
    if not qualified_picks:
        qualified_picks = evaluated_picks

    num_legs = 3 if mode == '5-odds' else 4
    selected_picks = qualified_picks[:num_legs]

    total_odds = 1.0
    for p in selected_picks:
        total_odds *= p['odd']
    total_odds = round(total_odds, 2)

    stake = round(bankroll * 0.01, 2)
    payout = round(stake * total_odds, 2)
    win_rate = round(min(85.0, (100.0 / total_odds) * 1.8), 1)

    return jsonify({
        'picks': selected_picks,
        'total_odds': total_odds,
        'stake': stake,
        'payout': payout,
        'win_rate': win_rate,
        'total_qualified': len(qualified_picks),
        'teams_count': len(team_stats),
        'fixtures_count': len(fixtures_to_process)
    })

if __name__ == '__main__':
    app.run(debug=True)
