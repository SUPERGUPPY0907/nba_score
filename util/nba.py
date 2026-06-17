"""
NBA utility module.
Fetches the most recent game score for a given team.

Primary source: nba_api (stats.nba.com)
Fallback source: ESPN free API (no auth, no IP restrictions)

stats.nba.com often blocks cloud/datacenter IPs, so ESPN is used as automatic fallback.
"""

from datetime import datetime
import os

import requests

# ─── ESPN fallback config ───────────────────────────────────────────────────────

ESPN_TEAM_SLUGS = {
    "ATL": "atl", "BOS": "bos", "BKN": "bkn", "CHA": "cha", "CHI": "chi",
    "CLE": "cle", "DAL": "dal", "DEN": "den", "DET": "det", "GSW": "gs",
    "HOU": "hou", "IND": "ind", "LAC": "lac", "LAL": "lal", "MEM": "mem",
    "MIA": "mia", "MIL": "mil", "MIN": "min", "NOP": "no", "NYK": "ny",
    "OKC": "okc", "ORL": "orl", "PHI": "phi", "PHX": "phx", "POR": "por",
    "SAC": "sac", "SAS": "sa", "TOR": "tor", "UTA": "utah", "WAS": "wsh",
}

ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
BALLDONTLIE_API_KEY = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
BALLDONTLIE_API_BASE = "https://api.balldontlie.io/v1"
BALLDONTLIE_TEAM_IDS = {
    "ATL": 1, "BOS": 2, "BKN": 3, "CHA": 4, "CHI": 5,
    "CLE": 6, "DAL": 7, "DEN": 8, "DET": 9, "GSW": 10,
    "HOU": 11, "IND": 12, "LAC": 13, "LAL": 14, "MEM": 15,
    "MIA": 16, "MIL": 17, "MIN": 18, "NOP": 19, "NYK": 20,
    "OKC": 21, "ORL": 22, "PHI": 23, "PHX": 24, "POR": 25,
    "SAC": 26, "SAS": 27, "TOR": 28, "UTA": 29, "WAS": 30,
}


def _empty_quarters():
    return {
        "home_q1": None,
        "home_q2": None,
        "home_q3": None,
        "home_q4": None,
        "home_ot": None,
        "away_q1": None,
        "away_q2": None,
        "away_q3": None,
        "away_q4": None,
        "away_ot": None,
    }


def _parse_espn_score(score_raw):
    """Return an integer score from the different shapes ESPN may return."""
    if isinstance(score_raw, dict):
        score_raw = score_raw.get("displayValue", score_raw.get("value", 0))
    if score_raw is None:
        return 0
    score = str(score_raw).strip()
    return int(score) if score.isdigit() else 0


