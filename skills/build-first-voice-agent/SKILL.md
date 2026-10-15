---
name: build-first-voice-agent
description: "URL·파일·설명으로 vox.ai의 첫 Single 음성 에이전트를 만들고 Manual·결과 저장·직접 시험까지 연결할 때 사용한다."
metadata:
  product: vox.ai
  layer: architect
  status: stable
---

# build-first-voice-agent

제품 호출에는 [공통 실행 계약](../../references/execution-contract.md)을 적용한다. 내장/외부의 질문·음성·파일·버전·게시·보고 차이는 [호스트 연결](../../references/host-adapters.md)을 따르고, 호스트 규칙이 이 절차보다 우선한다. 도구는 연결된 서버가 제공하는 실제 이름과 스키마를 확인한 뒤 사용한다. 현재 구현 capability는 [구현 도구 스냅샷](../../references/implemented-tools.snapshot.json)과 [워크플로 capability 표](../../references/workflow-capabilities.json)에 있다.

## 먼저 읽을 상태와 판단
기존 agent를 고치는 요청인지 새 구축인지 구분한다. 기존 대상이 있으면 [현재 상태](../explore-agent-context/SKILL.md)를 읽는다. 자료를 검토해 prompt·Manual·지식 중 둘 위치는 [근거 정리](../knowledge-grounding/SKILL.md)에서 결정하고, 업무 유형은 [음성 업무 설계](../voice-agent-design/SKILL.md)로 판단한다. 핵심 업무·방향·실제 완료 결과를 짧게 제안하고, 묻는 범위는 [정할 것](#정할-것)을 따른다. 새 구축이면 [유형 선택](../voice-agent-design/SKILL.md)을 적용하고, 첫 `save_agent` 전에 유형과 이유를 한 줄로 알린다(무인 실행이어도). 기본은 Single + Manual이며 Flow로 정해지면 이 스킬 대신 [Flow 절차](../agents-platform/SKILL.md)를 따른다.

## 정할 것
칸의 뜻·선택지·기본값은 [정할 칸](../../references/decision-slots.json)에 있고 선택지를 만들 때만 연다. 먼저 `direction`을 정하고 그 방향의 1등급 칸만 본다.
- 거는 전화(명단·시스템): `campaign`·`list_columns`·`success`·`number_source`·`persuasion`·`script_mode`
- 받는 전화: `scope`·`staffed_hours`·`handoff`·`intake_fields`

답이 설정을 바꾸고, 자료·이전 답으로 알 수 없고, 틀리면 다시 만들어야 하는 칸만 묻는다. 나머지는 기본값으로 만들고 마무리 보고의 가정에 적는다. `value` 칸(번호 출처·넘길 곳·문자 링크 등)은 지어내지 않고, 모르면 그 동작을 빼거나 미정으로 알린다. "질문 없이·바로·알아서"이거나 답을 받을 수 없는 실행이면 묻지 않는다.

## 구축

### 모델 고르기
새 agent 모델을 정하거나 사용자가 요청한 기존 agent 모델을 바꿀 때마다 `list_models(kind=llm)`을 호출한다. 사용자가 모델 ID·모델명·계열·공급사를 직접 지정하지 않았다면 “좋은 모델로”, “최신 모델로”, “성능 좋게”, “빠른 모델”, “비용이 낮은 모델”, “품질이 좋은 모델” 같은 속도·비용·품질·최신 선호는 지정으로 보지 않는다. 호스트 자신의 모델 계열이라는 이유로 고르지 않으며, 기존 agent 모델은 변경 요청이 없으면 보존한다.

- 결과에 `featured` 필드 자체가 없는 구 API에서는 새 agent의 `data.llm`을 생략해 서버 기본값을 쓴다. 사용자가 모델·계열·공급사를 지정했으면 그 선택을 이 구 API로 명시 저장할 수 없다고 알린다. 기존 agent 모델 변경도 실행하지 않고 현재 값을 보존한다. 모델이 들어 있는 템플릿은 선택하지 말고 `save_agent(mode=create)`에서 `data.llm`을 생략한다. `featured` 정보가 있는데 활성 featured 항목이 하나도 없다면 지정 없는 요청은 추천 모델을 찾지 못했다고 알리고 임의 선택하지 않는다.
- 추천 기준은 `featured=true`, `deprecated=false`인 모델이며, `display_order`가 가장 작은 항목이 이번 출시의 vox 추천 1순위다. 지정이 없으면 전역 추천 1순위의 `model` 값을 `data.llm.model`에 그대로 넣는다. 이는 표시 이름과 다른 routing group 키일 수 있다.
- featured 추천 범위 밖의 모델은 사용자가 모델 ID·모델명·계열·공급사를 직접 지정한 경우에만 선택한다. 정확한 모델 ID는 조회 결과의 `model`과, 모델명은 `display_name`과 정확히 일치시킨다. `deprecated=true` 항목은 정확한 모델 ID를 직접 지정한 경우에만 허용한다. 사용자가 계열이나 공급사를 지정하면 해당 범위에서 deprecated가 아닌 featured 항목 중 `display_order`가 가장 작은 것을 고른다. 범위 안에 featured 항목이 없으면 deprecated가 아닌 항목 중 순서가 가장 앞선 것을 선택한다. 저장 시 선택한 모델이 `featured=true`이고 `deprecated=false`인 추천 항목이 아니면 반드시 `이 모델은 vox 추천 모델이 아닙니다(추천: <featured 1순위 display_name>)` 한 줄을 알린다. 활성 featured 추천이 없으면 추천 이름을 만들지 말고 같은 문구의 추천 값을 `현재 featured 추천 모델 없음`으로 표시한다. 해당 ID·계열·공급사의 사용 가능한 항목이 조회 결과에 없으면 저장하지 않는다. 모델 ID를 추측하거나 다른 필드에서 만들어 내지 않는다.
- 선택을 한 줄로 알린다. 예: `모델: <display_name> (vox 추천 1순위)`, `모델: <display_name> (요청한 계열의 vox 추천 모델)`, `모델: <display_name> (사용자 지정)`, 또는 `모델: <display_name> (요청한 계열, vox 추천 모델 아님)`. 추천이 아닌 모델은 위의 필수 알림도 저장 전에 별도로 한 줄 표시한다. 사용자가 deprecated ID를 정확히 요청했다면 그 사실도 표시한다. 구 API fallback은 `모델: vox 추천 기본값 (구 API 서버 기본값)`이라고 알린다.
- `save_agent(mode=create)`에서는 선택한 `model`을 `data.llm.model`에 넣는다. 템플릿 생성은 `instantiate_agent_template` 성공 뒤 `get_agent`로 `head_revision`과 현재 `data.llm`을 읽고, `data.llm`의 기존 지원 필드는 보존하면서 `model`만 선택값으로 바꿔 `save_agent(mode=update)`에 보낸다. 방금 읽은 revision을 `expected_head_revision`으로 쓰고 다른 설정 묶음은 보내지 않는다. `llm` 묶음은 통째로 교체되므로 temperature 등 기존 값을 빠뜨리지 않는다.

### 구축 순서
1. Manual 목록(이름·트리거·제외절)과 프롬프트·Manual·지식 분담을 정한다. Manual 본문·분기·도구 작성은 [Manual 작성](../manual-authoring/SKILL.md)을 따른다. 외부 동작이 필수라면 [도구 연결](../connect-agent-tools/SKILL.md)의 의존성을 먼저 확인한다.
2. 시작점을 고른다. 새 agent는 위 [모델 고르기](#모델-고르기) 규칙을 템플릿과 직접 생성 모두에 적용한다. 맞는 업무 템플릿이 있으면 `list_agent_templates` → `get_agent_template`로 내용을 확인하고 `instantiate_agent_template`(payload.name)으로 Single을 만든다. 템플릿은 자동 게시되지 않으며 부분 실패 결과를 그대로 읽는다. 템플릿의 기본 프롬프트와 Manual은 업종·방향·완료 문구가 새 업무와 충돌할 수 있으므로 그대로 두지 않고 고쳐 쓴다. 없으면 `save_agent(mode=create)`로 Single을 만들고 선택 모델은 `data.llm.model`, 다시 쓴 프롬프트는 `data.prompt.prompt`에 넣는다. 반환된 `agent_id`를 보존한다.
3. `get_agent` 또는 `list_manuals`로 현재 `head_revision`을 읽은 뒤 Manual마다 `save_manual`로 본문을 저장한다(생성이면 `mode=create`와 같은 `agent_id`, `payload.expected_head_revision`, `name`, `trigger`, `content`; 템플릿이 만든 Manual은 수정). 이 호출이 Manual을 에이전트에 연결하며, Manual을 저장할 때마다 revision이 바뀌므로 다음 Manual 전에 다시 읽는다. 다른 Manual이 `@manual:<manual_id>`로 가리킬 대상은 UUID가 필요하므로 먼저 저장한다. 폐기된 `manualIds`를 agent payload에 만들지 않는다. Manual이 쓰는 내장 도구는 본문에서 `@tool:이름`, API 도구는 `list_tools`가 돌려준 `@tool:<tool_id>`로 참조해야 실행된다.

4. `list_manuals`로 Manual 수와 진단 건수를, `get_manual(agent_id, manual_id)`와 `get_agent(agent_id)`로 본문·참조·현재 revision을 재조회한다. 넓은 참고 자료가 필요하거나 사용자가 요청한 경우에만 [지식](../knowledge-grounding/SKILL.md)(텍스트·URL)을 연결한다. 통화 후 추출·내부 저장이 필요하면 [결과 설계](../post-call-result-design/SKILL.md)에서 통화 중 상태·실행과 postCall 결과를 구분하고, 필요한 설정만 [결과 설정](../configure-call-results/SKILL.md)으로 연결한다. 외부 연동은 [도구](../connect-agent-tools/SKILL.md)에서 실제 실행 경로를 확인한다. 실제 입력·ID 흐름은 [완성된 합성 여정](../../references/workflow-examples.md)에 있다. 저장 뒤에는 재조회한 본문에 [운영 수준 점검](../manual-authoring/SKILL.md#운영-수준-점검)을 적용해 전체 경로를 검토하고, 실제 결함만 고쳐 다시 저장한다.
5. 저장한 상태를 `create_agent_version`으로 버전에 남긴다(반환된 버전 번호 보존, `list_agent_versions`로 확인). 운영에 쓰려면 사용자에게 어느 버전을 production으로 지정할지 요약해 확인받고 `publish_agent_version`을 호출한 뒤 `get_agent`(production)로 재조회한다. 게시는 번호·발신 경로에 바로 영향을 주며 모든 의존성의 불변 게시가 아니다.
6. 이미 가진 번호에 연결하려면 [번호 연결](../connect-phone-service/SKILL.md), 발신하려면 [발신 운영](../operate-outbound-and-followup/SKILL.md), 결과 확인은 [통화 근거](../inspect-call-evidence/SKILL.md)로 이어간다. 음성 시험은 [직접 음성 시험](../prepare-voice-test/SKILL.md)에서 고객이 직접 한다. 번호 획득은 웹에서만 하며 첫 체험의 필수 단계가 아니다.

내장 도구 선택·참조, 주소 확인 절차와 텍스트/음성 시험 한계는 [Manual 작성](../manual-authoring/SKILL.md#도구-쓰기-tool) 및 [도구별 결과](../manual-authoring/SKILL.md#내장-도구별-신호와-결과)를 따른다.

## 공통 prompt 작성
새 Single 또는 공통 prompt 전체를 작성할 때는 공통 음성 규칙을 `# 말투와 발화`에 한 번만 넣고 Manual마다 복사하지 않는다. 실제 발화 문구를 쓰거나 검토할 때 [음성 프롬프트 기본 지침](../../references/voice-prompt-guidance.md)을 적용한다. 기존 Manual만 좁게 고치면 요청 범위를 유지한다. 나머지 prompt·Manual 구조는 [Manual 작성](../manual-authoring/SKILL.md)을 따른다.

## 부분 성공과 전달
Single만 저장됐다면 그 `agent_id`에서 Manual 생성 단계를 계속한다. Manual 저장 성공 뒤에는 같은 `agent_id`·`manual_id`로 확인한다. 게시 응답이 불명이면 `list_agent_versions`/`get_agent`로 production 상태를 읽고 다시 호출하지 않는다. `409` revision conflict는 최신 상태를 다시 읽고 의도를 다시 적용할 때만 처리하며, unknown 응답은 새 Single·Manual 생성이나 같은 쓰기로 자동 재시도하지 않는다. Agent 저장 성공을 시험 성공으로 보고하지 않는다. 실제 예약이 목표인데 연동이 없으면 그 결손을 알리고 사용자 목표를 유지한다.

사용자가 변경 의견을 주거나 새 대화에서 이어서 고치려 하면 [edit-manual-safely](../edit-manual-safely/SKILL.md)의 '피드백·재개 반영 순서'를 따른다.

## 마무리 보고
저장과 점검을 마치면 아래 순서로 항목마다 한두 줄씩 알린다.
1. **만든 것**: 유형과 이유 한 줄, Manual 이름 목록, 연결한 지식·도구·통화 결과 항목.
2. **점검 결과**: 다시 읽은 본문을 '운영 수준 점검'과 대조한 결과와 고친 것.
3. **가정과 확인할 것**: 사용자가 주지 않아 가정한 값(번호·시간·정책), 그대로 말하게 한 문구 중 고객 확인이 필요한 것, 개인정보를 받는다면 수집·녹취 안내가 필요한지.
4. **한계**: 지금 연결하지 못한 것(예: 실제 예약 시스템 연동 없음)과 그 때문에 통화에서 생기는 일.
5. **다음 할 일**: 체크리스트로 쓴다.
   - [ ] 직접 시험할 대화 3개(정상 / 예외·거절 / 위급·연결)
   - [ ] 번호 연결과 게시 전 확인할 것
   - [ ] 출시 뒤 첫 주에 볼 것: 결과별 종료 비율, 연결 실패, 도중 종료, 같은 질문 반복

## 업무 판단

첫 업무 선택·외부 의존성은 [업무 판단 기준](../../references/workflow-guidance.md)을 읽는다. 고객의 중요도, 자료에서 보이는 반복성과 업무 경계, 지금 확인 가능한 결과를 비교해 첫 완료 지점을 제안한다. 독립적인 준비는 진행하고, 결정을 기다려야 하는 실행은 구분한다.

내부 접수가 목표라면 Manual의 질문과 결과 필드를 함께 설계하되, 통화 중 필요한 상태·실행과 통화 후 추출·저장할 결과를 먼저 나눈다. 번호 연결·발신·통화 조회는 연결된 도구가 목록에 있을 때 위 단계로 진행하고, 없으면 해당 단계가 막혔다고 알린다.
