import contextlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build import ROOT, build


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'plugin'
        shutil.copytree(ROOT, self.root,
                        ignore=shutil.ignore_patterns('.git', 'dist', '.venv', '__pycache__'))

    def change_json(self, name, change):
        path = self.root / name
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def run_build(self):
        with contextlib.redirect_stdout(io.StringIO()):
            build(self.root)

    def test_reproducible_archives_and_hosted_isolation(self):
        self.run_build()
        before = {p.name: p.read_bytes() for p in (self.root / 'dist').glob('*.zip')}
        self.run_build()
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'dist').glob('*.zip')})
        with zipfile.ZipFile(self.root / 'dist/vox-ai-skills.zip') as hosted:
            self.assertFalse(any(name.startswith('.') for name in hosted.namelist()))
            with zipfile.ZipFile(self.root / 'dist/vox-ai-plugin.zip') as external:
                for name in hosted.namelist():
                    self.assertEqual(hosted.read(name), external.read(name))

    def test_bad_catalog_path_rejected_before_artifacts(self):
        self.change_json('catalog.json', lambda c: c['skills'][0].update(path='skills/missing/SKILL.md'))
        with self.assertRaisesRegex(ValueError, 'Catalog paths'):
            self.run_build()
        self.assertFalse((self.root / 'dist').exists())

    def test_duplicate_skill_rejected(self):
        self.change_json('catalog.json', lambda c: c['skills'].append(c['skills'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.run_build()

    def test_missing_skill_rejected(self):
        (self.root / 'skills/voice-agent-design/SKILL.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Catalog paths'):
            self.run_build()

    def test_frontmatter_mismatch_rejected(self):
        path = self.root / 'skills/voice-agent-design/SKILL.md'
        path.write_text(path.read_text().replace('name: voice-agent-design', 'name: wrong-name'))
        with self.assertRaisesRegex(ValueError, 'Frontmatter name'):
            self.run_build()

    def test_host_versions_must_match(self):
        self.change_json('.claude-plugin/plugin.json', lambda p: p.update(version='9.0.0'))
        with self.assertRaisesRegex(ValueError, 'disagree on version'):
            self.run_build()

    def test_bad_marketplace_source_rejected(self):
        self.change_json('.claude-plugin/marketplace.json',
                         lambda p: p['plugins'][0].update(source='./missing'))
        with self.assertRaisesRegex(ValueError, 'marketplace source'):
            self.run_build()

    def test_public_bundle_cannot_point_at_dev(self):
        self.change_json('.mcp.json', lambda p: p['mcpServers']['vox-ai'].update(
            url='https://mcp.dev.services.tryvox.co/mcp'))
        with self.assertRaisesRegex(ValueError, 'Public bundle'):
            self.run_build()

    def test_docs_connection_must_be_the_public_docs_mcp(self):
        self.change_json('.mcp.json', lambda p: p['mcpServers']['vox-docs'].update(
            url='https://fleek.mintlify.app/mcp'))
        with self.assertRaisesRegex(ValueError, 'docs MCP'):
            self.run_build()

    def test_docs_connection_cannot_be_dropped_or_extended(self):
        self.change_json('.mcp.json', lambda p: p['mcpServers'].pop('vox-docs'))
        with self.assertRaisesRegex(ValueError, 'exactly the vox-ai and vox-docs'):
            self.run_build()

    def change_slots(self, change):
        path = self.root / 'references/decision-slots.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        change(value)
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n',
                        encoding='utf-8')

    def test_decision_slots_reject_profile_key_outside_slots(self):
        self.change_slots(lambda d: d['profiles'][0]['common'].append('missing_slot'))
        with self.assertRaisesRegex(ValueError, 'not defined in slots'):
            self.run_build()

    def test_decision_slots_reject_slot_set_drift(self):
        self.change_slots(lambda d: d['slots'].pop('tone'))
        with self.assertRaisesRegex(ValueError, 'exactly the 24'):
            self.run_build()

    def test_decision_slots_reject_unused_or_duplicate_campaign_keys(self):
        self.change_slots(lambda d: d['campaign_slots']['value'].update(orphan='unused'))
        with self.assertRaisesRegex(ValueError, 'by_campaign keys must match'):
            self.run_build()

    def test_decision_slots_reject_value_slot_without_never_invent(self):
        self.change_slots(lambda d: d['slots']['handoff'].pop('never_invent'))
        with self.assertRaisesRegex(ValueError, 'never_invent'):
            self.run_build()

    def test_decision_slots_reject_default_outside_choices(self):
        self.change_slots(lambda d: d['slots']['persuasion'].update(default='once'))
        with self.assertRaisesRegex(ValueError, 'default is not a choice'):
            self.run_build()

    def test_decision_slots_reject_affects_outside_agent_fields(self):
        self.change_slots(lambda d: d['slots']['tone'].update(affects=['no_such_field.x']))
        with self.assertRaisesRegex(ValueError, 'not an agent field'):
            self.run_build()

    def test_decision_slots_reject_unknown_workflow(self):
        self.change_slots(lambda d: d['profiles'][0].update(workflow='missing'))
        with self.assertRaisesRegex(ValueError, 'unknown workflow'):
            self.run_build()

    def test_decision_slots_reject_internal_ids_hosts_and_urls(self):
        for text in ('시나리오 P3', 'PROD-12', 'Codex', 'https://example.com'):
            with self.subTest(text=text):
                self.change_slots(lambda d, text=text: d['kinds'].update(structure=text))
                with self.assertRaisesRegex(ValueError, 'forbidden pattern'):
                    self.run_build()

    def test_decision_slots_reject_escaped_or_crlf_format(self):
        path = self.root / 'references/decision-slots.json'
        original = path.read_text(encoding='utf-8')
        path.write_bytes(original.replace('\n', '\r\n').encode('utf-8'))
        with self.assertRaisesRegex(ValueError, 'LF'):
            self.run_build()
        path.write_text(original.replace('목소리', '\\uBAA9\\uC18C\\uB9AC', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'forbidden pattern'):
            self.run_build()

    def test_required_workflow_tool_must_be_in_implemented_snapshot(self):
        def remove_save_manual(snapshot):
            snapshot['implemented_tools'].remove('save_manual')
            snapshot['input_schemas'].pop('save_manual')
        self.change_json('references/implemented-tools.snapshot.json', remove_save_manual)

        def remove_lock_entry(lock):
            lock['implemented_tools'].remove('save_manual')
            lock['input_schema_sha256'].pop('save_manual')
        self.change_json('tool-contract-lock.json', remove_lock_entry)
        with self.assertRaisesRegex(ValueError, 'classifies unavailable tools as implemented'):
            self.run_build()

    def test_catalog_rejects_unpartitioned_skill_tool_references(self):
        def remove_partition(catalog):
            next(skill for skill in catalog['skills'] if skill['name'] == 'agents-platform')[
                'tools'] = ['get_organization']
        self.change_json('catalog.json', remove_partition)
        with self.assertRaisesRegex(ValueError, 'must explicitly partition'):
            self.run_build()

    def test_catalog_rejects_duplicate_skill_tool_references(self):
        def add_duplicate(catalog):
            skill = next(skill for skill in catalog['skills'] if skill['name'] == 'agents-platform')
            skill['tools']['implemented'].append('get_organization')
        self.change_json('catalog.json', add_duplicate)
        with self.assertRaisesRegex(ValueError, 'duplicate implemented tool references'):
            self.run_build()

    def test_catalog_rejects_unavailable_tool_as_implemented(self):
        def misclassify(catalog):
            skill = next(skill for skill in catalog['skills'] if skill['name'] == 'configure-supporting-channel')
            tools = skill['tools']
            tools['designed_only'].remove('save_widget')
            tools['implemented'].append('save_widget')
        self.change_json('catalog.json', misclassify)
        with self.assertRaisesRegex(ValueError, 'classifies unavailable tools as implemented'):
            self.run_build()

    def test_catalog_rejects_implemented_tool_as_designed_only(self):
        def misclassify(catalog):
            skill = next(skill for skill in catalog['skills'] if skill['name'] == 'agents-platform')
            tools = skill['tools']
            tools['implemented'].remove('save_manual')
            tools['designed_only'].append('save_manual')
        self.change_json('catalog.json', misclassify)
        with self.assertRaisesRegex(ValueError, 'classifies implemented tools as designed-only'):
            self.run_build()

    def test_catalog_rejects_unclassified_designed_tool(self):
        def add_unclassified(catalog):
            skill = next(skill for skill in catalog['skills'] if skill['name'] == 'agents-platform')
            skill['tools']['designed_only'].append('get_call_v2')
        self.change_json('catalog.json', add_unclassified)
        with self.assertRaisesRegex(ValueError, 'unclassified designed-only tools'):
            self.run_build()

    def test_designed_work_tools_cannot_be_hard_required(self):
        self.change_json('references/workflow-capabilities.json', lambda c:
                         c['workflows'][0]['designed']['required_tools'].append('get_work_context'))
        with self.assertRaisesRegex(ValueError, 'Designed tools cannot be hard-required'):
            self.run_build()

    def test_implemented_tool_cannot_remain_classified_as_designed(self):
        self.change_json('references/workflow-capabilities.json', lambda c:
                         c['workflows'][0]['designed']['optional_tools'].append('list_agents'))
        with self.assertRaisesRegex(ValueError, 'Designed optional tools must remain distinct'):
            self.run_build()

    def test_unavailable_designed_tools_need_a_fallback(self):
        def remove_fallback(c):
            workflow = c['workflows'][0]
            workflow['designed']['optional_tools'].append('open_voice_test_session')
            workflow['designed_unavailable_fallback'] = ''
        self.change_json('references/workflow-capabilities.json', remove_fallback)
        with self.assertRaisesRegex(ValueError, 'needs a fallback'):
            self.run_build()

    def test_invalid_mcp_call_json_is_rejected(self):
        path = self.root / 'references/workflow-examples.md'
        path.write_text(path.read_text().replace(
            '{"tool":"get_organization","arguments":{}}', '{"tool":', 1))
        with self.assertRaisesRegex(ValueError, 'Invalid mcp-call JSON'):
            self.run_build()

    def test_mcp_call_arguments_are_checked_against_input_schema(self):
        path = self.root / 'references/workflow-examples.md'
        path.write_text(path.read_text().replace(
            '"expected_head_revision":7', '"expected_head_revision":"7"', 1))
        with self.assertRaisesRegex(ValueError, 'Input schema validation failed for save_manual'):
            self.run_build()

    def test_mcp_call_requires_expected_head_revision(self):
        path = self.root / 'references/workflow-examples.md'
        path.write_text(path.read_text().replace('"expected_head_revision":7,', '', 1))
        with self.assertRaisesRegex(ValueError, 'Input schema validation failed for save_manual'):
            self.run_build()

    def test_wrong_manual_target_field_is_rejected(self):
        path = self.root / 'references/workflow-examples.md'
        path.write_text(path.read_text().replace(
            '"manual_id":"22222222-2222-4222-8222-222222222222"',
            '"manual":"22222222-2222-4222-8222-222222222222"', 1))
        with self.assertRaisesRegex(ValueError, 'Input schema validation failed for get_manual'):
            self.run_build()

    def test_schema_snapshot_digest_is_checked(self):
        self.change_json('references/tool-schemas/get_manual.json', lambda contract:
                         contract['inputSchema']['properties']['manual_id'].update(minLength=2))
        with self.assertRaisesRegex(ValueError, 'Input schema digest mismatch for get_manual'):
            self.run_build()

    def test_bundled_snapshot_provenance_is_checked(self):
        self.change_json('references/implemented-tools.snapshot.json', lambda snapshot:
                         snapshot['source'].update(mcp_commit='0' * 40))
        with self.assertRaisesRegex(ValueError, 'provenance disagrees'):
            self.run_build()


if __name__ == '__main__':
    unittest.main()
