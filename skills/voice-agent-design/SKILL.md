---
name: voice-agent-design
description: "vox.ai 음성 에이전트의 목적·대상·방향·채널·완료 기준을 설계하고 Single + Manual 기본·Flow 예외의 에이전트 유형을 고를 때 사용한다. 생성·저장 실행은 Architect 업무 스킬이 담당한다."
metadata:
  product: vox.ai
  layer: general
  status: stable
---

# voice-agent-design

## 설계할 것
사용자 자료에서 목적, 대상 고객, 시작 방식, 우선 채널, 사전 정보, 통화 뒤 실제 결과를 정리한다. 전화라면 인바운드/아웃바운드를 구분한다. 둘 다 필요하면 지식과 결과 필드의 재사용 여부와 도입·거절·종료 절차 차이를 따로 판단한다.

에이전트는 Single + Manual로 설계한다. 첫 구축은 핵심 업무 하나를 완주시키고, 서비스 안내는 넓게 담을 수 있다. 첫 체험에 번호 확보·외부 CRM을 강제하지 않되, 사용자가 요구한 외부 예약 확정을 내부 정보 수집으로 바꾸지 않는다. 필요한 연동이 없으면 그 차이와 현재 가능한 완료 지점을 설명한다.

## 에이전트 유형 선택
기본은 **Single + Manual**이다. Flow는 업무의 중심이 아래 규칙형 신호일 때만 고른다.

### Flow 신호 (하나 이상이 업무의 중심일 때만)
- F1 키패드 메뉴: "1번은 ○○, 2번은 ○○"처럼 고객이 번호를 눌러 고르는 ARS가 요청의 뼈대다. 키 입력 해석은 분류 단계의 LLM이 하므로 100% 결정적이지는 않다고 알린다.
- F2 원문 낭독: 법정·규제 고지, 약관·녹취 동의, 완전판매 확인 문항처럼 제공된 문구를 글자 그대로, 정해진 순서로 읽어야 하고 바꾸면 안 된다.
- F3 값에 따른 기계적 분기: 시각·요일·휴일·변수·API 결과 값을 비교식으로 판단해 경로가 갈리고, 그 분기가 통화 구조의 대부분이다.
- F4 건너뛰기 금지 단계: 규정·감사 요구로 "본인 확인 통과 전에는 다음 단계 불가"처럼 단계 순서를 어기면 안 된다고 명시됐다.
- F5 아웃바운드 고정 스크립트: 고정 확인 단계(본인 확인 → 고지문 → 동의 여부)를 매 통화 같게 진행해야 한다.

### Flow 신호가 아닌 것 (이것만으로 Flow를 고르지 않는다)
예약·접수·상담·문의 분류, 상담원/직원 연결, 문자 발송, 통화 종료, "필수로 받을 항목", "여러 단계", "분기가 있다", "복잡하다", 몇 개의 "반드시/절대" 규칙, 영업시간 안내 한두 줄.

### 그 밖은 Single + Manual
자유 대화, Q&A, 상담, 자연스러운 대화로 하는 예약·접수, 영업, 불만 처리, 만족도 조사(문항을 상황에 맞게 말해도 되는 경우).
- 프롬프트: 정체성·말투·인사·모든 업무에 공통인 원칙과 금지, Manual 선택 우선순위를 쓴다. 보통 1,500~4,000자이고 업무 절차는 Manual로 옮긴다.
- Manual: 업무별 절차·정책·예외. 고객 의도 하나당 Manual 하나(`save_manual`로 에이전트에 붙인다)이고 보통 3~10개다. 트리거는 겹치지 않게 쓰고 제외절을 둔다. API 조회·예약, 결과 코드 분기, 안전 단락처럼 복잡한 업무도 Manual의 이름 붙은 단계와 결과별 분기로 쓴다. 쓰는 법과 템플릿은 [manual-authoring](../manual-authoring/SKILL.md)이다.
- 지식: 소량의 공통 사실은 프롬프트에, 업무별 사실·정확히 말할 문구는 해당 Manual에 둔다. 많은 참고 자료가 필요하거나 사용자가 요청한 경우에만 지식을 검토한다. 현재 값은 API로 조회한다.
- 내장 도구: 통화 종료(`end_call`), 통화 전환(`transfer_call`), 문자(`send_sms`), 다른 agent 전환(`transfer_agent`). Manual이 쓰는 도구는 그 Manual 본문에서 `@tool:이름`으로 참조한다.
- API 도구: 실제 조회·등록이 필요할 때만 쓴다(예약 확정, 배송 조회). Manual 본문에서는 `@tool:<tool_id>`로 참조한다.

