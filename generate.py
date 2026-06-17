"""
Generate NBA score card SVG.

Designed to run in GitHub Actions. Fetches the latest game for a configured
team, renders an SVG card, and writes it to nba/output/nba-score.svg.

Data sources (tried in order):
    1. balldontlie (https://api.balldontlie.io, free API key required; includes Q1-Q4)
    2. nba_api  (stats.nba.com, no key)
    3. ESPN      (no key, fallback when stats.nba.com is blocked)

Usage:
    NBA_TEAM=LAL python nba/generate.py

Environment variables:
    NBA_TEAM:           Team abbreviation (default: LAL)
    BALLDONTLIE_API_KEY: Optional. Enables balldontlie fallback.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from jinja2 import Template

try:
    from util.nba import get_latest_game as get_latest_game_data
    from util.nba import get_latest_game_espn
except ImportError:
    get_latest_game_data = None
    get_latest_game_espn = None


# ─── Config ─────────────────────────────────────────────────────────────────────

TEAM_ABBREVIATION = os.environ.get("NBA_TEAM", "LAL").upper()
BALLDONTLIE_API_KEY = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
# Layout: "full" (wide scoreboard) or "compact" (minimal)
LAYOUT = os.environ.get("NBA_LAYOUT", "full").lower()

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "nba-score.svg"
TEMPLATE_FILE = Path(__file__).parent / "template.svg.j2"
FONTS_DIR = Path(__file__).parent / "fonts"
LOGOS_DIR = Path(__file__).parent / "logos"


def build_font_face_css():
    """
    Build @font-face CSS rules with embedded (base64) subsetted Archivo woff2 fonts.
    The fonts are pre-generated and stored in nba/fonts/*.b64 so the runtime needs
    no font tooling. Returns CSS string (may be empty if font files are missing).
    """
    css = ""
    for weight in (700, 900):
        b64_file = FONTS_DIR / f"archivo-{weight}.b64"
        if not b64_file.exists():
            continue
        b64 = b64_file.read_text().strip()
        css += (
            "@font-face{font-family:'ArchivoSubset';"
            f"font-weight:{weight};font-style:normal;font-display:swap;"
            f"src:url('data:font/woff2;base64,{b64}') format('woff2');}}"
        )
    return css

# Primary brand color per team (vivid, readable on dark background).
# Used to tint the user's own team abbreviation.
TEAM_COLORS = {
    "ATL": "E03A3E", "BOS": "39A05D", "BKN": "FFFFFF", "CHA": "00C0F2",
    "CHI": "CE1141", "CLE": "FDBB30", "DAL": "0064B1", "DEN": "FEC524",
    "DET": "C8102E", "GSW": "FFC72C", "HOU": "CE1141", "IND": "FDBB30",
    "LAC": "C8102E", "LAL": "FDB927", "MEM": "5D76A9", "MIA": "F9A01B",
    "MIL": "00471B", "MIN": "78BE20", "NOP": "85714D", "NYK": "F58426",
    "OKC": "EF3B24", "ORL": "0077C0", "PHI": "ED174C", "PHX": "E56020",
    "POR": "E03A3E", "SAC": "5A2D81", "SAS": "C4CED4", "TOR": "CE1141",
    "UTA": "F9A01B", "WAS": "E31837",
}
NEUTRAL_COLOR = "8A9099"  # opponent / non-highlighted text


def team_color(abbr):
    """Return the brand hex color for a team abbreviation (no #)."""
    return TEAM_COLORS.get(abbr.upper(), "FFFFFF")


def get_current_season_start_year():
    """Return the start year of the current NBA season (e.g. 2025 for 2025-26)."""
    today = datetime.now()
    return today.year if today.month >= 10 else today.year - 1


def get_current_season_str():
    """Return current season as 'YYYY-YY' for nba_api."""
    start = get_current_season_start_year()
    return f"{start}-{str(start + 1)[2:]}"


# ─── Data Source 1: nba_api ───────────────────────────────────────────────────────

def fetch_via_nba_api(team_abbreviation):
    """Fetch latest game via nba_api (stats.nba.com). Returns dict or None."""
    try:
        from nba_api.stats.endpoints import teamgamelog
        from nba_api.stats.static import teams
    except ImportError:
        print("nba_api not installed, skipping")
        return None

    def get_team(abbr):
        for t in teams.get_teams():
            if t["abbreviation"].upper() == abbr.upper():
                return t
        return None

    team = get_team(team_abbreviation)
    if not team:
        print(f"nba_api: unknown team '{team_abbreviation}'")
        return None

    season = get_current_season_str()
    print(f"[nba_api] Fetching {team['full_name']} ({team['abbreviation']}), season {season}")

    df = None
    for season_type in ["Playoffs", "Regular Season"]:
        try:
            game_log = teamgamelog.TeamGameLog(
                team_id=team["id"],
                season=season,
                season_type_all_star=season_type,
                timeout=15,
            )
            result_df = game_log.get_data_frames()[0]
            if not result_df.empty:
                df = result_df
                print(f"[nba_api] Found {len(df)} games in {season_type}")
                break
        except Exception as e:
            print(f"[nba_api] Failed {season_type}: {e}")
            # On connection/JSON errors, both season types will fail the same way
            return None

    if df is None or df.empty:
        print("[nba_api] No games found")
        return None

    latest = df.iloc[0]
    matchup = latest["MATCHUP"]  # "LAL vs. GSW" or "LAL @ GSW"
    is_home = "vs." in matchup

    if is_home:
        opponent_abbr = matchup.split("vs. ")[1].strip()
    else:
        opponent_abbr = matchup.split("@ ")[1].strip()

    opponent = get_team(opponent_abbr)
    opponent_name = opponent["full_name"] if opponent else opponent_abbr

    team_score = int(latest["PTS"])
    plus_minus = int(latest["PLUS_MINUS"])
    opponent_score = team_score - plus_minus
    result = latest["WL"]

    if is_home:
        home_team = {"name": team["full_name"], "abbreviation": team["abbreviation"], "score": team_score}
        away_team = {"name": opponent_name, "abbreviation": opponent_abbr, "score": opponent_score}
    else:
        home_team = {"name": opponent_name, "abbreviation": opponent_abbr, "score": opponent_score}
        away_team = {"name": team["full_name"], "abbreviation": team["abbreviation"], "score": team_score}

    return {
        "home_team": home_team,
        "away_team": away_team,
        "game_date": latest["GAME_DATE"],
        "result": result,
        "is_home": is_home,
        "status": "Final",
        "my_team": team["abbreviation"],
        "_source": "nba_api",
    }


# ─── Data Source 2: balldontlie ──────────────────────────────────────────────────

def fetch_via_balldontlie(team_abbreviation):
    """Fetch latest game via balldontlie API. Returns dict or None."""
    if not BALLDONTLIE_API_KEY:
        print("[balldontlie] No API key set (BALLDONTLIE_API_KEY), skipping")
        return None

    headers = {"Authorization": BALLDONTLIE_API_KEY}
    base = "https://api.balldontlie.io/v1"

    try:
        # 1. Find the team ID by abbreviation
        resp = requests.get(f"{base}/teams", headers=headers, timeout=15)
        resp.raise_for_status()
        teams_data = resp.json().get("data", [])

        team = next(
            (t for t in teams_data if t["abbreviation"].upper() == team_abbreviation.upper()),
            None,
        )
        if not team:
            print(f"[balldontlie] Unknown team '{team_abbreviation}'")
            return None

        print(f"[balldontlie] Fetching {team['full_name']} ({team['abbreviation']})")

        # 2. Get this season's games for the team
        season_start = get_current_season_start_year()
        params = {
            "team_ids[]": team["id"],
            "seasons[]": season_start,
            "per_page": 100,
        }
        resp = requests.get(f"{base}/games", headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        games = resp.json().get("data", [])

        # 3. Keep only finished games, sort by date descending
        finished = [g for g in games if g.get("status") == "Final"]
        if not finished:
            print("[balldontlie] No finished games found")
            return None

        finished.sort(key=lambda g: g.get("date", ""), reverse=True)
        latest = finished[0]

        home = latest["home_team"]
        visitor = latest["visitor_team"]
        home_score = latest["home_team_score"]
        visitor_score = latest["visitor_team_score"]

        is_home = home["abbreviation"].upper() == team_abbreviation.upper()
        if is_home:
            won = home_score > visitor_score
        else:
            won = visitor_score > home_score
        result = "W" if won else "L"

        # Format date "2025-01-05" -> "JAN 05, 2025"
        date_str = latest.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            game_date = dt.strftime("%b %d, %Y").upper()
        except ValueError:
            game_date = date_str

        # Quarter scores
        quarters = {
            "home_q1": latest.get("home_q1"),
            "home_q2": latest.get("home_q2"),
            "home_q3": latest.get("home_q3"),
            "home_q4": latest.get("home_q4"),
            "home_ot": latest.get("home_ot1"),
            "away_q1": latest.get("visitor_q1"),
            "away_q2": latest.get("visitor_q2"),
            "away_q3": latest.get("visitor_q3"),
            "away_q4": latest.get("visitor_q4"),
            "away_ot": latest.get("visitor_ot1"),
        }

        return {
            "home_team": {
                "name": home["full_name"],
                "abbreviation": home["abbreviation"],
                "score": home_score,
            },
            "away_team": {
                "name": visitor["full_name"],
                "abbreviation": visitor["abbreviation"],
                "score": visitor_score,
            },
            "game_date": game_date,
            "result": result,
            "is_home": is_home,
            "status": "Final",
            "my_team": team["abbreviation"],
            "quarters": quarters,
            "_source": "balldontlie",
        }

    except Exception as e:
        print(f"[balldontlie] Error: {e}")
        return None


def fetch_via_espn(team_abbreviation):
    """Fetch latest game via ESPN. Returns dict or None."""
    if get_latest_game_espn is None:
        return None

    try:
        game = get_latest_game_espn(team_abbreviation)
        if game:
            print("[espn] Latest game loaded")
            game["_source"] = "espn"
        return game
    except Exception as e:
        print(f"[espn] Error: {e}")
        return None


# ─── Orchestration ──────────────────────────────────────────────────────────────

def fetch_latest_game(team_abbreviation):
    """Try each data source in order until one succeeds."""
    if get_latest_game_data is not None:
        try:
            game = get_latest_game_data(team_abbreviation)
            if game:
                print(f"Success via {game.get('_source', 'util')}")
                return game
        except Exception as e:
            print(f"util data source failed: {e}")
        print("All data sources failed")
        return None

    for fetcher in (fetch_via_balldontlie, fetch_via_nba_api, fetch_via_espn):
        game = fetcher(team_abbreviation)
        if game:
            print(f"Success via {game['_source']}")
            return game
    print("All data sources failed")
    return None


# ─── ESPN Player Leaders ────────────────────────────────────────────────────────

ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_HEADERS = {"User-Agent": "Mozilla/5.0"}
ESPN_TO_NBA_ABBR = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
}


def normalize_team_abbr(abbreviation):
    """Normalize ESPN team abbreviations to the NBA/balldontlie form."""
    abbr = str(abbreviation or "").upper()
    return ESPN_TO_NBA_ABBR.get(abbr, abbr)


def fetch_espn_event_id(game_date_str, home_abbr, away_abbr):
    """Find the ESPN event ID for a game by date and team abbreviations."""
    # Parse date from various formats to YYYYMMDD
    from datetime import datetime as _dt
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%b %d, %Y".upper()):
        try:
            dt = _dt.strptime(game_date_str.strip(), fmt)
            break
        except ValueError:
            continue
    else:
        # Try uppercase month
        try:
            dt = _dt.strptime(game_date_str.strip().title(), "%b %d, %Y")
        except ValueError:
            print(f"[espn] Cannot parse date: {game_date_str}")
            return None

    date_str = dt.strftime("%Y%m%d")
    url = f"{ESPN_API}/scoreboard?dates={date_str}"

    try:
        resp = requests.get(url, headers=ESPN_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        events = resp.json().get("events", [])
        for ev in events:
            comp = ev["competitions"][0]
            teams_in_game = {normalize_team_abbr(c["team"].get("abbreviation", "")) for c in comp["competitors"]}
            if normalize_team_abbr(home_abbr) in teams_in_game or normalize_team_abbr(away_abbr) in teams_in_game:
                return ev["id"]
    except Exception as e:
        print(f"[espn] Error finding event: {e}")
    return None


def fetch_player_leaders(event_id):
    """
    Fetch top PTS/REB/AST player for each team from ESPN box score.
    Returns dict keyed by team abbreviation (uppercase).
    Each team has: { 'pts': {name, value}, 'reb': {name, value}, 'ast': {name, value} }
    """
    url = f"{ESPN_API}/summary?event={event_id}"
    try:
        resp = requests.get(url, headers=ESPN_HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[espn] Summary returned {resp.status_code}")
            return None
        data = resp.json()
        boxscore = data.get("boxscore", {})
        players_data = boxscore.get("players", [])
        if not players_data:
            return None

        result = {}
        for team_data in players_data:
            team_abbr = normalize_team_abbr(team_data["team"].get("abbreviation", ""))
            stats_group = team_data["statistics"][0]
            labels = stats_group["labels"]

            pts_idx = labels.index("PTS") if "PTS" in labels else -1
            reb_idx = labels.index("REB") if "REB" in labels else -1
            ast_idx = labels.index("AST") if "AST" in labels else -1

            athletes = [a for a in stats_group["athletes"] if len(a.get("stats", [])) > max(pts_idx, reb_idx, ast_idx)]
            if not athletes:
                continue

            def get_leader(idx):
                top = max(athletes, key=lambda a: int(a["stats"][idx]) if a["stats"][idx].isdigit() else 0)
                return {
                    "name": top["athlete"].get("shortName", top["athlete"].get("displayName", "")),
                    "value": int(top["stats"][idx]) if top["stats"][idx].isdigit() else 0,
                }

            team_leaders = {}
            if pts_idx >= 0:
                team_leaders["pts"] = get_leader(pts_idx)
            if reb_idx >= 0:
                team_leaders["reb"] = get_leader(reb_idx)
            if ast_idx >= 0:
                team_leaders["ast"] = get_leader(ast_idx)

            result[team_abbr] = team_leaders

        return result if result else None

    except Exception as e:
        print(f"[espn] Error fetching leaders: {e}")
        return None


# ─── Logo fetching ──────────────────────────────────────────────────────────────

# ESPN logo slug mapping (some abbreviations differ)
ESPN_LOGO_SLUGS = {
    "GSW": "gs", "NOP": "no", "NYK": "ny", "SAS": "sa",
    "UTA": "utah", "WAS": "wsh", "BKN": "bkn",
}


def fetch_team_logo_b64(abbreviation, size=200):
    """Load a team logo locally when available, otherwise download and embed it."""
    import base64
    from PIL import Image
    import io as _io

    slug = ESPN_LOGO_SLUGS.get(abbreviation.upper(), abbreviation.lower())
    local_candidates = (
        LOGOS_DIR / f"{abbreviation.upper()}.png",
        LOGOS_DIR / f"{abbreviation.lower()}.png",
        LOGOS_DIR / f"{slug}.png",
    )
    urls = (
        f"https://a.espncdn.com/i/teamlogos/nba/500/{slug}.png",
        f"http://a.espncdn.com/i/teamlogos/nba/500/{slug}.png",
    )

    def encode_image(raw):
        img = Image.open(_io.BytesIO(raw)).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    for path in local_candidates:
        if not path.exists():
            continue
        try:
            return encode_image(path.read_bytes())
        except Exception as e:
            print(f"Local logo failed for {abbreviation} at {path}: {e}")

    last_error = None
    for url in urls:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                continue
            return encode_image(resp.content)
        except Exception as e:
            last_error = e
    print(f"Logo fetch failed for {abbreviation}: {last_error}")
    return ""


# ─── SVG Generation ─────────────────────────────────────────────────────────────

def render_svg(game_data):
    """Render SVG from template with game data."""
    template_str = TEMPLATE_FILE.read_text(encoding="utf-8")
    template = Template(template_str)

    my_team = TEAM_ABBREVIATION
    ctx = {
        "game": game_data,
        "layout": LAYOUT if LAYOUT in ("full", "compact") else "full",
        "my_team": my_team,
        "neutral_color": NEUTRAL_COLOR,
        "font_face_css": build_font_face_css(),
        "away_logo": "",
        "home_logo": "",
        "leaders": None,
    }

    if game_data:
        away = game_data["away_team"]["abbreviation"]
        home = game_data["home_team"]["abbreviation"]
        ctx["away_color"] = team_color(away) if away.upper() == my_team.upper() else NEUTRAL_COLOR
        ctx["home_color"] = team_color(home) if home.upper() == my_team.upper() else NEUTRAL_COLOR
        away_score = game_data["away_team"]["score"]
        home_score = game_data["home_team"]["score"]
        ctx["away_won"] = away_score > home_score
        ctx["home_won"] = home_score > away_score

        # Fetch logos
        ctx["away_logo"] = fetch_team_logo_b64(away)
        ctx["home_logo"] = fetch_team_logo_b64(home)

        # Fetch player leaders via ESPN
        event_id = fetch_espn_event_id(game_data["game_date"], home, away)
        if event_id:
            print(f"[espn] Found event {event_id}, fetching leaders...")
            leaders = fetch_player_leaders(event_id)
            if leaders:
                ctx["leaders"] = leaders
                print(f"[espn] Leaders loaded")
            else:
                ctx["leaders"] = {}
        else:
            print("[espn] Could not find event ID for leaders")
            ctx["leaders"] = {}
    else:
        ctx["my_color"] = team_color(my_team)
        ctx["leaders"] = None

    return template.render(**ctx)


# ─── Main ────────────────────────────────────────────────────────────────────────

def main():
    print("=== NBA Score Card Generator ===")
    print(f"Team: {TEAM_ABBREVIATION}  Layout: {LAYOUT}")
    print()

    game_data = fetch_latest_game(TEAM_ABBREVIATION)

    if game_data:
        g = game_data
        print(
            f"\nLatest: {g['away_team']['abbreviation']} {g['away_team']['score']} @ "
            f"{g['home_team']['abbreviation']} {g['home_team']['score']} "
            f"({g['game_date']}) -> {g['result']}"
        )

    svg = render_svg(game_data)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(svg, encoding="utf-8")
    print(f"\nSVG written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
