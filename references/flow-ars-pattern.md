# Flow ARS 패턴: 안내 → 분류 → 라우터

[에이전트 유형 선택](../skills/voice-agent-design/SKILL.md)에서 **Flow로 정해졌을 때만** 쓰는 참조다. 기본은 Single + Manual이며, 키패드 메뉴가 업무의 뼈대일 때만 이 구조를 쓴다.

키패드(DTMF)와 음성을 함께 받는 대표전화 ARS를 Flow agent로 만들 때의 기준 구조다. 메뉴의 의미(어떤 키가 어떤 메뉴인지)는 **분류 노드 하나**에만 두고, 분기는 **logic 조건**으로 결정적으로 처리한다. 키마다 AI edge를 다는 설계(노드 × 키만큼 edge)는 쓰지 않는다. 검증을 통과한 최소 골격 그래프는 [flow-ars-skeleton.json](flow-ars-skeleton.json)이다.

## 설계 전제 (플랫폼 사실)
- 눌린 키는 별도 이벤트가 아니라 고객 메시지 `<entered_dtmf_digits>N</entered_dtmf_digits>` 또는 `[DTMF] N`으로 들어온다.
- `logic` 조건은 `condition` 노드에서만 평가한다. condition 노드에는 `logic`과 `fallback` edge만 단다.
- logic edge는 edges 배열 순서대로 평가하고, 처음 맞는 edge로 간다.
- `conversation` 노드에는 `fallback` edge를 달 수 없다(저장 거부). '그 밖의 입력'은 AI 조건으로 쓴다.
- `extraction` 노드는 나가는 edge가 정확히 1개여야 하고 `skip_user_response: true`다.
- `begin`의 나가는 edge는 `fallback` 1개만 둘 수 있다. `begin` → `condition` 노드 진입은 가능하다.
- 시스템 변수 `current_time`은 통화 시작 시각을 KST 문자열 `YYYY-MM-DD HH:MM:SS+0900 (Ddd)`로 담는다(예: `2026-10-01 14:30:00+0900 (Thu)`). logic `left`에 그대로 쓸 수 있고, 값은 통화 중 고정된다.
- **무입력(침묵)은 전환을 일으키지 않는다.** 노드가 약 10초 뒤 같은 안내를 다시 말하고, 이후 간격이 3초씩 늘며 반복된다. `silenceCallTimeoutInSeconds`에 닿으면 통화가 끝난다.
- `sendSms`는 통화 중 그 노드에 도달한 순간 발송된다. 통화 후 발송 기능은 없다.
- warm 전환은 상대를 transferCall 노드의 `ring_duration_in_seconds`초(1~90, 비우면 30) 호출한다. 받지 않으면 transferCall의 `fallback` edge로 이어진다. cold 전환은 실패해도 ARS로 돌아오지 않는다.

## 전체 구조
```
begin ─fb→ [hours gate] ─logic→ 메인(영업중: 9 포함) / 메인(영업외: 9 없음)
안내 노드(static) ─ai "0"→ 자기 자신(다시 듣기)
            └─ai "그 밖의 모든 입력"→ [메뉴 분류 extraction] ─skip→ [라우터 condition]
라우터 ─logic requested_menu=코드→ 각 안내 노드 | (문자 안내면) sendSms → 안내 노드
       ─TRANSFER→ [transfer gate] ─영업중→ transferCall(warm) ─fb→ 부재중 sendSms → endCall
                                  └영업외·휴무→ 메인(영업외)
       ─MAIN 또는 fallback→ [hours gate]
```

## 1. 안내 노드 (static conversation)
- 고정 문구는 `prompt_type: "static"`, `static_sentence`에 두고 `is_allow_interruption: true`로 한다.
- 문구 끝에 공통 키 안내를 넣는다. 예: "다시 들으시려면 영 번, 직원 연결은 구 번, 처음으로는 별표를 눌러 주세요."
- 나가는 edge는 **AI 2개**다.
  1. 자기 자신으로 가는 edge, `prompt`: "고객이 키패드로 0을 눌렀다(`<entered_dtmf_digits>0</entered_dtmf_digits>` 또는 [DTMF] 0)."
  2. 분류 노드로 가는 edge, `prompt`: "그 밖의 모든 입력: 0 이외의 키를 눌렀거나 무엇이든 말했다."