### 섞인 경우
- 대화가 중심이고 강한 규칙이 몇 개뿐이면 Single + Manual로 만든다. 규칙은 해당 Manual의 번호 단계와 "반드시" 조건, 도구 성공 조건으로 쓴다(예: 응급 증상이면 즉시 `transfer_call`). 순서가 중요하다는 이유만으로 Flow로 바꾸지 않는다.
- 규칙형 구간과 대화형 구간이 뚜렷이 나뉘면 agent를 나눈다. 예: 앞단 키패드 메뉴(Flow) → 대화가 필요한 메뉴만 `transferAgent` 노드로 Single + Manual agent에 넘긴다. 반대로 Single 상담 중 고지문 낭독이 필요하면 `transfer_agent`로 낭독 전용 Flow에 넘긴다.
- 방향(인바운드/아웃바운드), 페르소나·목소리·번호가 다르면 Manual을 늘리지 말고 agent를 나눈다.

### 애매할 때와 사용자가 유형을 지정했을 때
- 애매하면 Single + Manual로 만든다.
- 사용자가 Flow(또는 Single)를 명시하면 그대로 따른다. 다만 위 신호에 비춰 다른 유형이 낫다면 이유와 함께 한 번만 말하고, 다시 권하지 않는다. 특히 Flow를 지정했지만 대화로 받는 접수·상담이 중심이면(키패드 메뉴·원문 낭독·시각 분기가 중심이 아니면), 첫 저장 전에 'Single + Manual이 더 맞는 이유' 한 문장을 말하고 요청대로 Flow로 진행한다.

### 만들기 전에 말하기
첫 `save_agent` 전에 사용자에게 고른 유형과 이유를 한 줄로 알린다.
"Single + Manual 3개(예약 접수·진료 문의·응급 연결)로 만듭니다. 대화로 받는 접수이고 키패드 메뉴나 원문 낭독이 없기 때문입니다."

### 대조 예시
| 요청 | 유형 | 이유 |
|---|---|---|
| "치과 예약 전화를 받아 초진/재진·연락처·희망 시간 받기, 아프면 바로 데스크 연결" | Single + Manual | 대화형 접수. 전환은 내장 도구 |
| "고객 만족도 3문항을 편하게 물어보고 의견 받기" | Single + Manual | 문항을 상황에 맞게 말해도 됨 |
| "배송 문의·파손 접수·상담원 연결을 말로 받는 쇼핑몰 고객센터" | Single + Manual | 문의 분류와 전환만으로는 Flow가 아님 |
| "1번 영업시간, 2번 오시는 길, 9번 직원 연결 ARS" | Flow | F1 키패드 메뉴가 뼈대 |
| "보험 완전판매 확인 6문항을 원문대로 읽고 예/아니오 받기" | Flow | F2 원문·순서 고정 |
| "평일 9~18시는 상담원 연결, 그 외엔 정해진 멘트 후 종료" | Flow | F3 시각 비교가 구조 전체 |

