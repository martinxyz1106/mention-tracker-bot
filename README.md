# Mention Tracker Bot

GitHub Organization Project(`xyzcorpsoftware` / project #2)에서 특정 사용자(`martinxyz1106`)와 관련된
이슈/PR(담당자 지정, 리뷰 요청, 멘션)을 찾아서 Slack 채널로 알려주는 봇입니다.

## 동작 방식

- `scripts/check_mentions.py`가 GitHub GraphQL(Project 항목 조회) + REST Search(`mentions:` 검색) API를 호출해서
  대상 이슈/PR을 찾습니다.
- 열린 티켓(open)과 닫힌 티켓(closed/merged)을 구분해서 Slack 메시지에 섹션으로 나눠 보여줍니다.
- 닫힌 티켓 중 **닫힌 지 15일이 지난 것**은 알림 대상에서 제외됩니다. (`CLOSED_MENTION_DAYS` 상수로 조절)
- 티켓은 생성일 오름차순(오래된 것부터)으로 정렬되어 표시됩니다.
- 실행할 때마다 조건에 맞는 티켓을 **매번 다시** Slack으로 보냅니다 (중복 알림 방지 로직 없음).
- 매 실행 결과는 `state.json`에 기록만 되고(참고용), 알림 여부 판단에는 사용하지 않습니다.

## 실행 스케줄

`.github/workflows/check-mentions.yml`의 GitHub Actions로 매일 **KST 08:05 / 16:05 (UTC 23:05 / 07:05)** 에 자동 실행됩니다.
Actions 탭에서 `workflow_dispatch`로 수동 실행도 가능합니다.

알림 시각/횟수를 바꾸려면 `check-mentions.yml`의 `cron` 값을 수정하고 커밋/push 하세요. GitHub Actions cron은
**UTC 기준**이라 KST 시각은 UTC−9시간으로 변환해서 넣어야 합니다. 예: KST 09/14/18시 → UTC로는 0/5/9시이므로
`cron: '0 0,5,9 * * *'`.

⚠️ 분(minute) 값은 **정각(0분)을 피하세요.** GitHub Actions는 매시 정각처럼 스케줄이 몰리는 시간대에
부하로 인해 실행이 지연되거나 아예 드롭될 수 있다고 공식 문서에 명시되어 있습니다. 실제로 이 저장소에서도
정각(0분)으로 설정했을 때 `schedule` 트리거로 자동 실행된 이력이 한 번도 없었습니다 (Actions 탭에서
`workflow_dispatch`로 트리거된 실행만 존재). 5분 등 정각에서 벗어난 값을 사용하세요.

## 추적 대상 설정

`scripts/check_mentions.py` 상단의 상수를 실제 사용할 Organization/Project/사용자에 맞게 수정해야 합니다.

```python
ORG = "xyzcorpsoftware"     # 조회할 Organization
PROJECT_NUMBER = 2          # Organization Project 번호 (project URL의 숫자)
USERNAME = "martinxyz1106"  # 담당자 지정 / 리뷰 요청 / 멘션 여부를 추적할 GitHub 사용자명
```

다른 사람/조직 용도로 이 저장소를 쓰려면 이 값들을 먼저 바꾸고 커밋하세요.

## 필요한 GitHub Actions Secrets

이 저장소의 **Settings → Secrets and variables → Actions → Secrets** 탭에 아래 3개를 등록해야 합니다.
(⚠️ **Variables** 탭이 아니라 **Secrets** 탭이어야 합니다 — Variable은 평문으로 저장되어 누구나 값을 볼 수 있습니다.)

| Secret 이름 | 용도 | 발급 방법 |
| --- | --- | --- |
| `GH_PAT` | GitHub GraphQL/REST API 호출용 Personal Access Token | GitHub → Settings → Developer settings → Personal access tokens. 최소 `repo`, `read:project`, `read:org` 스코프 필요. Organization이 SSO를 강제한다면 발급 후 해당 org에 대해 SSO authorize 필요. |
| `SLACK_BOT_TOKEN` | Slack 메시지 전송용 Bot Token (`xoxb-...`) | Slack App 설정 → OAuth & Permissions. `chat:write` 권한 필요하고, 알림 보낼 채널에 봇을 초대해야 함. |
| `SLACK_CHANNEL_ID` | 메시지를 보낼 Slack 채널 ID | Slack에서 채널 정보 보기 → 하단의 채널 ID 복사 (채널 이름이 아니라 ID). |

실제 토큰/ID 값은 이 저장소 어디에도 커밋하지 말고, 항상 GitHub Secrets에만 등록하세요.

## 로컬에서 테스트하기

```bash
export GH_PAT=xxxx
export SLACK_BOT_TOKEN=xoxb-xxxx
export SLACK_CHANNEL_ID=Cxxxxxxxx
python scripts/check_mentions.py
```

## 기타 설정값

- `CLOSED_MENTION_DAYS`: 닫힌 티켓을 알림 대상에서 제외하기까지의 기준 일수 (기본 15일)

## SLACK 봇 추가 방법
- 에이전트 및 도구 탭 -> Ticket Tracking Bot -Individual
- 개인 비공개 채널 추가 -> 봇 초대
- Action에서 Run WorkFlow 실행 
