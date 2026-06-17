import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, Response, request, render_template
import re

from generate import fetch_espn_event_id, fetch_player_leaders, fetch_team_logo_b64
from util.nba import get_latest_game, get_all_team_abbreviations

app = Flask(__name__)


@app.route("/api/nba")
def nba_card():
    """
    Generate an SVG card showing the latest game score for a given NBA team.

    Query parameters:
        - team (required): NBA team abbreviation (e.g., LAL, GSW, BOS)
        - theme: card theme (default: "default")
        - background_color: hex color for background (default: "161b22")
        - accent_color: hex color for accent elements (default: "c9510c")
        - border_radius: card corner radius in px (default: "10")
        - season: NBA season string e.g. "2024-25" (default: auto-detect)
    """
    team = request.args.get("team")
    theme = request.args.get("theme", default="default")
    background_color = request.args.get("background_color", default="161b22")
    accent_color = request.args.get("accent_color", default="c9510c")
    border_radius = request.args.get("border_radius", default="10")
    season = request.args.get("season", default=None)

    # Validate team parameter
    if not team:
        return Response(
            "Error: 'team' parameter is required. Example: /api/nba?team=LAL",
            status=400,
        )

    team = team.upper()
    valid_teams = get_all_team_abbreviations()
    if team not in valid_teams:
        return Response(
            f"Error: Invalid team abbreviation '{team}'. Valid options: {', '.join(sorted(valid_teams))}",
            status=400,
        )

    # Validate border_radius
    if not re.match(r"^\d+$", border_radius):
        border_radius = "10"

    # Fetch game data
    game = get_latest_game(team, season=season)
    leaders = {}
    away_logo = ""
    home_logo = ""
    if game:
        away_logo = fetch_team_logo_b64(game["away_team"]["abbreviation"])
        home_logo = fetch_team_logo_b64(game["home_team"]["abbreviation"])
        event_id = fetch_espn_event_id(
            game["game_date"],
            game["home_team"]["abbreviation"],
            game["away_team"]["abbreviation"],
        )
        if event_id:
            leaders = fetch_player_leaders(event_id) or {}

    # Determine text colors based on background
    text_color = "e6edf3"
    title_color = "c9d1d9"

    # Render SVG
    svg = render_template(
        f"nba.{theme}.html.j2",
        game=game,
        leaders=leaders,
        away_logo=away_logo,
        home_logo=home_logo,
        background_color=background_color,
        accent_color=accent_color,
        text_color=text_color,
        title_color=title_color,
        border_radius=border_radius,
    )

    resp = Response(svg, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "s-maxage=300"  # Cache for 5 minutes
    return resp


@app.route("/api/nba/teams")
def list_teams():
    """List all valid NBA team abbreviations."""
    teams = get_all_team_abbreviations()
    return Response(
        "Valid NBA team abbreviations:\n" + ", ".join(sorted(teams)),
        mimetype="text/plain",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5005)
