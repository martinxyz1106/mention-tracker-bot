import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ORG = "xyzcorpsoftware"
PROJECT_NUMBER = 2
USERNAME = "martinxyz1106"
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "state.json")
CLOSED_MENTION_DAYS = 15

GH_TOKEN = os.environ["GH_PAT"]
SLACK_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL = os.environ["SLACK_CHANNEL_ID"]

GRAPHQL_URL = "https://api.github.com/graphql"
REST_SEARCH_URL = "https://api.github.com/search/issues"
SLACK_POST_URL = "https://slack.com/api/chat.postMessage"

GRAPHQL_QUERY = """
query($org: String!, $number: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $number) {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          content {
            __typename
            ... on Issue {
              number
              title
              url
              state
              closedAt
              repository { nameWithOwner }
              assignees(first: 20) { nodes { login } }
            }
            ... on PullRequest {
              number
              title
              url
              state
              closedAt
              repository { nameWithOwner }
              assignees(first: 20) { nodes { login } }
              reviewRequests(first: 20) {
                nodes { requestedReviewer { ... on User { login } } }
              }
            }
          }
        }
      }
    }
  }
}
"""


def http_post_json(url, payload, headers):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"POST {url} failed: {e.code} {e.read().decode()}") from e


def http_get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GET {url} failed: {e.code} {e.read().decode()}") from e


def gh_graphql(variables):
    return http_post_json(
        GRAPHQL_URL,
        {"query": GRAPHQL_QUERY, "variables": variables},
        {
            "Authorization": f"Bearer {GH_TOKEN}",
            "Content-Type": "application/json",
        },
    )


def fetch_project_items():
    items = []
    cursor = None
    while True:
        data = gh_graphql({"org": ORG, "number": PROJECT_NUMBER, "cursor": cursor})
        if data.get("errors"):
            raise RuntimeError(f"GraphQL error: {data['errors']}")
        project = data["data"]["organization"]["projectV2"]
        if project is None:
            raise RuntimeError(
                "Project not found, or GH_PAT lacks read:project / read:org scope"
            )
        block = project["items"]
        items.extend(block["nodes"])
        if block["pageInfo"]["hasNextPage"]:
            cursor = block["pageInfo"]["endCursor"]
        else:
            break
    return items


def fetch_mentioned_numbers(repo):
    query = f"repo:{repo} mentions:{USERNAME}"
    url = f"{REST_SEARCH_URL}?q={urllib.parse.quote(query)}&per_page=100"
    data = http_get_json(
        url,
        {
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
    )
    return {item["number"] for item in data.get("items", [])}


def post_to_slack(text):
    result = http_post_json(
        SLACK_POST_URL,
        {"channel": SLACK_CHANNEL, "text": text},
        {
            "Authorization": f"Bearer {SLACK_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    if not result.get("ok"):
        raise RuntimeError(f"Slack API error: {result}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"notified": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    items = fetch_project_items()

    repos = {
        it["content"]["repository"]["nameWithOwner"]
        for it in items
        if it.get("content") and it["content"]["__typename"] in ("Issue", "PullRequest")
    }
    mentioned_by_repo = {repo: fetch_mentioned_numbers(repo) for repo in repos}

    now = datetime.now(timezone.utc)
    matched = []
    for it in items:
        content = it.get("content")
        if not content or content["__typename"] not in ("Issue", "PullRequest"):
            continue

        is_open = content["state"] == "OPEN"
        if not is_open and content["closedAt"]:
            closed_at = datetime.fromisoformat(content["closedAt"].replace("Z", "+00:00"))
            if now - closed_at > timedelta(days=CLOSED_MENTION_DAYS):
                continue

        repo = content["repository"]["nameWithOwner"]
        number = content["number"]
        reasons = []

        assignees = {a["login"] for a in content["assignees"]["nodes"]}
        if USERNAME in assignees:
            reasons.append("담당자 지정")

        if content["__typename"] == "PullRequest":
            reviewers = {
                rr["requestedReviewer"]["login"]
                for rr in content["reviewRequests"]["nodes"]
                if rr["requestedReviewer"] and "login" in rr["requestedReviewer"]
            }
            if USERNAME in reviewers:
                reasons.append("리뷰 요청됨")

        if number in mentioned_by_repo.get(repo, set()):
            reasons.append("멘션됨")

        if reasons:
            matched.append(
                {
                    "key": f"{repo}#{number}",
                    "title": content["title"],
                    "url": content["url"],
                    "reasons": reasons,
                    "is_open": is_open,
                }
            )

    state = load_state()
    notified = set(state.get("notified", []))
    new_items = [m for m in matched if m["key"] not in notified]

    if new_items:
        def format_line(m):
            return f"*<{m['url']}|{m['key']}> {m['title']}* — {', '.join(m['reasons'])}"

        sections = []
        open_lines = [format_line(m) for m in new_items if m["is_open"]]
        closed_lines = [format_line(m) for m in new_items if not m["is_open"]]
        if open_lines:
            sections.append("*열린 티켓*\n" + "\n".join(open_lines))
        if closed_lines:
            sections.append("*닫힌 티켓*\n" + "\n".join(closed_lines))

        text = "새로운 관련 티켓이 있습니다:\n\n" + "\n\n".join(sections)
        post_to_slack(text)

    state["notified"] = sorted(m["key"] for m in matched)
    save_state(state)


if __name__ == "__main__":
    main()
