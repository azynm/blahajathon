from __future__ import annotations
from datetime import datetime
from flask import Flask, render_template


import hashlib
import hmac
import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request

from github_logic import GitLeagueEngine

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True


def _load_players() -> list[dict]:
	players_path = Path(__file__).resolve().parent / "players.json"
	if not players_path.exists():
		return []

	with players_path.open("r", encoding="utf-8") as file:
		data = json.load(file)

	if not isinstance(data, list):
		return []

	return data


def _build_current_user() -> dict[str, str]:
	return {
		"name": "Jordan Rivera",
		"role": "Project Captain",
	}

@app.route("/")
def home():
	players = _load_players()
	current_user = _build_current_user()
	last_updated = datetime.now().strftime("%b %d, %Y %I:%M %p")
	return render_template(
		"index.html",
		players=players,
		current_user=current_user,
		last_updated=last_updated,
	)

if __name__ == "__main__":
    app.run(debug=True)
	
"""Main API entrypoint for Git integration webhook and league table endpoints."""


# Create the FastAPI app instance.
# The title/version appear in OpenAPI docs at /docs.
app = FastAPI(title="Hackathon League API", version="0.1.0")

# Single in-memory engine instance used by all requests.
# This keeps live state while the process is running.
engine = GitLeagueEngine()


# Verify GitHub webhook signature when a secret is configured.
# If no secret is configured, signature verification is skipped
# (useful for local testing with tools like ngrok).
def _verify_signature(raw_body: bytes, provided_signature: str | None) -> None:
	secret = os.getenv("GITHUB_WEBHOOK_SECRET")
	if not secret:
		# Secret is optional during local testing.
		return

	# GitHub signs requests in X-Hub-Signature-256 header.
	if not provided_signature:
		raise HTTPException(status_code=401, detail="Missing webhook signature")

	# Compute expected HMAC digest for this raw request body.
	expected = "sha256=" + hmac.new(
		key=secret.encode("utf-8"),
		msg=raw_body,
		digestmod=hashlib.sha256,
	).hexdigest()

	# Constant-time comparison to avoid timing attacks.
	if not hmac.compare_digest(expected, provided_signature):
		raise HTTPException(status_code=401, detail="Invalid webhook signature")


# Validate project-manager/admin access for control endpoints.
# Admin token is expected via request header.
def _require_admin(admin_token: str | None) -> None:
	expected = os.getenv("ADMIN_TOKEN")
	if not expected:
		raise HTTPException(status_code=500, detail="ADMIN_TOKEN not configured")
	if admin_token != expected:
		raise HTTPException(status_code=403, detail="Admin privileges required")


# Root endpoint: quick smoke-check and service identification.
@app.get("/")
async def root() -> dict[str, str]:
	return {"service": "git-integration", "status": "ok"}


# Health endpoint: simple heartbeat for uptime checks.
@app.get("/health")
async def health() -> dict[str, str]:
	return {"status": "healthy"}


# Main GitHub webhook ingestion endpoint.
# GitHub sends event type in X-GitHub-Event and JSON payload in body.
@app.post("/github-webhook")
async def github_webhook(
	request: Request,
	x_github_event: str | None = Header(default=None),
	x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, object]:
	# Event header is required to know how to route payload.
	if not x_github_event:
		raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

	# Read raw bytes first so we can both verify signature and parse JSON.
	raw_body = await request.body()
	_verify_signature(raw_body, x_hub_signature_256)

	try:
		# Parse request body into Python dict.
		payload = json.loads(raw_body.decode("utf-8"))
	except json.JSONDecodeError as exc:
		raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

	# GitHub sends ping event when webhook is first configured.
	if x_github_event == "ping":
		return {"status": "success", "event": "ping"}

	# Delegate event-specific processing to GitLeagueEngine.
	result = engine.process_event(x_github_event, payload)
	return {
		"status": "success",
		"received_event": x_github_event,
		"result": result,
		"engine": engine.status(),
	}


# Return current ranked league table and engine metadata.
@app.get("/git/leaderboard")
async def git_leaderboard() -> dict[str, object]:
	return {
		"status": "success",
		"engine": engine.status(),
		"leaderboard": engine.leaderboard(),
	}


# Return recent raw/parsed Git event logs for debugging or commentator feed.
@app.get("/git/logs")
async def git_logs(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
	return {
		"status": "success",
		"count": limit,
		"logs": engine.recent_logs(limit=limit),
	}


# Admin endpoint to enable Crunch Mode.
# During Crunch Mode, scoring multiplier is 2x for the chosen duration.
@app.post("/admin/crunch-mode/start")
async def admin_start_crunch_mode(
	hours: int = Query(default=48, ge=1, le=168),
	x_admin_token: str | None = Header(default=None),
) -> dict[str, object]:
	# Validate caller has project-manager privileges.
	_require_admin(x_admin_token)
	# Activate crunch mode in core engine.
	result = engine.start_crunch_mode(hours=hours)
	return {"status": "success", "crunch_mode": result}


# Admin endpoint to set global time scaling factor.
# Affects time-based metrics such as inactivity and response-time display.
@app.post("/admin/time-scale")
async def admin_set_time_scale(
	scale: float = Query(..., gt=0.0, le=1000.0),
	x_admin_token: str | None = Header(default=None),
) -> dict[str, object]:
	# Validate caller has project-manager privileges.
	_require_admin(x_admin_token)
	try:
		# Apply PM-provided scale value to the engine.
		result = engine.set_time_scale(scale)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	return {"status": "success", "time": result}