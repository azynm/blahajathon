# CoLeague
A Flask App for gamify-ing the workspace! It integrates with Discord (in place of Slack) and Github to draft a leaderboard 
of you and your colleagues, rewarding commits, positive messages or activity, as well as punishing spam, negative messages or 
awful branch usage. 

Created by Zayn Malik, Aadi Deepchand, Lacksha Jeyabraba and Sophia Advincula in 24 hours for the 2026 SotonHack!

# Running the app

run project with 
> python app.py

## Git Integration (Webhook + League Table)

This project now includes a FastAPI webhook receiver for live GitHub events.

### 1. Run the API

```bash
uvicorn app:app --reload --port 8000
```

Optional environment variables:

- `GITHUB_WEBHOOK_SECRET`: validates `X-Hub-Signature-256` from GitHub.
- `ADMIN_TOKEN`: required for admin endpoints.

### 2. Expose localhost for GitHub webhooks

```bash
ngrok http 8000
```

Use the forwarding URL and append `/github-webhook`.

### 3. Configure GitHub Webhook

In your repository:

1. Go to `Settings -> Webhooks -> Add webhook`
2. Payload URL: `https://<your-ngrok-url>/github-webhook`
3. Content type: `application/json`
4. (Optional) Set the same secret as `GITHUB_WEBHOOK_SECRET`
5. Select individual events:
	- `Pushes`
	- `Branch or tag creation`
	- `Branch or tag deletion`
	- `Pull requests`
	- `Pull request reviews`

### 4. Available API endpoints

- `POST /github-webhook`: receives GitHub events
- `GET /git/leaderboard`: returns ranked leaderboard + metrics
- `GET /git/logs?limit=50`: recent parsed Git event logs
- `POST /admin/crunch-mode/start?hours=48`: enable score multiplier x2
- `POST /admin/time-scale?scale=1.0`: scale inactivity/response-time metrics

Admin endpoints require header: `X-Admin-Token: <ADMIN_TOKEN>`

### 5. Metrics currently populated from Git events

- Commits
- Merge approvals
- Activity/Inactivity
- Response times (PR open -> merged)
- Spam heuristic (high event burst)
- Commit names/messages
- Branch usage
- Leaderboard points/rank

Note: Positive/negative message metrics are placeholders in this Git module and are intended to be filled by Discord-side analysis.

run project with 
> python app.py