## 질문과 제안
무엇을 물을지는 [정할 것](../build-first-voice-agent/SKILL.md#정할-것)을 따른다. 말투·목소리는 대상에 맞춰 제안하고, 첫 저장 뒤 들어 보고 고르게 한다. 새로운 구축 요청 자체를 실고객 발신 허가로 해석하지 않는다.

새 agent의 모델 선택은 [에이전트 구축의 모델 선택 규칙](../build-first-voice-agent/SKILL.md#모델-고르기)을 따른다.

## 산출물
유형과 이유 한 줄, 목표/근거/가정/필수 정보/정상·예외·마무리/실제 결과/시험 상황을 짧은 업무 요약으로 남긴다. Single + Manual이면 Manual 목록(고객 의도별 이름·트리거)과 프롬프트·지식·도구 분담도 적는다. 기획 문서는 구성 저장이나 실제 시험 완료가 아니다.

예: 청소 견적 문의라면 ‘상담 정보를 수집해 저장’과 ‘가격을 확정하고 예약’의 완료 근거를 구분한다. 후자를 요청했다면 전자로 몰래 축소하지 않는다.

실제 구축은 [build-first-voice-agent](../build-first-voice-agent/SKILL.md), 대화 원고 작성은 [manual-authoring](../manual-authoring/SKILL.md)로 연결한다.

업무가 여러 개이거나 고객 목표가 바뀌면 [업무 판단 기준](../../references/workflow-guidance.md)의 업무 선택·질문 기준을 적용한다. ‘A/B’, ‘예약’, ‘접수’ 같은 단어를 도구명으로 바로 번역하지 말고 대상과 실제 결과의 의미를 먼저 맞춘다. 잠정 제안과 사용자 결정은 출처를 구분한다.

## Flow와 ARS 흐름
위 ‘에이전트 유형 선택’에서 Flow로 정해졌을 때만 적용한다. 그렇지 않으면 이 절은 건너뛴다. 키패드 메뉴 ARS의 구조·키 표·골격 그래프는 [Flow ARS 패턴](../../references/flow-ars-pattern.md)을 따른다.
- 노드는 실제 schema가 허용하는 `begin`, `conversation`, `tool`, `condition`, `extraction`, `api`, `sendSms`, `transferCall`, `transferAgent`, `endCall`, `note`로 설계한다. 노드 `data` 키는 snake_case(`static_sentence`, `prompt_type`, `is_allow_interruption` 등)이고 분기는 노드가 아니라 edge의 `condition`(`ai`·`logic`·`fallback`)으로 둔다. 고정 문구는 `prompt_type`을 `static`으로 하고 `static_sentence`에 두며 끼어들기는 `is_allow_interruption`으로 정한다. F2·F5 질문은 dynamic conversation의 `first_message`에 그대로, 판정·재안내만 `prompt`에(원문 낭독은 미보장); 고지·완료는 `static_sentence`에 둔다.
- 키패드(DTMF) 메뉴는 키마다 AI edge를 달지 않는다. 눌린 키는 고객 메시지로 들어오므로 분류용 `extraction` 노드 하나가 메뉴 코드를 뽑고, `condition` 노드의 `logic` 조건이 그 코드로 결정적으로 분기한다.
- 시각·요일·휴일처럼 값으로 갈리는 분기도 `condition` 노드의 `logic` 조건이다. `begin`의 나가는 edge는 `fallback` 조건만 허용하므로 `begin` → `condition` 노드로 분기한다. `current_time`을 logic 변수로 쓸 수 있다. logic edge는 저장 순서대로 평가해 처음 맞는 것을 택하므로 휴일 edge를 영업시간 edge보다 앞에 둔다.
- `conversation` 노드에는 `fallback` edge를 달 수 없고 저장이 거부된다. ‘그 밖의 입력’은 AI 조건 edge로 쓴다. 실패 후 접수나 대표 연결로 복귀해야 하는 `transferCall`은 반드시 `transfer_type: "warm"`과 실패 `fallback` edge를 쓴다. cold는 이 요구에 쓰지 않는다. 다른 agent로는 `transferAgent`다.
- self-loop(자기 자신으로 돌아오는 edge)는 ‘0번 다시 듣기’처럼 입력이 있을 때의 재안내에만 쓴다. 무입력용 self-loop는 만들지 않는다.
- **무입력(침묵)은 전환 조건이 아니다.** ‘무입력 → 재안내 → 직원 연결’은 지금 만들 수 없다. 무입력 변수·edge·노드를 만들지 말고, 같은 안내가 반복되다 설정한 무응답 시간에 통화가 끝난다는 한계를 사용자에게 알린다.
- `sendSms`가 `fire_and_forget`이면 성공 edge의 AI 조건 문구는 정확히 "요청 성공 시"여야 한다. 인바운드에서 `sms_from_number`를 생략하면 고객이 건 번호로 나간다.
- `validate_flow`는 cold 전환(실패해도 돌아오지 않음)과 logic 변수 이름 오타를 잡지 못한다. 직접 확인한다.

저장 전에는 `validate_flow`를 `level="all"`로 호출해 errors를 고치고 advisories(저장은 막지 않는 실행 경고)도 읽어 반영한다. `save_agent`는 [agents-platform](../agents-platform/SKILL.md)의 Flow agent 절차를 따른다. 흐름을 만들었다는 것이 실제 통화 시험을 마쳤다는 뜻은 아니며, 시험은 고객이 직접 한다.

Flow의 조회·등록값 비교·결과 기록·mock 채팅 시험은 [Flow 업무 계약](../../references/flow-business-contract.md)을 따른다. 저장 전에 결과 스키마와 outcome, 모든 API의 동일 case·trace, 채팅 입력변수 전체, 연결 실패 복귀를 점검한다.