def _parse_espn_datetime(event):
    try:
        dt = datetime.fromisoformat(event.get("date", "").replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0


def _parse_game_date_value(game):
    try:
        return datetime.strptime(game.get("date", "")[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return datetime.min


def _is_final_status(status):
    status_text = str(status or "").strip().lower()
    return status_text == "final" or status_text.startswith("final")


def _is_live_status(status):
    status_text = str(status or "").strip().lower()
    if not status_text or _is_final_status(status_text):
        return False
    upcoming = ("scheduled", "postponed", "canceled", "cancelled", "delayed")
    if any(word in status_text for word in upcoming):
        return False
    live_words = ("live", "progress", "qtr", "quarter", "half", "halftime", "ot")
    return any(word in status_text for word in live_words)


def _normalize_game_status(status):
    if _is_final_status(status):
        return "Final"
    if _is_live_status(status):
        return "Live"
    return str(status or "Scheduled")


def _select_latest_relevant_game(games):
    if not games:
        return None

    live_games = [game for game in games if _is_live_status(game.get("status"))]
    if live_games:
        return max(live_games, key=_parse_game_date_value)

    final_games = [game for game in games if _is_final_status(game.get("status"))]
    if final_games:
        return max(final_games, key=_parse_game_date_value)

    today = datetime.now().date()
    past_or_today = [
        game for game in games
        if _parse_game_date_value(game).date() <= today
    ]
    if past_or_today:
        return max(past_or_today, key=_parse_game_date_value)

    return min(games, key=_parse_game_date_value)


def _get_current_season_start_year():
    today = datetime.now()
    return today.year if today.month >= 10 else today.year - 1


def _parse_season_start_year(season):
    if not season:
        return _get_current_season_start_year()
    try:
        return int(str(season).split("-")[0])
    except (TypeError, ValueError):
        return _get_current_season_start_year()


def _sum_optional_scores(*scores):
    values = [score for score in scores if score is not None]
    return sum(values) if values else None


def _extract_balldontlie_quarters(game):
    quarters = _empty_quarters()
    quarters.update({
        "home_q1": game.get("home_q1"),
        "home_q2": game.get("home_q2"),
        "home_q3": game.get("home_q3"),
        "home_q4": game.get("home_q4"),
        "home_ot": _sum_optional_scores(
            game.get("home_ot1"),
            game.get("home_ot2"),
            game.get("home_ot3"),
        ),
        "away_q1": game.get("visitor_q1"),
        "away_q2": game.get("visitor_q2"),
        "away_q3": game.get("visitor_q3"),
        "away_q4": game.get("visitor_q4"),
        "away_ot": _sum_optional_scores(
            game.get("visitor_ot1"),
            game.get("visitor_ot2"),
            game.get("visitor_ot3"),
        ),
    })
    return quarters


def _line_score_value(linescores, index):
    if len(linescores) <= index:
        return None
    raw = linescores[index]
    if isinstance(raw, dict):
        raw = raw.get("value", raw.get("displayValue"))
    if raw is None:
        return None
    value = str(raw).strip()
    return int(value) if value.isdigit() else None


def _extract_espn_quarters(home_competitor, away_competitor):
    home_lines = home_competitor.get("linescores", [])
    away_lines = away_competitor.get("linescores", [])
    home_ot = [_line_score_value(home_lines, index) for index in range(4, len(home_lines))]
    away_ot = [_line_score_value(away_lines, index) for index in range(4, len(away_lines))]
    quarters = _empty_quarters()
    quarters.update({
        "home_q1": _line_score_value(home_lines, 0),
        "home_q2": _line_score_value(home_lines, 1),
        "home_q3": _line_score_value(home_lines, 2),
        "home_q4": _line_score_value(home_lines, 3),
        "home_ot": _sum_optional_scores(*home_ot),
        "away_q1": _line_score_value(away_lines, 0),
        "away_q2": _line_score_value(away_lines, 1),
        "away_q3": _line_score_value(away_lines, 2),
        "away_q4": _line_score_value(away_lines, 3),
        "away_ot": _sum_optional_scores(*away_ot),
    })
    return quarters

# ─── nba_api ────────────────────────────────────────────────────────────────────

try:
    from nba_api.stats.endpoints import teamgamelog
    from nba_api.stats.static import teams as nba_teams_module
    HAS_NBA_API = True
except ImportError:
    HAS_NBA_API = False


def _get_team_by_abbreviation(abbreviation):
    """Get team info by abbreviation using nba_api static data."""
    if not HAS_NBA_API:
        return None
    nba_teams = nba_teams_module.get_teams()
    for team in nba_teams:
        if team["abbreviation"].upper() == abbreviation.upper():
            return team
    return None


# ─── nba_api method ─────────────────────────────────────────────────────────────

def _get_latest_game_nba_api(team_abbreviation, season=None):
    """Fetch latest game via nba_api (stats.nba.com)."""
    if not HAS_NBA_API:
        return None

    team = _get_team_by_abbreviation(team_abbreviation)
    if not team:
        return None

    if season is None:
        today = datetime.now()
        if today.month >= 10:
            season = f"{today.year}-{str(today.year + 1)[2:]}"
        else:
            season = f"{today.year - 1}-{str(today.year)[2:]}"

    # Try Playoffs first (short timeout), then Regular Season
    df = None
    for season_type in ["Playoffs", "Regular Season"]:
        try:
            game_log = teamgamelog.TeamGameLog(
                team_id=team["id"],
                season=season,
                season_type_all_star=season_type,
                timeout=5,
            )
            df = game_log.get_data_frames()[0]
            if not df.empty:
                break
        except Exception as e:
            # If timeout/connection error, don't retry another season_type
            # Just bail and let caller fall back to ESPN
            raise e

    if df is None or df.empty:
        return None

    latest = df.iloc[0]

    matchup = latest["MATCHUP"]
    is_home = "vs." in matchup

    if is_home:
        opponent_abbr = matchup.split("vs. ")[1].strip()
    else:
        opponent_abbr = matchup.split("@ ")[1].strip()

    opponent = _get_team_by_abbreviation(opponent_abbr)
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
        "quarters": _empty_quarters(),
    }


# ─── balldontlie method ─────────────────────────────────────────────────────────

def _get_latest_game_balldontlie(team_abbreviation, season=None):
    """Fetch latest game with period scores via balldontlie."""
    if not BALLDONTLIE_API_KEY:
        return None

    headers = {"Authorization": BALLDONTLIE_API_KEY}
    team_abbr = team_abbreviation.upper()

    team_id = BALLDONTLIE_TEAM_IDS.get(team_abbr)
    if not team_id:
        return None

    params = {
        "team_ids[]": team_id,
        "seasons[]": _parse_season_start_year(season),
        "per_page": 100,
    }
    resp = requests.get(
        f"{BALLDONTLIE_API_BASE}/games",
        headers=headers,
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    games = resp.json().get("data", [])
    latest = _select_latest_relevant_game(games)
    if not latest:
        return None

    home = latest["home_team"]
    visitor = latest["visitor_team"]
    home_score = latest["home_team_score"]
    visitor_score = latest["visitor_team_score"]
    is_final = _is_final_status(latest.get("status"))

    is_home = home.get("abbreviation", "").upper() == team_abbr
    if is_home:
        won = home_score > visitor_score
    else:
        won = visitor_score > home_score

    date_str = latest.get("date", "")
    try:
        game_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        game_date = date_str

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
        "result": ("W" if won else "L") if is_final else "",
        "is_home": is_home,
        "status": _normalize_game_status(latest.get("status")),
        "my_team": team_abbr,
        "quarters": _extract_balldontlie_quarters(latest),
        "_source": "balldontlie",
    }


# ─── ESPN fallback method ───────────────────────────────────────────────────────

def _get_latest_game_espn(team_abbreviation):
    """Fetch latest game via ESPN free API (fallback)."""
    team_abbr = team_abbreviation.upper()
    espn_slug = ESPN_TEAM_SLUGS.get(team_abbr)
    if not espn_slug:
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    url = f"{ESPN_API_BASE}/teams/{espn_slug}/schedule"
    resp = requests.get(url, headers=headers, timeout=15)

    if resp.status_code != 200:
        return None

    data = resp.json()
    events = data.get("events", [])
    if not events:
        return None

    live_games = [
        e for e in events
        if e.get("competitions", [{}])[0]
        .get("status", {}).get("type", {}).get("name") == "STATUS_IN_PROGRESS"
    ]
    if live_games:
        latest_event = max(live_games, key=_parse_espn_datetime)
    else:
        # Find the most recent completed game
        completed_games = [
            e for e in events
            if e.get("competitions", [{}])[0]
            .get("status", {}).get("type", {}).get("completed", False)
        ]

        if not completed_games:
            return None

        latest_event = max(completed_games, key=_parse_espn_datetime)

    comp = latest_event["competitions"][0]
    competitors = comp["competitors"]

    home_data = None
    away_data = None
    home_competitor = None
    away_competitor = None
    for competitor in competitors:
        team_info = competitor["team"]
        entry = {
            "name": team_info.get("displayName", team_info.get("name", "")),
            "abbreviation": team_info.get("abbreviation", ""),
            "score": _parse_espn_score(competitor.get("score", {})),
        }

        if competitor["homeAway"] == "home":
            home_data = entry
            home_competitor = competitor
            home_data["_winner"] = competitor.get("winner", False)
        else:
            away_data = entry
            away_competitor = competitor
            away_data["_winner"] = competitor.get("winner", False)

    if not home_data or not away_data:
        return None

    is_home = home_data["abbreviation"].upper() == team_abbr
    status_type = comp.get("status", {}).get("type", {})
    is_final = bool(status_type.get("completed"))
    if is_home:
        result = "W" if home_data.get("_winner") else "L"
    else:
        result = "W" if away_data.get("_winner") else "L"
    if not is_final:
        result = ""

    # Format date
    game_date_raw = latest_event.get("date", "")
    try:
        dt = datetime.fromisoformat(game_date_raw.replace("Z", "+00:00"))
        game_date = dt.strftime("%b %d, %Y")
    except (ValueError, AttributeError):
        game_date = game_date_raw

    # Status
    if is_final:
        status = "Final"
    elif status_type.get("name") == "STATUS_IN_PROGRESS":
        status = "Live"
    else:
        status = status_type.get("shortDetail", "Scheduled")

    home_data.pop("_winner", None)
    away_data.pop("_winner", None)

    return {
        "home_team": home_data,
        "away_team": away_data,
        "game_date": game_date,
        "result": result,
        "is_home": is_home,
        "status": status,
        "my_team": team_abbr,
        "quarters": _extract_espn_quarters(home_competitor, away_competitor),
        "_source": "espn",
    }


def get_latest_game_espn(team_abbreviation):
    """Fetch the live game when available, otherwise the most recent completed game."""
    return _get_latest_game_espn(team_abbreviation)


def get_latest_game_balldontlie(team_abbreviation, season=None):
    """Fetch the live game when available, otherwise the most recent completed game."""
    return _get_latest_game_balldontlie(team_abbreviation, season)


# ─── Public API ─────────────────────────────────────────────────────────────────

def get_latest_game(team_abbreviation, season=None):
    """
    Get the most recent game for a team.
    Tries nba_api first, falls back to ESPN if it fails.

    Args:
        team_abbreviation: NBA team abbreviation (e.g., 'LAL', 'GSW', 'BOS')
        season: Season string like '2024-25'. Auto-detected if not provided.

    Returns a dict with:
        - home_team: dict with name, abbreviation, score
        - away_team: dict with name, abbreviation, score
        - game_date: formatted date string
        - result: 'W' or 'L' (from perspective of the requested team)
        - is_home: whether the requested team was the home team
        - status: 'Final', 'Live', etc.
        - my_team: the requested team abbreviation
        - quarters: dict with Q1-Q4/OT values when balldontlie is available
    """
    # Prefer balldontlie when configured because it includes period scores.
    if BALLDONTLIE_API_KEY:
        try:
            result = _get_latest_game_balldontlie(team_abbreviation, season)
            if result:
                print("Using balldontlie data source")
                return result
        except Exception as e:
            print(f"balldontlie failed: {e}, falling back to nba_api/ESPN")

    # Try nba_api first
    if HAS_NBA_API:
        try:
            result = _get_latest_game_nba_api(team_abbreviation, season)
            if result:
                return result
        except Exception as e:
            print(f"nba_api failed: {e}, falling back to ESPN")

    # Fallback to ESPN
    try:
        result = _get_latest_game_espn(team_abbreviation)
        if result:
            print("Using ESPN fallback data source")
            return result
    except Exception as e:
        print(f"ESPN fallback also failed: {e}")

    return None


def get_all_team_abbreviations():
    """Return all valid NBA team abbreviations."""
    if HAS_NBA_API:
        nba_teams = nba_teams_module.get_teams()
        return sorted([t["abbreviation"] for t in nba_teams])
    return sorted(ESPN_TEAM_SLUGS.keys())
