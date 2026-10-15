import json
import re
import unittest
from pathlib import Path

import tiktoken

from scripts.build import DECISION_SLOT_KEYS, validate_decision_slots

ROOT = Path(__file__).resolve().parents[1]
SLOTS_PATH = ROOT / 'references/decision-slots.json'
JSON_TOKEN_CAP = 2500
LINKING_FILES = {
    'skills/build-first-voice-agent/SKILL.md',
    'references/host-adapters.md',
}


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def markdown_files():
    return sorted(
        path.relative_to(ROOT).as_posix()
        for base in ('skills', 'references')
        for path in (ROOT / base).rglob('*.md')
    )


class DecisionSlotsFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(SLOTS_PATH.read_text(encoding='utf-8'))

    def test_validator_accepts_the_shipped_file(self):
        validate_decision_slots(ROOT)

    def test_file_format_is_raw_utf8_lf_with_one_final_newline(self):
        raw = SLOTS_PATH.read_bytes()
        self.assertNotIn(b'\r', raw)
        self.assertTrue(raw.endswith(b'\n') and not raw.endswith(b'\n\n'))
        self.assertNotIn('\\u', raw.decode('utf-8'))

    def test_json_token_count_stays_within_cap(self):
        encoder = tiktoken.get_encoding('o200k_base')
        actual = len(encoder.encode(SLOTS_PATH.read_text(encoding='utf-8')))
        self.assertLessEqual(actual, JSON_TOKEN_CAP)

    def test_slot_keys_are_exactly_the_defined_set(self):
        self.assertEqual(len(DECISION_SLOT_KEYS), 24)
        self.assertEqual(set(self.data['slots']), DECISION_SLOT_KEYS)

    def test_never_invent_marks_exactly_the_value_slots(self):
        marked = {key for key, slot in self.data['slots'].items() if slot.get('never_invent')}
        values = {key for key, slot in self.data['slots'].items() if slot['kind'] == 'value'}
        self.assertEqual(marked, values)
        self.assertEqual(len(values), 5)

    def test_campaign_slots_cover_every_by_campaign_key_once(self):
        profile = self.data['profiles'][0]
        used = [key for keys in profile['by_campaign'].values() for key in keys]
        defined = [key for group in self.data['campaign_slots'].values() for key in group]
        self.assertEqual(sorted(used), sorted(defined))
        self.assertEqual(len(used), len(set(used)))
        self.assertEqual(set(profile['by_campaign']), set(self.data['choices']['campaign']))

    def test_file_has_no_internal_ids_hosts_paths_or_urls(self):
        text = SLOTS_PATH.read_text(encoding='utf-8')
        for pattern in (r'\b[POD]\d+\b', r'\bI\d\b', r'PROD-', r'/Users/', r'상승비',
                        r'Claude|Codex|Grok|Copilot|코파일럿|ChatGPT|Cursor',
                        r'빈 preset|empty preset', r'https?://'):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, text))


class DecisionSlotsGuidanceTests(unittest.TestCase):
    def test_only_build_first_and_host_adapters_point_to_the_file(self):
        linking = {path for path in markdown_files() if 'decision-slots.json' in read(path)}
        self.assertEqual(linking, LINKING_FILES)

    def test_slot_token_appears_only_inside_the_embedded_host_section(self):
        for path in markdown_files():
            if path != 'references/host-adapters.md':
                with self.subTest(path=path):
                    self.assertNotIn('⟦slot:', read(path))
        text = read('references/host-adapters.md')
        start = text.index('## 내장 Copilot')
        end = text.index('\n## Codex', start)
        self.assertEqual(text.count('⟦slot:'), 1)
        self.assertIn('⟦slot:', text[start:end])

    def test_empty_preset_wording_is_absent(self):
        for path in markdown_files():
            with self.subTest(path=path):
                self.assertIsNone(re.search(r'빈 preset|empty preset', read(path)))

    def test_build_first_names_decision_section_and_value_rule(self):
        text = read('skills/build-first-voice-agent/SKILL.md')
        self.assertIn('## 정할 것', text)
        self.assertIn('[정할 칸](../../references/decision-slots.json)', text)
        self.assertIn('`value` 칸', text)
        for slot in ('campaign', 'list_columns', 'success', 'number_source', 'persuasion',
                     'script_mode', 'scope', 'staffed_hours', 'handoff', 'intake_fields'):
            with self.subTest(slot=slot):
                self.assertIn(f'`{slot}`', text)


if __name__ == '__main__':
    unittest.main()
