"""GitHub webhook processing and league-table scoring for Git metrics only."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# Return the current time in UTC so all stored timestamps are consistent.
def _utc_now() -> datetime:
	return datetime.now(timezone.utc)


# Parse a GitHub ISO8601 timestamp string into a datetime object.
# Example input: "2026-03-14T10:30:22Z".
def _parse_dt(value: str | None) -> datetime | None:
	if not value:
		return None
	# GitHub timestamps are ISO8601, often ending in Z.
	return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class UserStats:
	# Total number of commits attributed to this user.
	commits: int = 0
	# Number of PR approvals the user submitted.
	merge_approvals: int = 0
	# Placeholder for future Discord sentiment integration.
	positive_messages: int = 0
	# Placeholder for future Discord sentiment integration.
	negative_messages: int = 0
	# Number of activity events seen for this user (push, PR open, etc.).
	activity_events: int = 0
	# Number of times user tripped the anti-spam heuristic.
	spam_events: int = 0
	# Count of branch-related usage events for this user.
	branch_usage: int = 0
	# Aggregated points used for ranking.
	points: float = 0.0
	# PR response times (in seconds), optionally scaled by admin time factor.
	response_times_seconds: list[float] = field(default_factory=list)
	# Recent commit messages for display/inspection.
	commit_names: list[str] = field(default_factory=list)
	# Last observed activity timestamp for inactivity calculations.
	last_activity_at: datetime | None = None


class GitLeagueEngine:
	"""Consumes GitHub webhook events and updates in-memory league metrics."""

	def __init__(self) -> None:
		# Map username -> cumulative stats.
		self.users: dict[str, UserStats] = defaultdict(UserStats)
		# Rolling event log (newest at end) for debugging/visualization.
		self.logs: deque[dict[str, Any]] = deque(maxlen=500)
		# Cache PR open timestamps to compute response time at merge.
		self.pr_opened_at: dict[int, datetime] = {}
		# Per-user event timestamps used for spam detection in a short window.
		self.event_window_by_user: dict[str, deque[datetime]] = defaultdict(deque)

		# Admin controls.
		# Multiplies time-based metrics (inactivity and response-time values).
		self.time_scale: float = 1.0
		# If set in the future, score multiplier is doubled (Crunch Mode).
		self.crunch_mode_until: datetime | None = None

	# Return active points multiplier (2x during crunch mode, otherwise 1x).
	def _multiplier(self, now: datetime) -> float:
		if self.crunch_mode_until and now <= self.crunch_mode_until:
			return 2.0
		return 1.0

	# Enable Crunch Mode for a given duration. During this time, points are doubled.
	def start_crunch_mode(self, hours: int = 48) -> dict[str, Any]:
		now = _utc_now()
		self.crunch_mode_until = now + timedelta(hours=hours)
		return {
			"enabled": True,
			"until": self.crunch_mode_until.isoformat(),
			"multiplier": 2.0,
		}

	# Set PM-controlled time scaling for time-based metrics.
	def set_time_scale(self, scale: float) -> dict[str, Any]:
		if scale <= 0:
			raise ValueError("Time scale must be greater than 0")
		self.time_scale = scale
		return {"time_scale": self.time_scale}

	# Record that a user was active now and update spam counters.
	def _mark_activity(self, username: str, now: datetime) -> None:
		user = self.users[username]
		user.activity_events += 1
		user.last_activity_at = now

		# Simple spam heuristic: more than 10 events in 2 minutes.
		window = self.event_window_by_user[username]
		window.append(now)
		cutoff = now - timedelta(minutes=2)
		while window and window[0] < cutoff:
			window.popleft()
		if len(window) > 10:
			user.spam_events += 1

	# Add points to a user with the current global multiplier applied.
	def _add_points(self, username: str, base_points: float, now: datetime) -> None:
		self.users[username].points += base_points * self._multiplier(now)

	# Entry point: route each incoming GitHub webhook event to its handler.
	def process_event(self, event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
		"""Main router for GitHub webhook event payloads."""
		now = _utc_now()

		if event_name == "push":
			return self._handle_push(payload, now)
		if event_name == "create":
			return self._handle_branch_create(payload, now)
		if event_name == "delete":
			return self._handle_branch_delete(payload, now)
		if event_name == "pull_request":
			return self._handle_pull_request(payload, now)
		if event_name == "pull_request_review":
			return self._handle_pull_request_review(payload, now)

		return {"status": "ignored", "event": event_name}

	# Handle push events:
	# - count commits
	# - track commit messages
	# - score points
	# - count changed files for impact context
	def _handle_push(self, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
		pusher = payload.get("pusher", {}).get("name") or "unknown"
		commits = payload.get("commits", [])
		ref = payload.get("ref", "")
		branch = ref.split("/")[-1] if ref else "unknown"

		self._mark_activity(pusher, now)

		user = self.users[pusher]
		user.commits += len(commits)
		user.branch_usage += 1
		self._add_points(pusher, 10 * len(commits), now)

		# Build per-push summary data.
		commit_messages: list[str] = []
		changed_files_total = 0
		for commit in commits:
			# Keep commit names for UI and human-readable context.
			msg = commit.get("message", "")
			if msg:
				user.commit_names.append(msg)
				commit_messages.append(msg)

			# Count file-level impact for added/removed/modified files.
			# Note: this is file count impact, not line count impact.
			# For line-level impact we'd need additional API calls or payload fields.
			# Kept intentionally simple for real-time processing.
			added = commit.get("added") or []
			removed = commit.get("removed") or []
			modified = commit.get("modified") or []
			changed_files_total += len(added) + len(removed) + len(modified)

		# Append a compact event log entry for later replay/UI display.
		self.logs.append(
			{
				"kind": "push",
				"at": now.isoformat(),
				"user": pusher,
				"branch": branch,
				"commit_count": len(commits),
				"changed_files": changed_files_total,
				"commit_messages": commit_messages,
			}
		)

		# Return a compact processing summary for API response.
		return {
			"status": "processed",
			"event": "push",
			"user": pusher,
			"branch": branch,
			"commit_count": len(commits),
		}

	# Handle branch create events and award small branch-usage points.
	def _handle_branch_create(self, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
		if payload.get("ref_type") != "branch":
			return {"status": "ignored", "event": "create", "reason": "not-branch"}

		creator = payload.get("sender", {}).get("login") or "unknown"
		branch_name = payload.get("ref") or "unknown"

		self._mark_activity(creator, now)
		self.users[creator].branch_usage += 1
		self._add_points(creator, 5, now)

		# Log this branch creation action.
		self.logs.append(
			{
				"kind": "branch_create",
				"at": now.isoformat(),
				"user": creator,
				"branch": branch_name,
			}
		)

		return {
			"status": "processed",
			"event": "create",
			"user": creator,
			"branch": branch_name,
		}

	# Handle branch delete events. We log activity but do not alter points currently.
	def _handle_branch_delete(self, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
		if payload.get("ref_type") != "branch":
			return {"status": "ignored", "event": "delete", "reason": "not-branch"}

		actor = payload.get("sender", {}).get("login") or "unknown"
		branch_name = payload.get("ref") or "unknown"

		# Branch deletion still counts as an activity touchpoint.
		self._mark_activity(actor, now)
		self.logs.append(
			{
				"kind": "branch_delete",
				"at": now.isoformat(),
				"user": actor,
				"branch": branch_name,
			}
		)

		return {
			"status": "processed",
			"event": "delete",
			"user": actor,
			"branch": branch_name,
		}

	# Handle pull request events for open and merged flows.
	def _handle_pull_request(self, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
		action = payload.get("action")
		pr = payload.get("pull_request", {})
		pr_number = pr.get("number")
		pr_user = pr.get("user", {}).get("login") or "unknown"

		self._mark_activity(pr_user, now)

		if action == "opened" and pr_number is not None:
			# Cache open timestamp so merged event can compute response time.
			opened_at = _parse_dt(pr.get("created_at")) or now
			self.pr_opened_at[int(pr_number)] = opened_at
			# Reward opening a PR.
			self._add_points(pr_user, 10, now)
			self.logs.append(
				{
					"kind": "pr_opened",
					"at": now.isoformat(),
					"user": pr_user,
					"pr_number": pr_number,
				}
			)
			return {"status": "processed", "event": "pull_request", "action": action}

		if action == "closed" and pr.get("merged"):
			# Sender here is typically the actor that triggered merge/close.
			merger = payload.get("sender", {}).get("login") or "unknown"
			self._mark_activity(merger, now)
			# Reward both PR author and merger.
			self._add_points(pr_user, 30, now)
			self._add_points(merger, 15, now)

			# Prefer cached opened time, fallback to payload if needed.
			opened_at = None
			if pr_number is not None:
				opened_at = self.pr_opened_at.pop(int(pr_number), None)
			opened_at = opened_at or _parse_dt(pr.get("created_at"))
			closed_at = _parse_dt(pr.get("closed_at")) or now

			# Compute and store scaled response time in seconds.
			response_seconds: float | None = None
			if opened_at:
				response_seconds = max((closed_at - opened_at).total_seconds(), 0.0)
				# Time scaling lets PM simulate faster/slower project timelines.
				scaled = response_seconds * self.time_scale
				self.users[pr_user].response_times_seconds.append(scaled)

			# Keep a merge log event for commentator/UI timeline.
			self.logs.append(
				{
					"kind": "pr_merged",
					"at": now.isoformat(),
					"user": pr_user,
					"merged_by": merger,
					"pr_number": pr_number,
					"response_time_seconds": response_seconds,
				}
			)
			return {"status": "processed", "event": "pull_request", "action": action}

		# For other PR actions, we acknowledge but do not score yet.
		return {"status": "processed", "event": "pull_request", "action": action}

	# Handle review submissions and count approvals.
	def _handle_pull_request_review(self, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
		action = payload.get("action")
		review = payload.get("review", {})
		state = review.get("state")

		if action == "submitted" and state == "approved":
			reviewer = review.get("user", {}).get("login") or "unknown"
			self._mark_activity(reviewer, now)
			# Approval contributes to merge-approval metric and points.
			self.users[reviewer].merge_approvals += 1
			self._add_points(reviewer, 20, now)
			self.logs.append(
				{
					"kind": "pr_approval",
					"at": now.isoformat(),
					"user": reviewer,
				}
			)
			return {
				"status": "processed",
				"event": "pull_request_review",
				"action": action,
				"state": state,
			}

		# Non-approved review states are currently tracked only as processed.
		return {
			"status": "processed",
			"event": "pull_request_review",
			"action": action,
			"state": state,
		}

	# Build ranked leaderboard rows from current in-memory stats.
	def leaderboard(self) -> list[dict[str, Any]]:
		rows: list[dict[str, Any]] = []
		now = _utc_now()

		for username, stats in self.users.items():
			# Average PR response time for this user (if any PR timings exist).
			avg_response = (
				sum(stats.response_times_seconds) / len(stats.response_times_seconds)
				if stats.response_times_seconds
				else None
			)
			# Time since last observed activity, scaled by PM time factor.
			inactivity_seconds = None
			if stats.last_activity_at:
				inactivity_seconds = max((now - stats.last_activity_at).total_seconds(), 0.0)
				inactivity_seconds *= self.time_scale

			# Keep response shape stable for frontend/UI usage.
			rows.append(
				{
					"user": username,
					"points": round(stats.points, 2),
					"commits": stats.commits,
					"merge_approvals": stats.merge_approvals,
					"positive_messages": stats.positive_messages,
					"negative_messages": stats.negative_messages,
					"activity": stats.activity_events,
					"inactivity_seconds": inactivity_seconds,
					"avg_response_time_seconds": avg_response,
					"spam": stats.spam_events,
					"branch_usage": stats.branch_usage,
					"recent_commit_names": stats.commit_names[-10:],
				}
			)

		# Sort descending by points and assign rank numbers.
		rows.sort(key=lambda item: item["points"], reverse=True)
		for idx, row in enumerate(rows, start=1):
			row["rank"] = idx
		return rows

	# Return recent logs with a safety clamp to protect memory and response size.
	def recent_logs(self, limit: int = 50) -> list[dict[str, Any]]:
		size = max(1, min(limit, 500))
		return list(self.logs)[-size:]

	# Return engine-level status metadata for health/debug output.
	def status(self) -> dict[str, Any]:
		now = _utc_now()
		return {
			"users_tracked": len(self.users),
			"time_scale": self.time_scale,
			"crunch_mode": {
				"enabled": bool(self.crunch_mode_until and now <= self.crunch_mode_until),
				"until": self.crunch_mode_until.isoformat() if self.crunch_mode_until else None,
			},
		}