- 이 구조를 택하는 이유는 다음과 같다.
  - 다시 듣기가 분류 상태(last_menu)에 의존하지 않는다.
  - AI 판단이 '0인가 아닌가'라는 이진 판단이라 흔들림이 적다.
  - 두 번째 edge가 모든 입력을 받으므로 노드에 갇히지 않는다.
- 분류 노드로 가는 edge 1개만 두고 0을 분류기의 `last_menu`로 처리해도 동작한다. 다만 LLM 단계가 하나 늘고, 분류기의 문맥 판단에 기대야 한다.
- 무입력을 edge 조건에 쓰지 않는다. 무입력으로는 그 edge가 평가되지 않는다.

## 2. 메뉴 분류 extraction (분류기)
- 변수는 3개다.
  - `requested_menu`(string): 이번 입력이 가리키는 메뉴 코드
  - `last_menu`(string): 마지막으로 실제 안내한 메뉴 코드
  - `unknown_count`(number): 연속 미분류 횟수
- 에이전트 `data.presetDynamicVariables`에 `{"last_menu": "MAIN", "unknown_count": "0"}`을 둔다. 값은 문자열이어야 한다.
- 메뉴 코드는 대문자 영문으로 고정한다(예: `MAIN`, `HOURS`, `VISIT_MENU`, `DIRECTIONS`, `PARKING`, `TRANSFER`, `UNKNOWN_REPROMPT`, `END`). 라우터의 `equals` 값과 글자 하나까지 같아야 한다.
- 추출 프롬프트 템플릿(메뉴 표만 업무에 맞게 바꾼다):
```
직전 메뉴: {{last_menu}} / 직전 미분류 횟수: {{unknown_count}} (비어 있으면 0)
가장 최근 USER 입력 하나만 분류한다. 과거 입력·도구 결과는 새 입력이 아니다.
requested_menu, last_menu, unknown_count를 항상 모두 출력한다. 코드는 아래 표의 값만 쓴다.
[입력 종류] <entered_dtmf_digits>…</entered_dtmf_digits> 또는 '[DTMF] '로 시작하면 키패드 입력이다. 그 밖은 음성이다.
[키 표] 문맥은 last_menu다.
- 공통: 9=TRANSFER, *=MAIN, 0=last_menu 값을 그대로 requested_menu로.
- MAIN: 1=HOURS, 2=VISIT_MENU, 3=BOOKING
- VISIT_MENU: 1=DIRECTIONS, 2=PARKING
- 표에 없는 키, #, 여러 자리 입력은 MAIN. 여러 자리를 쪼개지 않는다.
[음성] 뜻으로 분류한다. 영업시간·휴무=HOURS, 주소·위치=DIRECTIONS, 주차=PARKING, 예약=BOOKING,
직원·상담원=TRANSFER, 처음으로=MAIN, 다시 들려줘=last_menu, 명확한 종료 의사=END.
사람이 말한 '일 번', '별표'는 같은 키 규칙으로 처리한다.
[미분류] 메뉴로 답할 수 없는 말·잡음은 unknown_count가 0이면 UNKNOWN_REPROMPT와 unknown_count=1,
1 이상이면 TRANSFER와 unknown_count=0. 분류된 입력이나 DTMF면 unknown_count=0.
[상태] requested_menu가 실제 안내 메뉴면 last_menu도 같은 값. TRANSFER·UNKNOWN_REPROMPT·END면 last_menu 유지.
```
- `is_skip_user_response: true`, `tool_call_sound: "none"`로 둔다. 나가는 edge는 라우터로 가는 AI edge 1개(`skip_user_response: true`)뿐이다.

