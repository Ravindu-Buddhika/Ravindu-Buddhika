#!/usr/bin/env python3
"""
Fetches real GitHub data (profile info, contribution stats, streaks,
top languages) for a given username and writes it into README.md
between marker comments, in a terminal/monospace style.

Requires a GitHub token with at least `read:user` scope in the
environment variable GH_TOKEN (a classic PAT works fine, public
scope is enough since all the data we read is public).
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, date

USERNAME = os.environ.get("GH_USERNAME", "Ravindu-Buddhika")
TOKEN = os.environ.get("GH_TOKEN")
README_PATH = os.environ.get("README_PATH", "README.md")

if not TOKEN:
    print("ERROR: GH_TOKEN environment variable is not set.", file=sys.stderr)
    sys.exit(1)

REST_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": USERNAME,
}

GRAPHQL_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": USERNAME,
}


def http_get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def http_post(url, headers, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# 1. Basic profile info (REST)
# ---------------------------------------------------------------------------
profile = http_get(f"https://api.github.com/users/{USERNAME}", REST_HEADERS)

public_repos = profile.get("public_repos", 0)
followers = profile.get("followers", 0)
following = profile.get("following", 0)
created_at = profile.get("created_at", "")
member_since = ""
if created_at:
    member_since = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").strftime("%d %b %Y")


# ---------------------------------------------------------------------------
# 2. Contribution calendar + streaks (GraphQL)
# ---------------------------------------------------------------------------
query = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""

gql_result = http_post(
    "https://api.github.com/graphql",
    GRAPHQL_HEADERS,
    {"query": query, "variables": {"login": USERNAME}},
)

calendar = gql_result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
total_contributions = calendar["totalContributions"]

days = []
for week in calendar["weeks"]:
    for d in week["contributionDays"]:
        days.append((datetime.strptime(d["date"], "%Y-%m-%d").date(), d["contributionCount"]))
days.sort(key=lambda x: x[0])

# Longest streak (any period in the last year covered by the calendar)
longest_streak = 0
longest_start = longest_end = None
cur_run = 0
run_start = None
for d, count in days:
    if count > 0:
        if cur_run == 0:
            run_start = d
        cur_run += 1
        if cur_run > longest_streak:
            longest_streak = cur_run
            longest_start, longest_end = run_start, d
    else:
        cur_run = 0

# Current streak: consecutive contributed days ending today (or yesterday
# if today has no contributions yet)
current_streak = 0
current_start = None
today = date.today()
days_by_date = {d: c for d, c in days}
cursor = today
# if today has 0 so far, start counting from yesterday
if days_by_date.get(cursor, 0) == 0:
    cursor = cursor.fromordinal(cursor.toordinal() - 1)
while days_by_date.get(cursor, 0) > 0:
    current_streak += 1
    current_start = cursor
    cursor = cursor.fromordinal(cursor.toordinal() - 1)
current_end = today if days_by_date.get(today, 0) > 0 else (current_start or today)


def fmt(d):
    return d.strftime("%b %d") if d else "-"


# ---------------------------------------------------------------------------
# 3. Top languages (REST, byte-accurate, forks excluded — matches the
#    same logic used on the portfolio site)
# ---------------------------------------------------------------------------
repos = []
page = 1
while True:
    batch = http_get(
        f"https://api.github.com/users/{USERNAME}/repos?per_page=100&page={page}",
        REST_HEADERS,
    )
    if not batch:
        break
    repos.extend(batch)
    if len(batch) < 100:
        break
    page += 1

own_repos = [r for r in repos if not r.get("fork")]

lang_bytes = {}
for r in own_repos:
    langs_url = r.get("languages_url")
    if not langs_url:
        continue
    try:
        langs = http_get(langs_url, REST_HEADERS)
    except Exception:
        continue
    for lang, size in langs.items():
        lang_bytes[lang] = lang_bytes.get(lang, 0) + size

top_langs = sorted(lang_bytes.items(), key=lambda x: -x[1])[:5]
top5_total = sum(size for _, size in top_langs) or 1


def bar(pct, width=20):
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


lang_lines = []
for lang, size in top_langs:
    pct = round(100 * size / top5_total, 2)
    lang_lines.append(f"  {lang:<11} {bar(pct)}  {pct}%")
lang_block = "\n".join(lang_lines) if lang_lines else "  (no language data available)"


# ---------------------------------------------------------------------------
# 4. Build the terminal-style block
# ---------------------------------------------------------------------------
generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

stats_block = f"""<pre align="left" style="background:#0D1117; color:#39FF14; font-family:'Fira Code','Courier New',monospace; padding:22px; border-radius:8px; line-height:1.6; font-size:14px;">
<b>ravindu@dev</b>:~$ curl -s api.github.com/users/{USERNAME} | jq

  login          : {USERNAME}
  public_repos   : {public_repos}
  followers      : {followers}
  following      : {following}
  member_since   : {member_since}

<b>ravindu@dev</b>:~$ cat github_stats.txt
  ┌──────────────────┬──────────────────┬──────────────────┐
  │  Total Commits    │  Current Streak  │  Longest Streak  │
  ├──────────────────┼──────────────────┼──────────────────┤
  │      {total_contributions:<13}│      {current_streak:<11}│      {longest_streak:<11}│
  │  (last 12 months) │ {fmt(current_start)} - {fmt(current_end)}  │ {fmt(longest_start)} - {fmt(longest_end)}  │
  └──────────────────┴──────────────────┴──────────────────┘

<b>ravindu@dev</b>:~$ cat top_langs.txt
{lang_block}

<b>ravindu@dev</b>:~$ # last synced: {generated_at}
</pre>"""

# ---------------------------------------------------------------------------
# 5. Write into README.md between markers
# ---------------------------------------------------------------------------
START = "<!--STATS-START-->"
END = "<!--STATS-END-->"

with open(README_PATH, "r", encoding="utf-8") as f:
    content = f.read()

if START not in content or END not in content:
    print(f"ERROR: Could not find {START} / {END} markers in {README_PATH}", file=sys.stderr)
    sys.exit(1)

before = content.split(START)[0]
after = content.split(END)[1]
new_content = f"{before}{START}\n{stats_block}\n{END}{after}"

with open(README_PATH, "w", encoding="utf-8") as f:
    f.write(new_content)

print("README.md updated successfully.")
