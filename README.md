# ⚽ Quantitative Football Betting Engine

A serverless web application that computes 5-game rolling statistics from historical football match data and generates scored betting tickets using a quantitative model.

## Architecture

```
football_proect/
├── api/
│   └── index.py          # Flask backend (Vercel serverless function)
├── public/
│   └── index.html        # Mobile-first dark dashboard
├── data/
│   └── sample_historical.csv   # Bundled seed data (EPL, La Liga, Serie A, Bundesliga, Ligue 1)
├── requirements.txt      # Python dependencies
├── vercel.json           # Vercel routing config
└── README.md
```

## Local Development

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the Flask dev server
python api/index.py

# 4. Serve the frontend (separate terminal)
cd public && python3 -m http.server 8080

# 5. Visit http://localhost:5000/api/ticket (API) or http://localhost:8080 (UI)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ticket` | GET/POST | Generate scored betting tickets |
| `/api/teams` | GET | List all teams with rolling stats |
| `/api/health` | GET | Health check |

### POST `/api/ticket` Body

```json
{
  "bankroll": 15000,
  "strategy": "5-odds",
  "fixtures": [
    {"home_team": "Arsenal", "away_team": "Chelsea"},
    {"home_team": "Barcelona", "away_team": "Real Madrid"}
  ]
}
```

## Quant Model

| Market | Line | Trigger | Odds | Weight |
|--------|------|---------|------|--------|
| Over 22.5 Fouls | 22.5 | ≥ 28.60 | 1.50 | 8.5 |
| Over 3.5 Yellow Cards | 3.5 | ≥ 5.40 | 1.55 | 8.5 |
| Over 8.5 Shots on Target | 8.5 | ≥ 12.00 | 1.80 | 9.0 |
| Over 8.5 Corners | 8.5 | ≥ 11.80 | 1.55 | 8.5 |

Picks scoring ≥ 8.5/10 qualify. Default bankroll stake = **1%**.

## Deploy to Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Login
vercel login

# Deploy (first time)
vercel

# Deploy to production
vercel --prod
```

## Push to GitHub

```bash
git init
git add .
git commit -m "feat: Quantitative Football Betting Engine v1.0"
git remote add origin https://github.com/YOUR_USERNAME/football-betting-engine.git
git branch -M main
git push -u origin main
```

Then connect the GitHub repo to Vercel via the [Vercel Dashboard](https://vercel.com/new) for automatic deployments on every push.

## Data Sources

- **Bundled**: `data/sample_historical.csv` (Premier League, La Liga, Serie A, Bundesliga, Ligue 1)
- **Auto-fetched at runtime**: [football-data.co.uk](https://football-data.co.uk) — E0, SP1, I1, D1, F1 CSVs (current 2024-25 season)

> **Disclaimer**: For informational and educational purposes only. Always gamble responsibly.
