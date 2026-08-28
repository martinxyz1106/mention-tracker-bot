# Mention Tracker Bot

GitHub Organization Project(`xyzcorpsoftware` / project #2)에서 특정 사용자(`martinxyz1106`)와 관련된
이슈/PR(담당자 지정, 리뷰 요청, 멘션)을 찾아서 Slack 채널로 알려주는 봇입니다.

## 동작 방식

- `scripts/check_mentions.py`가 GitHub GraphQL(Project 항목 조회) + REST Search(`mentions:` 검색) API를 호출해서
  대상 이슈/PR을 찾습니다.
- 열린 티켓(open)과 닫힌 티켓(closed/merged)을 구분해서 Slack 메시지에 섹션으로 나눠 보여줍니다.
- 닫힌 티켓 중 **닫힌 지 15일이 지난 것**은 알림 대상에서 제외됩니다. (`CLOSED_MENTION_DAYS` 상수로 조절)
- 티켓은 생성일 오름차순(오래된 것부터)으로 정렬되어 표시됩니다.
- 실행할 때마다 조건에 맞는 티켓을 **매번 다시** Slack으로 보냅니다 (같은 티켓 목록에 대한 중복 알림 방지 로직 없음).
- 매 실행 결과는 `state.json`의 `notified`에 기록만 되고(참고용), 알림 여부 판단에는 사용하지 않습니다.
- `state.json`의 `last_window`는 **스케줄(`schedule`) 실행에 한해서** "이 아침/저녁 슬롯을 이미 처리했는지"를 기록합니다.
  같은 슬롯에서 이미 성공 처리됐으면 이후 재시도는 API 호출 없이 곧바로 스킵합니다 (아래 "실행 스케줄" 참고).
  `workflow_dispatch` 수동 실행은 이 스킵 로직의 영향을 받지 않고 항상 전체 로직을 실행합니다.

## 실행 스케줄

`.github/workflows/check-mentions.yml`의 GitHub Actions로 매일 **KST 08:05~08:30 / 16:05~16:30 (UTC 23:05~23:30 / 07:05~07:30)**
사이에 5분 간격으로 여러 번 자동 실행을 시도합니다. Actions 탭에서 `workflow_dispatch`로 수동 실행도 가능합니다.

⚠️ **GitHub Actions의 `schedule` 트리거는 정시 실행을 보장하지 않고, 경우에 따라 아예 드롭될 수 있습니다**
(공식 문서에 명시된 동작이며, 특히 매시 정각처럼 스케줄이 몰리는 시간대에 발생하기 쉽습니다). 실제로 이 저장소에서도
`schedule` 트리거로 자동 실행된 이력이 한 번도 없었던 시기가 있었습니다 (신규 레포 생성 직후 첫 스케줄 사이클이
드롭된 사례, Actions 탭에서 `workflow_dispatch`로 트리거된 실행만 존재했음).

이를 완화하기 위해 **하나의 시간대(08시/16시)에 여러 번(5분 간격) cron을 걸어두고**, `scripts/check_mentions.py`에서
KST 기준 "오늘 아침/저녁 슬롯"을 계산해 이미 그 슬롯에서 성공 처리됐으면 스킵하도록 만들었습니다
(`current_window_key`, `state.json`의 `last_window`). 즉 5번의 시도 중 하나만 성공해도 그 시간대 알림은 정상적으로
나가고, 나머지 시도는 조용히 스킵됩니다. 새 토큰 발급이나 외부 크론 서비스 없이 GitHub Actions 안에서만 해결하는 방식입니다.

알림 시각/횟수를 바꾸려면 `check-mentions.yml`의 `cron` 값과 `scripts/check_mentions.py`의 `current_window_key`
함수(어느 KST 시각을 "AM"/"PM" 슬롯으로 볼지)를 함께 수정하고 커밋/push 하세요. GitHub Actions cron은 **UTC 기준**이라
KST 시각은 UTC−9시간으로 변환해서 넣어야 합니다.

⚠️ 분(minute) 값에 **정각(0분)은 포함하지 마세요.** 매시 정각은 GitHub Actions 스케줄 부하가 몰려 특히 드롭되기 쉽습니다.

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