## 3. 라우터 (condition)
- 코드마다 logic edge 1개를 둔다: `{"type":"logic","operator":"&&","equations":[{"left":"requested_menu","operator":"equals","right":"HOURS"}]}`.
- `fallback` edge 1개를 hours gate(메인 메뉴)로 보낸다. 분류 결과가 비거나 이상해도 메인으로 돌아온다.
- `UNKNOWN_REPROMPT`는 되묻기 static 노드로 보낸다("죄송합니다. 한 번 더 말씀해 주시거나 별표를 눌러 주세요."). 이 노드의 AI edge 1개는 분류기로 간다.
- 선택 사항: '네, 감사합니다' 같은 맞장구를 `FINISH`로 분류해 "더 궁금하신 점이 있으신가요?" 노드로 보내고, 그다음 "없어요"는 `END`로 처리한다.

## 4. 공통 키
| 키 | 의미 | 처리 위치 |
|---|---|---|
| 0 | 방금 안내 다시 듣기 | 안내 노드 self-loop (음성 "다시"는 분류기의 last_menu) |
| 9 | 직원 연결 | 분류기 → TRANSFER → transfer gate(영업외면 메인(영업외)) |
| * | 메인 메뉴 | 분류기 → MAIN → hours gate |
- 별표 안내는 메인 메뉴에서 한 번만 하고, 영업시간 외 메뉴에서는 9를 말하지 않는다.

## 5. 영업시간·휴무 분기 (결정적)
- LLM 추출로 영업 상태를 판정하지 말고 condition 노드의 `current_time` logic으로 판정한다.
- 순서가 중요하다. 첫 일치가 이긴다.
  1. 휴무 edge(`||`): `contains "(Sun)"`(정기 휴무 요일), `contains "2026-12-25 "`(지정 휴일, 날짜 뒤에 공백 포함) → 영업외
  2. 영업 edge(`||`): 영업 시각마다 `contains " 10:"` … `contains " 17:"`(10:00~18:00이면 10~17시). 공백을 앞에 붙여야 분(`:10:`)과 섞이지 않는다. → 영업중
  3. `fallback` → 영업외
- 같은 식을 필요한 곳마다 복제한다. 시작·메인 복귀용 hours gate 하나, 직원 연결 직전 transfer gate 하나를 둔다.
- 영업외 메인 문구는 영업시간을 알리고 9를 뺀다. 영업외에 9를 눌러도 transfer gate가 메인(영업외)으로 돌려보낸다.
- 지정 휴일 날짜는 해마다 사용자가 갱신해야 한다. 저장할 때 이 사실을 알린다.

## 6. 직원 연결과 부재중 문자
- 설정은 `transferCall`에 `transfer_type: "warm"`, `transfer_configuration: {"transfer_type":"phone","transfer_to":"+82…"}`이다.
  - 전환 전 안내는 `prompt_type: "static"`과 `static_sentence`에 넣는다.
  - 직원에게 들려줄 귓속말은 `warm_transfer_static_sentence`에 넣는다.
- 나가는 edge는 `fallback` 1개이고 필수다. 이 edge는 부재중 `sendSms`(`response_mode: "wait"`)로 간다.
- sendSms 뒤에는 `endCall`을 둔다. 예: "지금은 연결이 어려워 문자로 안내를 보내 드렸습니다." 이 endCall은 성공 edge와 fallback edge가 모두 가리킨다.
- 착신 번호가 없으면 비우지 말고 사용자에게 받는다. 빈 값은 저장이 거부된다. 사용자가 시험 번호를 주면 그 번호를 쓴다.

## 7. 안내 중 문자 발송
- 안내 문구가 "문자로 보내 드리겠습니다"라고 말하는 노드는, 라우터에서 바로 가지 말고 **그 직전에 sendSms를 거친다.** 경로는 라우터 → sendSms → 안내 노드다. 이렇게 하면 0번 다시 듣기(self-loop)로 문자가 다시 나가지 않는다.
- `response_mode: "fire_and_forget"`이면 성공 edge의 AI `prompt`는 정확히 **"요청 성공 시"**여야 한다. 다른 문구는 저장이 거부된다. 실패 시 `fallback`도 같은 안내 노드로 보낸다.
- 문자 본문(`static_sentence`)은 일반 숫자 표기를 쓴다(주소 123, URL). `static_title`도 채운다.
- 인바운드에서 `sms_from_number`를 생략하면 고객이 건 번호로 나간다. 번호를 지어내거나 질문으로 멈추지 말고, 발신 번호를 따로 정해야 할 때만 조직이 보유한 문자 발신 가능 번호를 받는다.

