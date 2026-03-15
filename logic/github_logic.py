import requests
from datetime import datetime

def get_detailed_github_data(repo, headers, since_date):
    base_url = f"https://api.github.com/repos/{repo}"
    since_date = since_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    out = []

    #Get commits since a certain time
    commit_params = {"since": since_date}
    commits_res = requests.get(f"{base_url}/commits", headers=headers, params=commit_params)
    
    if commits_res.status_code == 200:
        for c in commits_res.json():
            if "merge" in (c['commit']['message']).lower():
                out.append({
                    "type": "merge",
                    "author": c['commit']['author']['name'],
                    "date": c['commit']['author']['date'],
                    "message": c['commit']['message']#,
                    #"sha": c['sha']
                })
            else:
                out.append({
                    "type": "commit",
                    "author": c['commit']['author']['name'],
                    "date": c['commit']['author']['date'],
                    "message": c['commit']['message']#,
                    #"sha": c['sha']
                })

    #Get pull requests
    prs_res = requests.get(f"{base_url}/pulls?state=closed&sort=updated&direction=desc", headers=headers)
    
    if prs_res.status_code == 200:
        for pr in prs_res.json():
            merged_at = pr.get('merged_at')
            
            # Only proceed if it was merged and merged AFTER our 'since_date'
            if merged_at and merged_at >= since_date:
                
                # Fetch Approvers
                reviews_res = requests.get(f"{base_url}/pulls/{pr['number']}/reviews", headers=headers)
                approvers = []
                if reviews_res.status_code == 200:
                    approvers = [r['user']['login'] for r in reviews_res.json() if r['state'] == 'APPROVED']
                
                out.append({
                    "type": "merge_request",
                    "id": pr['number'],
                    "title": pr['title'],
                    "author": pr['user']['login'],
                    "merged_at": merged_at,
                    "source_branch": pr['head']['ref'],
                    "target_branch": pr['base']['ref'],
                    "approvers": list(set(approvers)) # list(set()) removes duplicate approvals
                })
            
            # Optimization: If the PR was updated before our 'since_date', 
            # we can stop looping (since we sorted by 'updated' desc).
            elif pr.get('updated_at') < since_date:
                break

    return out