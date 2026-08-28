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
KST = timezone(timedelta(hours=9))

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
              createdAt
              closedAt
              repository { nameWithOwner }
              assignees(first: 20) { nodes { login } }
            }
            ... on PullRequest {
              number
              title
              url
              state
              createdAt
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


def current_window_key(now_utc):
    """KST 08시대/16시대 실행 슬롯을 식별하는 키. 그 외 시간이면 None (윈도우 dedup 미적용)."""
    kst_now = now_utc.astimezone(KST)
    if kst_now.hour == 8:
        slot = "AM"
    elif kst_now.hour == 16:
        slot = "PM"
    elif kst_now.hour == 11:  # TEMP TEST: 확인 후 제거 예정
        slot = "TEST"
    else:
        return None
    return f"{kst_now.date().isoformat()}_{slot}"


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
    now = datetime.now(timezone.utc)
    is_scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    window_key = current_window_key(now) if is_scheduled else None

    state = load_state()
    if window_key and state.get("last_window") == window_key:
        print(f"Window {window_key} already handled, skipping.")
        return

    items = fetch_project_items()

    repos = {
        it["content"]["repository"]["nameWithOwner"]
        for it in items
        if it.get("content") and it["content"]["__typename"] in ("Issue", "PullRequest")
    }
    mentioned_by_repo = {repo: fetch_mentioned_numbers(repo) for repo in repos}

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
                    "created_at": content["createdAt"],
                }
            )

    matched.sort(key=lambda m: m["created_at"])

    if matched:
        def format_line(m):
            created_date = m["created_at"][:10]
            return f"*<{m['url']}|{m['key']}> {m['title']}* ({created_date}) — {', '.join(m['reasons'])}"

        sections = []
        open_lines = [format_line(m) for m in matched if m["is_open"]]
        closed_lines = [format_line(m) for m in matched if not m["is_open"]]
        if open_lines:
            sections.append("*열린 티켓*\n" + "\n".join(open_lines))
        if closed_lines:
            sections.append("*닫힌 티켓*\n" + "\n".join(closed_lines))

        text = "관련 티켓이 있습니다:\n\n" + "\n\n".join(sections)
        post_to_slack(text)

    if window_key:
        state["last_window"] = window_key
    state["notified"] = sorted(m["key"] for m in matched)
    save_state(state)


if __name__ == "__main__":
    main()