## 8. TTS 읽기 표기 (음성 문구에만)
static 문구(안내·전환·종료)에는 아라비아 숫자와 기호를 쓰지 않고 읽는 그대로 적는다.

| 원문 | 표기 |
|---|---|
| 오전 10시~오후 6시 | 오전 열 시부터 오후 여섯 시까지 |
| 12월 25일 | 십이월 이십오일 |
| 중앙로 123 | 중앙로 백이십삼 |
| 2층, 1시간 | 이 층, 한 시간 |
| 0번 / 9번 | 영 번 / 구 번 |
| * / # | 별표 / 우물 정자 |

요청서에 읽기 지정 표가 있으면 그 표가 우선한다.

## 9. 에이전트 설정 (`save_agent`의 `payload.data`, camelCase)
- `callSettings`
  - `dtmfInterruptible: true`: 키를 누르면 안내를 바로 멈춘다.
  - `dtmfTimeoutSeconds: 1`: 한 자리 메뉴라 1초면 된다.
  - `dtmfTerminationEnabled: false`
  - `silenceCallTimeoutInSeconds: 45~60`: 재안내 2~3회 뒤 종료된다(추정).
- `speech.isAllowInterruption: true`. 노드마다 `is_allow_interruption: true`도 함께 둔다.
- `presetDynamicVariables`: §2의 초깃값.
- `prompt.prompt`: "한국어 존댓말. 변수·노드·코드 이름을 고객에게 읽지 않는다."
- 새 agent 모델은 [모델 선택 규칙](../skills/build-first-voice-agent/SKILL.md#모델-고르기)에 따라 정한다. `llm`을 보낼 때는 `model`이 필수이며, 선택된 `model` 값을 `data.llm.model`에 명시한다. 구 API처럼 `list_models(kind=llm)` 결과에 `featured` 필드가 없으면 `llm`을 생략해 서버 추천 기본값을 쓴다. `temperature: 0`을 권장한다.
- 노드 `data` 키는 snake_case, agent `data` 키는 camelCase다. 섞어 쓰지 않는다.

## 10. 지금 안 되는 것: 무입력 → 재안내 → 직원 연결
**무입력은 분기 조건이 될 수 없다.** "무입력이면 1회 재안내 후 직원 연결"은 현재 구현할 수 없다. 무입력 횟수 변수, 무입력 edge 문구, 무입력 재안내 노드를 만들지 않는다. 만들어도 실행되지 않는다. 저장 보고에서 사용자에게 그대로 말한다.

> 무입력(침묵)은 지금 Flow에서 분기 조건으로 쓸 수 없습니다. 무입력이면 같은 안내를 약 10초 뒤부터 다시 말하고, 설정한 무응답 종료 시간(예: 50초)이 지나면 통화를 정중히 종료합니다. 그래서 '재안내 후 직원 연결'은 구현하지 못했고, 대신 잘못된 입력이나 알아듣지 못한 말이 두 번 이어지면 직원 연결로 보내도록 했습니다.

## 11. 알려진 함정
- 키마다 AI edge, `conversation` 노드의 `fallback`, 무입력 self-loop는 쓰지 않는다. 각각 분기가 흔들리거나, 저장이 거부되거나, 실행되지 않는다.
- fire_and_forget `sendSms`의 성공 edge 문구는 정확히 "요청 성공 시"다(§7).
- `current_time`은 logic 변수로 쓸 수 있다. 휴무 edge를 영업 edge보다 앞에 둔다(§5).
- 직원 연결 `transferCall`은 warm과 `fallback` 경로가 있어야 한다. `validate_flow`는 cold 전환을 경고 없이 통과시키고, logic `left` 변수명 오타도 잡지 못한다. 저장 뒤 `get_agent`로 `transfer_type`과 변수명(`requested_menu`, `current_time`)을 직접 확인한다.
- `sms_from_number`를 생략한 동작은 §7을 따른다.

## 12. MCP 호출 순서
1. `get_schema(namespace="flow-schema", schema_type="flow-data")`로 그래프 형식을 확인한다. 노드별 세부는 `node-extraction`, `node-condition`, `node-transferCall`, `node-sendSms`에서 확인한다. 설정 키는 `get_schema("agent-schema","agent-data-create")`로 확인한다. 이름이 다르면 `list_schemas`로 실제 이름을 찾는다.
2. `validate_flow(level="all", payload={"flow": {nodes, edges}})`를 호출한다. errors를 0으로 만들고 advisories를 읽는다. 검증 오류를 추측으로 우회하지 않는다.
3. §9의 선택 모델을 포함하거나 구 API fallback 규칙에 따라 생략해 `save_agent(mode="create", payload={name, type:"flow", data:{…§9}, flow:{…}})`로 저장한다. 게시하지 않는다.
4. `get_agent(agent_id)`로 다시 읽고 다음을 확인한다.
   - logic edge 순서(휴무가 영업보다 앞)
   - `transfer_type: "warm"`과 fallback edge
   - sendSms 위치
   - `callSettings`

   보고에는 `agent_id`, `head_revision`, `flow_revision`을 넣는다.
5. 수정할 때는 다음 순서를 따른다.
   1. `get_agent`로 현재 그래프를 읽는다.
   2. 그래프 전체를 편집한다.
   3. `validate_flow(agent_id=…, level="all")`로 검증한다.
   4. `save_agent(mode="update", payload={expected_head_revision, expected_flow_revision, flow})`로 저장한다.
   5. `get_agent`로 다시 읽는다.
6. 게시는 사용자가 요청할 때만 한다(`create_agent_version` → `publish_agent_version`). 번호 연결은 사용자 확인 뒤 `set_number_agents`로 한다.
7. 음성 시험은 고객이 제품 화면에서 직접 한다. 시험 목록에 다음을 넣는다.
   - 키 1~4와 하위 메뉴
   - 각 안내의 0·9·*
   - 말로 묻기
   - 잘못된 키
   - 미분류 2회
   - 영업외 9
   - 직원 미응답(30초 뒤 부재중 문자)
   - 문자 수신

## 13. 최소 골격
[flow-ars-skeleton.json](flow-ars-skeleton.json)은 `validate_flow`를 통과한 예시 그래프다. 가상 매장이며 노드 15개·edge 29개다. 핵심 루프 하나만 담았다: 메인 2종(영업 중·영업시간 외) + 분류 + 라우터 + 안내 1개 + 문자 안내 1개 + 직원 연결/부재중 문자 + 되묻기 + 종료.
- 하위 메뉴는 §2 표처럼 메뉴 노드와 코드를 늘려 확장한다.
- 골격의 `extraction_prompt`는 이 문서 §2 템플릿을 줄인 것이다. 실제로는 §2 템플릿 전문에 업무의 키 표를 넣어 채운다.
- 착신 번호(`+821000000000`)와 휴일 날짜(`2026-12-25`), 매장 문구는 자리표시자다. 사용자에게 받은 값으로 바꾼다.
- 노드 `position`은 필수다. 필드는 `get_schema`의 구성요소(`BeginFlowNodeData`의 `first_line_type` 필수, `LogicCondition`의 `equations[{left,operator,right}]`와 `operator` `&&`·`||`)를 따른다.

## 14. 조회·확인 업무와 시험 계약
접수·지역 조회·등록값 확인을 더할 때는 [Flow 업무 계약](flow-business-contract.md)을 따른다. 실패 후 접수 또는 대표 연결이 필요하면 warm과 실패 fallback을 반드시 둔다. 모의 시험은 원본을 보존한 별도 변형 그래프를 사용한다.
