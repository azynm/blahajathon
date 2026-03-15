"""
Scoring system for CoLeague.
Calculates player scores based on Discord and GitHub activity.
"""
import json
import os
import math
from datetime import datetime, timedelta
from collections import defaultdict

SCORES_FILE = "scores.json"

# Map every known alias (lowercase) to a canonical display name
PLAYER_ALIASES = {
    "azynm": "Zayn",
    "zayn": "Zayn",
    "lackshaj": "Lacksha",
    "lacksha.": "Lacksha",
    "lacksha": "Lacksha",
    "aadideepchand20": "Aadi",
    "aadi deepchand": "Aadi",
    "aadi": "Aadi",
    "sophacode": "Sophia",
    "soph.advinc": "Sophia",
    "soupdewoop": "Sophia",
}


def resolve_player(name):
    """Resolve a raw username to a canonical player name."""
    return PLAYER_ALIASES.get(name.lower(), None)


def load_scores():
    """Load scores from JSON file."""
    if os.path.exists(SCORES_FILE):
        with open(SCORES_FILE, "r") as f:
            return json.load(f)
    return {"players": {}, "branches_claimed": {}, "last_updated": None}


def save_scores(data):
    """Save scores to JSON file."""
    data["last_updated"] = datetime.now().isoformat()
    with open(SCORES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def ensure_player(data, player_id, discord_id=None, github_id=None):
    """Ensure a player exists in the scores data."""
    if player_id not in data["players"]:
        data["players"][player_id] = {
            "discord_id": discord_id or player_id,
            "github_id": github_id or player_id,
            "display_name": None,
            "overall": 0,
            "discord_score": 0,
            "git_score": 0,
            "recent_record": [],  # Last 5: "good", "bad", "neutral"
            "stats": {
                "messages_sent": 0,
                "positive_mentions": 0,
                "negative_mentions": 0,
                "commits": 0,
                "merges": 0,
                "merge_conflicts": 0,
                "main_commits": 0,
                "branches_used": [],
            }
        }
    return data["players"][player_id]


def set_display_name(canonical_name, display_name):
    """Set a custom display name for a player."""
    data = load_scores()
    if canonical_name in data["players"]:
        data["players"][canonical_name]["display_name"] = display_name
        save_scores(data)
        return True
    return False


# =============================================================================
# DISCORD SCORING
# =============================================================================

def calculate_discord_scores(messages, sentiment_result):
    """
    Calculate Discord scores for all players from messages.

    Args:
        messages: List of message dicts with author, content, timestamp
        sentiment_result: Dict with 'overall' and 'highlights' from analyse_sentiment

    Returns:
        Dict of {player_id: score_delta}
    """
    scores = defaultdict(int)
    stats = defaultdict(lambda: defaultdict(int))

    # Group messages by author
    messages_by_author = defaultdict(list)
    for msg in messages:
        author = msg["author"]
        messages_by_author[author].append(msg)

    for author, author_messages in messages_by_author.items():
        # Base message score: +1 per message
        msg_count = len(author_messages)
        scores[author] += msg_count * 1
        stats[author]["messages"] = msg_count

        # Spam detection: check for similar consecutive messages
        spam_penalty = calculate_spam_penalty(author_messages)
        scores[author] += spam_penalty
        stats[author]["spam_penalty"] = spam_penalty

        # Reply time bonus (exponential decay)
        reply_bonus = calculate_reply_bonus(author_messages, messages)
        scores[author] += reply_bonus
        stats[author]["reply_bonus"] = reply_bonus

    # Positive/Negative mentions from highlights
    highlights = sentiment_result.get("highlights", [])
    mention_scores = parse_highlights_for_mentions(highlights)
    for player, delta in mention_scores.items():
        scores[player] += delta
        if delta > 0:
            stats[player]["positive_mentions"] += 1
        else:
            stats[player]["negative_mentions"] += 1

    return dict(scores), dict(stats)


def calculate_spam_penalty(author_messages):
    """
    Calculate spam penalty based on message similarity.
    Returns value between -6 and 0.
    """
    if len(author_messages) < 3:
        return 0

    # Sort by timestamp
    sorted_msgs = sorted(author_messages, key=lambda m: m["timestamp"])

    # Check for rapid-fire similar messages
    similar_count = 0
    for i in range(1, len(sorted_msgs)):
        prev_content = sorted_msgs[i-1]["content"].lower().strip()
        curr_content = sorted_msgs[i]["content"].lower().strip()

        # Simple similarity: same message or very short messages in rapid succession
        if prev_content == curr_content and len(curr_content) < 20:
            similar_count += 1
        elif len(prev_content) < 5 and len(curr_content) < 5:
            similar_count += 0.5

    # Scale penalty: -2 to -6 based on spam ratio
    spam_ratio = similar_count / len(sorted_msgs)
    if spam_ratio > 0.5:
        return -6
    elif spam_ratio > 0.3:
        return -4
    elif spam_ratio > 0.1:
        return -2
    return 0


def calculate_reply_bonus(author_messages, all_messages):
    """
    Calculate reply time bonus with exponential decay.
    Fast replies get more points, cannot go negative.
    """
    # For now, simplified: +2 if they responded within 5 minutes, +1 within 15min
    # Full implementation would track reply chains
    bonus = 0

    sorted_all = sorted(all_messages, key=lambda m: m["timestamp"])
    author_timestamps = set(m["timestamp"] for m in author_messages)

    for i, msg in enumerate(sorted_all):
        if msg["timestamp"] in author_timestamps and i > 0:
            prev_msg = sorted_all[i-1]
            if prev_msg["author"] != msg["author"]:
                try:
                    prev_time = datetime.fromisoformat(prev_msg["timestamp"].replace("+00:00", ""))
                    curr_time = datetime.fromisoformat(msg["timestamp"].replace("+00:00", ""))
                    diff_minutes = (curr_time - prev_time).total_seconds() / 60

                    # Exponential decay: fast replies worth more
                    if diff_minutes < 1:
                        bonus += 3
                    elif diff_minutes < 5:
                        bonus += 2
                    elif diff_minutes < 15:
                        bonus += 1
                except:
                    pass

    return min(bonus, 10)  # Cap at 10


def parse_highlights_for_mentions(highlights):
    """
    Parse highlights to determine positive/negative mentions.
    Returns {player: score_delta}
    """
    scores = {}

    positive_keywords = ["encouraged", "helped", "supported", "praised", "thanked", "positive", "productive"]
    negative_keywords = ["insulted", "threatened", "angry", "toxic", "rant", "conflict", "slur", "attack"]

    for highlight in highlights:
        highlight_lower = highlight.lower()

        # Try to extract player name (usually at the start)
        words = highlight.split()
        if not words:
            continue

        # First word is often the player name
        player = words[0].rstrip(",.:!")

        # Determine sentiment
        is_positive = any(kw in highlight_lower for kw in positive_keywords)
        is_negative = any(kw in highlight_lower for kw in negative_keywords)

        if is_negative:
            scores[player] = scores.get(player, 0) - 8
        elif is_positive:
            scores[player] = scores.get(player, 0) + 5

    return scores


# =============================================================================
# GIT SCORING
# =============================================================================

def calculate_git_scores(github_data, branches_claimed):
    """
    Calculate Git scores for all players from GitHub data.

    Args:
        github_data: List of dicts from get_detailed_github_data
        branches_claimed: Dict tracking which branches have been claimed {branch: player}

    Returns:
        Tuple of (scores_dict, stats_dict, updated_branches_claimed)
    """
    scores = defaultdict(int)
    stats = defaultdict(lambda: defaultdict(int))

    for item in github_data:
        author = item.get("author", "unknown")
        item_type = item.get("type")

        if item_type == "commit":
            message = item.get("message", "").lower()

            # Check if commit to main (usually indicated by merge message or branch info)
            if "merge" not in message:
                # Regular commit: +2
                scores[author] += 2
                stats[author]["commits"] += 1

        elif item_type == "merge":
            message = item.get("message", "").lower()

            # Check for merge to main
            if "main" in message or "master" in message:
                # Check if it's a direct commit to main (bad) or a merge (ok)
                if "merge pull request" in message or "merge branch" in message:
                    # Good merge: +5
                    scores[author] += 5
                    stats[author]["good_merges"] += 1
                else:
                    # Direct commit to main: -20
                    scores[author] -= 20
                    stats[author]["main_commits"] += 1

        elif item_type == "merge_request":
            source_branch = item.get("source_branch", "")
            target_branch = item.get("target_branch", "")

            # Branch usage bonus: +10 for new branch (once per branch)
            if source_branch and source_branch not in branches_claimed:
                branches_claimed[source_branch] = author
                scores[author] += 10
                stats[author]["new_branches"] = stats[author].get("new_branches", 0) + 1

            # Merged PR: +5
            scores[author] += 5
            stats[author]["prs_merged"] = stats[author].get("prs_merged", 0) + 1

            # Approvers get points too
            for approver in item.get("approvers", []):
                scores[approver] += 2
                stats[approver]["reviews"] = stats[approver].get("reviews", 0) + 1

    return dict(scores), dict(stats), branches_claimed


# =============================================================================
# MAIN SCORING FUNCTION
# =============================================================================

def update_scores(discord_messages, sentiment_result, github_data):
    """
    Main function to update all player scores.

    Args:
        discord_messages: List of Discord messages
        sentiment_result: Result from analyse_sentiment
        github_data: Result from get_detailed_github_data

    Returns:
        Updated scores data dict
    """
    data = load_scores()

    # Calculate Discord scores
    discord_scores, discord_stats = calculate_discord_scores(discord_messages, sentiment_result)

    # Calculate Git scores
    branches_claimed = data.get("branches_claimed", {})
    git_scores, git_stats, branches_claimed = calculate_git_scores(github_data, branches_claimed)
    data["branches_claimed"] = branches_claimed

    # Combine all players, resolving aliases and skipping unknowns
    all_raw = set(discord_scores.keys()) | set(git_scores.keys())

    # Aggregate scores by canonical name
    resolved_discord = defaultdict(int)
    resolved_git = defaultdict(int)
    resolved_discord_stats = defaultdict(lambda: defaultdict(int))
    resolved_git_stats = defaultdict(lambda: defaultdict(int))

    for raw in all_raw:
        canonical = resolve_player(raw)
        if not canonical:
            continue
        resolved_discord[canonical] += discord_scores.get(raw, 0)
        resolved_git[canonical] += git_scores.get(raw, 0)
        for key, value in discord_stats.get(raw, {}).items():
            resolved_discord_stats[canonical][key] += value
        for key, value in git_stats.get(raw, {}).items():
            resolved_git_stats[canonical][key] += value

    all_players = set(resolved_discord.keys()) | set(resolved_git.keys())

    for player in all_players:
        p = ensure_player(data, player)

        # Add deltas to scores
        p["discord_score"] += resolved_discord.get(player, 0)
        p["git_score"] += resolved_git.get(player, 0)
        p["overall"] = p["discord_score"] + p["git_score"]

        # Update stats
        for key, value in resolved_discord_stats.get(player, {}).items():
            p["stats"][key] = p["stats"].get(key, 0) + value
        for key, value in resolved_git_stats.get(player, {}).items():
            p["stats"][key] = p["stats"].get(key, 0) + value

    # Update recent record based on overall sentiment
    overall_sentiment = sentiment_result.get("overall", "neutral")
    record_entry = "good" if overall_sentiment == "positive" else "bad" if overall_sentiment in ("toxic", "highly toxic") else "neutral"

    # Add to each mentioned player's recent record
    highlights = sentiment_result.get("highlights", [])
    for highlight in highlights:
        words = highlight.split()
        if words:
            raw_name = words[0].rstrip(",.:!")
            player = resolve_player(raw_name)
            if player and player in data["players"]:
                data["players"][player]["recent_record"].append(record_entry)
                data["players"][player]["recent_record"] = data["players"][player]["recent_record"][-5:]

    save_scores(data)
    return data


def get_leaderboard():
    """Get sorted leaderboard of all players."""
    data = load_scores()
    players = data.get("players", {})

    leaderboard = []
    for player_id, info in players.items():
        stats = info.get("stats", {})
        leaderboard.append({
            "id": player_id,
            "name": info.get("display_name") or player_id,
            "overall_points": info["overall"],
            "discord_score": info["discord_score"],
            "git_score": info["git_score"],
            "recent_record": info["recent_record"][-5:],
            "stats": {
                "commits": stats.get("commits", 0),
                "merge_approvals": stats.get("reviews", 0),
                "positive_messages": stats.get("positive_mentions", 0),
                "negative_messages": stats.get("negative_mentions", 0),
                "response_time_mins": stats.get("reply_bonus", 0),
                "spam_score": abs(stats.get("spam_penalty", 0)),
                "branch_usage": stats.get("new_branches", 0),
            },
        })

    sorted_board = sorted(leaderboard, key=lambda x: x["overall_points"], reverse=True)
    for i, player in enumerate(sorted_board):
        player["rank"] = i + 1
    return sorted_board


def get_scores_last_updated():
    """Return a human-friendly timestamp for when scores were last persisted."""
    data = load_scores()
    raw = data.get("last_updated")
    if not raw:
        return "Not updated yet"

    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw
