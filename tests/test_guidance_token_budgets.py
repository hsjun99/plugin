"""Keep skill and voice-guidance loading budgets tied to the frozen 0.2.13 baseline."""
import math
import re
import unittest
from pathlib import Path

import tiktoken


ROOT = Path(__file__).resolve().parents[1]

# Exact o200k_base counts from baseline e14f540. Per-file headroom allows focused
# semantic additions; the tighter aggregate cap prevents moving the whole corpus
# above baseline to hide concentrated growth.
BASELINE_SKILL_TOKENS = {
    'skills/agents-platform/SKILL.md': 3142,
    'skills/build-first-voice-agent/SKILL.md': 4322,
    'skills/cli-authoring/SKILL.md': 553,
    'skills/configure-call-results/SKILL.md': 512,
    'skills/configure-supporting-channel/SKILL.md': 432,
    'skills/connect-agent-tools/SKILL.md': 698,
    'skills/connect-phone-service/SKILL.md': 786,
    'skills/dashboard-navigation/SKILL.md': 528,
    'skills/edit-manual-safely/SKILL.md': 1335,
    'skills/explore-agent-context/SKILL.md': 541,
    'skills/inspect-call-evidence/SKILL.md': 578,
    'skills/knowledge-grounding/SKILL.md': 730,
    'skills/manual-authoring/SKILL.md': 5519,
    'skills/operate-outbound-and-followup/SKILL.md': 1280,
    'skills/post-call-result-design/SKILL.md': 486,
    'skills/prepare-voice-test/SKILL.md': 905,
    'skills/product-documentation/SKILL.md': 653,
    'skills/resume-agent-work/SKILL.md': 1783,
    'skills/review-call-performance/SKILL.md': 634,
    'skills/review-shared-impact/SKILL.md': 497,
    'skills/tool-integration-design/SKILL.md': 502,
    'skills/troubleshoot-agent-tool/SKILL.md': 584,
    'skills/try-and-improve-voice-agent/SKILL.md': 1058,
    'skills/tune-voice-behavior/SKILL.md': 786,
    'skills/voice-agent-design/SKILL.md': 3074,
    'skills/voice-interaction-design/SKILL.md': 519,
}

# Count each unique file once. The common voice guide did not exist at baseline.
HOTPATH_BASELINE_TOKENS = {
    'skills/build-first-voice-agent/SKILL.md': 4322,
    'skills/manual-authoring/SKILL.md': 5519,
    'skills/voice-agent-design/SKILL.md': 3074,
    'references/voice-prompt-guidance.md': 0,
    'references/manual-examples.md': 2198,
}
SKILL_BASELINE_TOTAL = sum(BASELINE_SKILL_TOKENS.values())
HOTPATH_BASELINE_TOTAL = sum(HOTPATH_BASELINE_TOKENS.values())
HOTPATH_TOKEN_CAP = 16322  # User-approved +8% ceiling: floor(15,113 * 1.08).

# The checklist and nine-step prose in manual-authoring restore the inspected
# 0.2.14 operating guidance. The old 5% cap (5,794) cannot contain it; 6,600 is
# just above that complete historical file's 6,585 tokens. The aggregate
# hotpath ceiling remains the stricter guard against unrelated growth.
ENTRY_SKILL_CAPS = {
    'skills/build-first-voice-agent/SKILL.md': 4538,
    'skills/manual-authoring/SKILL.md': 6600,
    'skills/voice-agent-design/SKILL.md': 3227,
}

# v0.2.16 decision-slots additions. These are new, separate caps; the existing
# entry caps, the 34,058 skill-total cap and the 16,322 hotpath cap are unchanged.
BUILD_FIRST_DECISION_CAP = 3367
HOST_ADAPTERS_CAP = 2750
DECISION_SLOTS_JSON_CAP = 2500

HOTPATH_FILES = (
    'skills/build-first-voice-agent/SKILL.md',
    'skills/manual-authoring/SKILL.md',
    'skills/voice-agent-design/SKILL.md',
    'references/voice-prompt-guidance.md',
    'references/manual-examples.md',
)


class GuidanceTokenBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = tiktoken.get_encoding('o200k_base')

    def token_count(self, relative_path):
        return len(self.encoder.encode((ROOT / relative_path).read_text(encoding='utf-8')))

    @staticmethod
    def current_skill_paths():
        return sorted(
            str(path.relative_to(ROOT))
            for path in (ROOT / 'skills').rglob('SKILL.md')
        )

    def assert_at_most_five_percent_over(self, actual, baseline, label):
        upper = math.floor(baseline * 1.05)
        self.assertLessEqual(actual, upper, f'{label}: {actual} is above {upper}')

    def test_skill_inventory_matches_the_frozen_baseline(self):
        actual = set(self.current_skill_paths())
        self.assertTrue(set(BASELINE_SKILL_TOKENS).issubset(actual))

    def test_core_voice_guide_has_four_direct_skill_routes(self):
        linked_skills = {
            path for path in self.current_skill_paths()
            if 'voice-prompt-guidance.md' in (ROOT / path).read_text(encoding='utf-8')
        }
        self.assertEqual(linked_skills, {
            'skills/build-first-voice-agent/SKILL.md',
            'skills/manual-authoring/SKILL.md',
            'skills/edit-manual-safely/SKILL.md',
            'skills/voice-interaction-design/SKILL.md',
        })

    def test_failure_guide_is_linked_only_from_diagnosis_skills(self):
        linked_skills = {
            path for path in self.current_skill_paths()
            if 'voice-prompt-failure-guidance.md' in (ROOT / path).read_text(encoding='utf-8')
        }
        self.assertEqual(linked_skills, {
            'skills/inspect-call-evidence/SKILL.md',
            'skills/try-and-improve-voice-agent/SKILL.md',
        })

    def test_each_skill_has_a_baseline_derived_cap(self):
        for path in self.current_skill_paths():
            with self.subTest(path=path):
                actual = self.token_count(path)
                baseline = BASELINE_SKILL_TOKENS.get(path)
                # The global +5% corpus budget is stricter than this local cap.
                # A 10% allowance or 200 tokens, whichever is larger, gives a
                # changed skill room for required detail while stopping outliers.
                # New skills have no historical per-file budget; they receive a
                # 2,000-token ceiling and still count toward the aggregate cap.
                local_cap = (baseline + max(200, math.ceil(baseline * 0.10))
                             if baseline is not None else 2000)
                cap = max(local_cap, ENTRY_SKILL_CAPS.get(path, 0))
                self.assertLessEqual(actual, cap, f'{path}: {actual} tokens exceeds {cap}')

    def test_entry_skills_stay_within_declared_caps(self):
        for path, cap in ENTRY_SKILL_CAPS.items():
            with self.subTest(path=path):
                self.assertLessEqual(self.token_count(path), cap)

    def test_decision_slots_additions_stay_within_their_new_caps(self):
        for path, cap in (
            ('skills/build-first-voice-agent/SKILL.md', BUILD_FIRST_DECISION_CAP),
            ('references/host-adapters.md', HOST_ADAPTERS_CAP),
            ('references/decision-slots.json', DECISION_SLOTS_JSON_CAP),
        ):
            with self.subTest(path=path):
                actual = self.token_count(path)
                self.assertLessEqual(actual, cap, f'{path}: {actual} tokens exceeds {cap}')

    def test_skill_total_stays_within_five_percent_of_baseline(self):
        paths = self.current_skill_paths()
        actual = sum(self.token_count(path) for path in paths)
        self.assert_at_most_five_percent_over(actual, SKILL_BASELINE_TOTAL, 'all SKILL.md files')

    def test_voice_authoring_hotpath_stays_within_user_token_cap(self):
        actual = sum(self.token_count(path) for path in HOTPATH_FILES)
        self.assertEqual(HOTPATH_TOKEN_CAP, math.floor(HOTPATH_BASELINE_TOTAL * 1.08))
        self.assertLessEqual(actual, HOTPATH_TOKEN_CAP,
                             f'voice authoring hotpath: {actual} is above {HOTPATH_TOKEN_CAP}')

    def test_manual_authoring_checklist_has_inspectable_continuous_items(self):
        text = (ROOT / 'skills/manual-authoring/SKILL.md').read_text(encoding='utf-8')
        start = text.index('## 운영 수준 점검')
        end = text.index('\n## Manual이 통화에서 쓰이는 방식', start)
        checklist = text[start:end]
        numbers = [int(value) for value in re.findall(r'(?m)^(\d+)\.\s', checklist)]
        self.assertGreaterEqual(len(numbers), 9)
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        for phrase in (
            '실패하면 다시 부르지 않고',
            '최대 2회. 넘으면 …',
            '…은 제외한다(○○ 담당)',
            '부작용이 있는 도구는 고객 동의 뒤 호출한다',
            '요청 접수·전송',
            '고객의 수신·이용 가능',
            '업무 완료',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, checklist)

    def test_manual_authoring_keeps_concrete_branch_and_return_rules(self):
        text = (ROOT / 'skills/manual-authoring/SKILL.md').read_text(encoding='utf-8')
        for phrase in (
            '관찰 가능한 확인점(필요하면 화면 상태)을 정해 그곳까지만 안내한 뒤 답을 기다린다',
            '반복에는 상한을 둔다: "한 번만", "최초 포함 최대 2회". 넘었을 때의 행동도 적는다.',
            '이미 결과를 분명히 들었거나 단순 안내·고정 고지문·낭독 Flow인 경우 확인 질문을 덧붙이지 않는다',
            '실제 화면 경로나 이름은 확인된 자료가 있을 때만 쓴다',
            '뒤에서 쓸 값은 "…을 기억한다"로 적는다',
            '확인된 값·완료한 점검·하위 Manual 결과를 유지해 원래 요청의 다음 미완료 단계로 돌아간다',
            '다른 Manual로 넘길 때도 이 절차를 멈추고 `@manual:<id>`를 시작한 뒤 돌아올 지점을 적는다',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_build_first_applies_the_operational_checklist_after_readback(self):
        text = (ROOT / 'skills/build-first-voice-agent/SKILL.md').read_text(encoding='utf-8')
        pointer = '[운영 수준 점검](../manual-authoring/SKILL.md#운영-수준-점검)'
        self.assertEqual(text.count(pointer), 1)
        self.assertIn('저장 뒤에는 재조회한 본문에 ' + pointer + '을 적용', text)

    def test_hotpath_has_no_repeated_long_prose_paragraphs(self):
        paragraphs = {}
        for path in HOTPATH_FILES:
            if path.endswith('/manual-examples.md'):
                continue  # The file consists of worked examples, excluded by design.
            text = (ROOT / path).read_text(encoding='utf-8')
            text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
            for paragraph in re.split(r'\n\s*\n', text):
                normalized = re.sub(r'\s+', ' ', paragraph).strip().lower()
                normalized = re.sub(r'[`*_#>]+', '', normalized)
                if len(normalized) < 150:
                    continue
                if re.search(r'(^|\n)#{1,6}.*(?:예시|example)|\[.*예시', paragraph, re.IGNORECASE):
                    continue
                paragraphs.setdefault(normalized, set()).add(path)

        duplicates = {
            paragraph: paths for paragraph, paths in paragraphs.items() if len(paths) > 1
        }
        self.assertFalse(duplicates, f'repeated hotpath prose: {duplicates}')


if __name__ == '__main__':
    unittest.main()
