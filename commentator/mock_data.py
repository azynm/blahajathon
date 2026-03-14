# frontend/mock_data.py

MOCK_EVENTS_SCENARIO_1 = {
    "recent_commits": [
        {"author": "Zayn", "message": "fixed the catastrophic memory leak in prod", "lines_changed": 420},
        {"author": "Alex", "message": "typo in readme", "lines_changed": 2}
    ],
    "pull_requests_merged": 1,
    "discord_sentiment": "highly toxic",
    "discord_spam_count": 45
}

MOCK_EVENTS_SCENARIO_2 = {
    "recent_commits": [
        {"author": "Sarah", "message": "Refactored the entire authentication flow", "lines_changed": 1500},
        {"author": "Mike", "message": "added unit tests for auth", "lines_changed": 300}
    ],
    "pull_requests_merged": 3,
    "discord_sentiment": "extremely positive and hype",
    "discord_spam_count": 2
}

MOCK_EVENTS_SCENARIO_3 = {
    "recent_commits": [
        {"author": "Dave", "message": "oops rolled back previous commit", "lines_changed": 1500},
        {"author": "Dave", "message": "quick fix", "lines_changed": 10},
        {"author": "Dave", "message": "another quick fix", "lines_changed": 5}
    ],
    "pull_requests_merged": 0,
    "discord_sentiment": "panicking",
    "discord_spam_count": 120
}

ALL_SCENARIOS = {
    "Scenario 1: The Carry and the Slacker": MOCK_EVENTS_SCENARIO_1,
    "Scenario 2: The Dream Team": MOCK_EVENTS_SCENARIO_2,
    "Scenario 3: The Panic Mode": MOCK_EVENTS_SCENARIO_3,
}
