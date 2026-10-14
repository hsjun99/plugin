"""Validate and build external Plugin and hosted skill-only ZIPs."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from collections import Counter
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker, SchemaError

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Invalid JSON file {path}: {exc}') from exc


def canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_tool_snapshot(root, catalog):
    snapshot_path = catalog.get('implemented_tools_snapshot')
    require(snapshot_path == 'references/implemented-tools.snapshot.json',
            'Catalog must point at the reviewed implemented-tools snapshot')
    snapshot = load_json(root / snapshot_path)
    implemented = snapshot.get('implemented_tools')
    require(isinstance(implemented, list) and bool(implemented),
            'Implemented-tools snapshot must contain a non-empty list')
    require(all(isinstance(name, str) and name for name in implemented),
            'Implemented-tools snapshot contains an invalid tool name')
    require(len(implemented) == len(set(implemented)),
            'Implemented-tools snapshot contains duplicate tools')

    lock = load_json(root / 'tool-contract-lock.json')
    source = snapshot.get('source', {})
    require(isinstance(lock.get('mcp_commit'), str)
            and re.fullmatch(r'[0-9a-f]{40}', lock['mcp_commit']),
            'Tool contract lock must pin the full source MCP commit')
    require(re.fullmatch(r'[0-9a-f]{64}', lock.get('manifest_sha256', '')),
            'Tool contract lock must pin the source manifest SHA-256')
    require(sorted(lock.get('implemented_tools', [])) == sorted(implemented),
            'Implemented-tools snapshot disagrees with the source contract lock')
    require(lock.get('source_state') in {'clean_commit', 'dirty_worktree_candidate'},
            'Tool contract lock must identify whether contracts come from a clean commit or dirty candidate')
    dirty_contracts = lock.get('dirty_contracts')
    require(isinstance(dirty_contracts, list)
            and all(isinstance(name, str) and name for name in dirty_contracts)
            and len(dirty_contracts) == len(set(dirty_contracts)),
            'Tool contract lock has invalid dirty contract names')
    require((lock['source_state'] == 'dirty_worktree_candidate') == bool(dirty_contracts),
            'Tool contract lock dirty state and dirty contract list disagree')
    provenance_keys = ('mcp_commit', 'manifest_sha256', 'source_manifest_sha256',
                       'source_state', 'dirty_contracts')
    require(source == {key: lock[key] for key in provenance_keys},
            'Bundled tool snapshot provenance disagrees with the source contract lock')
    for key in ('native_tools', 'public_excluded'):
        require(isinstance(lock.get(key), list) and set(lock[key]) <= set(implemented)
                and snapshot.get(key) == lock[key],
                f'Tool contract lock and snapshot disagree on {key}')
    schema_hashes = lock.get('input_schema_sha256', {})
    require(set(schema_hashes) == set(implemented),
            'Tool contract lock must include an input schema digest for every implemented tool')
    snapshot_schemas = snapshot.get('input_schemas', {})
    require(set(snapshot_schemas) == set(implemented),
            'Packaged input schema snapshots must cover every implemented tool')

    schemas = {}
    for name in implemented:
        entry = snapshot_schemas[name]
        require(isinstance(entry, dict) and entry.get('path') == f'tool-schemas/{name}.json',
                f'Invalid packaged input schema path for {name}')
        contract_path = root / 'references' / entry['path']
        contract = load_json(contract_path)
        require(contract.get('name') == name and isinstance(contract.get('inputSchema'), dict),
                f'Invalid packaged input schema contract for {name}')
        schema = contract['inputSchema']
        digest = canonical_sha256(schema)
        require(digest == entry.get('sha256') == schema_hashes.get(name),
                f'Input schema digest mismatch for {name}')
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError(f'Invalid packaged input schema for {name}: {exc.message}') from exc
        schemas[name] = schema
    return set(implemented), schemas


def validate_workflow_capabilities(root, catalog, implemented_tools):
    path = catalog.get('workflow_capabilities')
    require(path == 'references/workflow-capabilities.json',
            'Catalog must point at the workflow capability contract')
    contract = load_json(root / path)
    require(contract.get('schema_version') == 1, 'Unsupported workflow capability schema version')
    require(contract.get('implemented_tools_snapshot') == 'implemented-tools.snapshot.json',
            'Workflow capability contract must identify its implemented-tools snapshot')
    workflows = contract.get('workflows')
    require(isinstance(workflows, list) and bool(workflows),
            'Workflow capability contract must contain workflows')
    workflow_ids = [workflow.get('id') for workflow in workflows if isinstance(workflow, dict)]
    require(len(workflow_ids) == len(workflows) and all(workflow_ids),
            'Workflow capability contract contains an invalid workflow')
    require(len(workflow_ids) == len(set(workflow_ids)),
            'Workflow capability contract contains duplicate workflow IDs')
    required_workflows = {'authoring', 'refinement', 'customer_direct_test', 'operate', 'resume'}
    require(required_workflows.issubset(workflow_ids),
            'Workflow capability contract is missing a required public workflow')

    for workflow in workflows:
        implemented = workflow.get('implemented', {})
        designed = workflow.get('designed', {})
        required = implemented.get('required_tools', [])
        optional = implemented.get('optional_tools', [])
        designed_required = designed.get('required_tools', [])
        designed_optional = designed.get('optional_tools', [])
        for label, names in [('implemented required', required), ('implemented optional', optional),
                             ('designed required', designed_required), ('designed optional', designed_optional)]:
            require(isinstance(names, list) and all(isinstance(name, str) and name for name in names),
                    f"Invalid {label} tool list in workflow {workflow['id']}")
            require(len(names) == len(set(names)),
                    f"Duplicate {label} tool in workflow {workflow['id']}")
        require(not set(required).intersection(optional),
                f"Required and optional tools overlap in workflow {workflow['id']}")
        require(set(required + optional).issubset(implemented_tools),
                f"Workflow {workflow['id']} requires or offers a tool absent from the implemented-tools snapshot")
        require(not designed_required,
                f"Designed tools cannot be hard-required in workflow {workflow['id']}")
        require(not set(designed_optional).intersection(implemented_tools),
                f"Designed optional tools must remain distinct from implemented tools in workflow {workflow['id']}")
        if designed_optional:
            require(isinstance(workflow.get('designed_unavailable_fallback'), str)
                    and workflow['designed_unavailable_fallback'].strip(),
                    f"Workflow {workflow['id']} needs a fallback while designed tools are unavailable")


def validate_skill_tool_references(catalog, implemented_tools):
    designed_registry = catalog.get('designed_tool_references')
    require(isinstance(designed_registry, list)
            and all(isinstance(name, str) and name for name in designed_registry),
            'Catalog designed_tool_references must be a list of tool names')
    require(len(designed_registry) == len(set(designed_registry)),
            'Catalog designed_tool_references contains duplicate tools')
    designed_registry = set(designed_registry)
    require(not designed_registry.intersection(implemented_tools),
            'Catalog classifies an implemented tool as designed-only')

    referenced_designed = set()
    for skill in catalog['skills']:
        name = skill['name']
        tools = skill.get('tools')
        require(isinstance(tools, dict) and set(tools) == {'implemented', 'designed_only'},
                f'Skill {name} must explicitly partition tools into implemented and designed_only')
        implemented = tools['implemented']
        designed_only = tools['designed_only']
        for label, names in [('implemented', implemented), ('designed_only', designed_only)]:
            require(isinstance(names, list) and all(isinstance(tool, str) and tool for tool in names),
                    f'Skill {name} has an invalid {label} tool list')
            require(len(names) == len(set(names)),
                    f'Skill {name} has duplicate {label} tool references')
        require(not set(implemented).intersection(designed_only),
                f'Skill {name} has a tool classified as both implemented and designed-only')
        require(set(implemented).issubset(implemented_tools),
                f'Skill {name} classifies unavailable tools as implemented')
        require(set(designed_only).isdisjoint(implemented_tools),
                f'Skill {name} classifies implemented tools as designed-only')
        unknown_designed = set(designed_only) - designed_registry
        require(not unknown_designed,
                f'Skill {name} has unclassified designed-only tools: {sorted(unknown_designed)}')
        referenced_designed.update(designed_only)
    require(referenced_designed == designed_registry,
            'Catalog designed_tool_references must exactly cover skill designed-only references')


def validate_tool_examples(root, implemented_tools, schemas):
    examples_path = root / 'references/workflow-examples.md'
    blocks = list(re.finditer(r'```mcp-call\s*\n(.*?)```', examples_path.read_text(), flags=re.DOTALL))
    require(bool(blocks), f'No MCP call examples found in {examples_path}')
    for index, match in enumerate(blocks, start=1):
        try:
            example = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError(f'Invalid mcp-call JSON in {examples_path}, block {index}: {exc}') from exc
        require(isinstance(example, dict) and isinstance(example.get('tool'), str),
                f'Invalid tool invocation in {examples_path}, block {index}')
        name = example['tool']
        require(name in implemented_tools,
                f'{examples_path}, block {index} calls a tool absent from the implemented-tools snapshot: {name}')
        require(set(example) == {'tool', 'arguments'} and isinstance(example['arguments'], dict),
                f'{examples_path}, block {index} must have only tool and object arguments')
        validator = Draft202012Validator(schemas[name], format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(example['arguments']),
                        key=lambda error: tuple(str(part) for part in error.absolute_path))
        if errors:
            error = errors[0]
            location = '.'.join(str(part) for part in error.absolute_path) or '<arguments>'
            raise ValueError(f'Input schema validation failed for {name} in {examples_path}, block {index} '
                             f'at {location}: {error.message}')


def crosscheck_mcp_source(root, mcp_root=None, manifest_path=None):
    lock = load_json(root / 'tool-contract-lock.json')
    if manifest_path:
        manifest_file = Path(manifest_path).resolve()
    elif mcp_root:
        manifest_file = Path(mcp_root).resolve() / 'src/vox_mcp/contracts/manifest.json'
    else:
        return
    require(manifest_file.is_file(), f'MCP manifest not found: {manifest_file}')
    contracts_dir = manifest_file.parent
    manifest_bytes = manifest_file.read_bytes()
    require(hashlib.sha256(manifest_bytes).hexdigest() == lock['manifest_sha256'],
            'Supplied MCP manifest digest does not match the pinned source')
    manifest = json.loads(manifest_bytes)
    require(manifest.get('source_manifest_sha256') == lock.get('source_manifest_sha256'),
            'Supplied MCP source manifest checksum does not match the pinned source')
    native = lock.get('native_tools', [])
    embedded_only = set(manifest.get('exposure', {}).get('embedded_only', []))
    api_tools = [name for name in manifest.get('implemented_tools', []) if name not in embedded_only]
    require(sorted([*api_tools, *native]) == sorted(lock['implemented_tools']),
            'Supplied MCP implemented tool list does not match the packaged snapshot')
    require(sorted(manifest.get('exposure', {}).get('public_excluded', [])) == lock.get('public_excluded', []),
            'Supplied MCP public exposure exclusions do not match the packaged snapshot')
    for name, expected_digest in lock['input_schema_sha256'].items():
        contract_path = contracts_dir / f'{name}.json'
        contract = load_json(contract_path)
        require(canonical_sha256(contract.get('inputSchema')) == expected_digest,
                f'Supplied MCP input schema does not match the pinned source for {name}')
    if mcp_root:
        checkout = str(Path(mcp_root).resolve())
        result = subprocess.run(['git', '-C', checkout, 'rev-parse', 'HEAD'],
                                check=True, capture_output=True, text=True)
        require(result.stdout.strip() == lock['mcp_commit'],
                'Supplied MCP checkout commit does not match the pinned source')
        changed = subprocess.run(
            ['git', '-C', checkout, 'diff', '--name-only', 'HEAD', '--', 'src/vox_mcp/contracts'],
            check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        untracked = subprocess.run(
            ['git', '-C', checkout, 'ls-files', '--others', '--exclude-standard',
             '--', 'src/vox_mcp/contracts'],
            check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        dirty_contracts = sorted(Path(path).stem for path in {*changed, *untracked}
                                 if path.endswith('.json'))
        require(dirty_contracts == lock['dirty_contracts'],
                'Supplied MCP dirty contract set does not match the candidate snapshot')
        require((lock['source_state'] == 'dirty_worktree_candidate') == bool(dirty_contracts),
                'Supplied MCP checkout state does not match the candidate snapshot')


def validate(root):
    catalog = load_json(root / 'catalog.json')
    entries = catalog['skills']
    names = [entry['name'] for entry in entries]
    require(bool(names) and len(names) == len(set(names)), 'Duplicate or empty catalog skills')
    paths = [entry['path'] for entry in entries]
    actual = sorted(root.glob('skills/*/SKILL.md'))
    require(len(paths) == len(set(paths)), 'Duplicate catalog paths')
    require(set(paths) == {p.relative_to(root).as_posix() for p in actual},
            'Catalog paths must exactly match skill files')
    require(dict(Counter(entry['layer'] for entry in entries)) == catalog['layers'],
            'Catalog layer counts do not match skills')

    implemented_tools, schemas = validate_tool_snapshot(root, catalog)
    validate_skill_tool_references(catalog, implemented_tools)
    validate_workflow_capabilities(root, catalog, implemented_tools)
    validate_tool_examples(root, implemented_tools, schemas)

    for entry in entries:
        path = root / entry['path']
        require(entry['path'] == f"skills/{entry['name']}/SKILL.md", 'Skill name/path mismatch')
        parts = path.read_text().split('---', 2)
        require(len(parts) == 3 and not parts[0].strip(), f'Missing frontmatter: {path}')
        frontmatter = yaml.safe_load(parts[1])
        require(isinstance(frontmatter, dict), f'Invalid frontmatter: {path}')
        require(frontmatter.get('name') == entry['name'], f'Frontmatter name mismatch: {path}')
        require(frontmatter.get('description') == entry['description'],
                f'Frontmatter description mismatch: {path}')
        require(frontmatter.get('metadata', {}).get('layer') == entry['layer'],
                f'Catalog layer mismatch: {path}')

    codex = load_json(root / '.codex-plugin/plugin.json')
    claude = load_json(root / '.claude-plugin/plugin.json')
    for key in ('name', 'version', 'description', 'author', 'skills', 'mcpServers'):
        require(codex.get(key) == claude.get(key) and key in codex,
                f'Host manifests disagree on {key}')
    require(codex['name'] == 'vox-ai', 'Unexpected plugin name')
    require(re.fullmatch(r'\d+\.\d+\.\d+', codex['version']), 'Invalid release version')
    require(codex['skills'] == './skills/' and codex['mcpServers'] == './.mcp.json',
            'Unexpected component paths')
    servers = load_json(root / '.mcp.json')['mcpServers']
    require(set(servers) == {'vox-ai', 'vox-docs'},
            'Public bundle must declare exactly the vox-ai and vox-docs MCP servers')
    require(servers['vox-ai'] == {'type': 'http', 'url': 'https://mcp.tryvox.co/mcp'},
            'Public bundle must use the reviewed public MCP connection without credentials')
    require(servers['vox-docs'] == {'type': 'http', 'url': 'https://docs.tryvox.co/mcp'},
            'Public bundle must connect the public docs MCP without credentials')
    for host, location in [('codex', '.agents/plugins/marketplace.json'),
                           ('claude', '.claude-plugin/marketplace.json')]:
        market = load_json(root / location)
        require(market['name'] == 'vox-ai' and len(market['plugins']) == 1,
                f'Unexpected {host} marketplace')
        plugin = market['plugins'][0]
        expected_source = {'source': 'local', 'path': './'} if host == 'codex' else './'
        require(plugin['name'] == codex['name'] and plugin['source'] == expected_source,
                f'Invalid {host} marketplace source')

    shared = sorted([*actual, *(p for p in (root / 'references').rglob('*') if p.is_file())])
    for path in shared:
        require(path.is_file() and not path.is_symlink(), f'Not a regular file: {path}')
        content = path.read_text()
        require('/Users/' not in content and '[[share/' not in content,
                f'Private path in {path}')
        if path.suffix == '.md':
            for href in re.findall(r'\]\(([^)]+)\)', content):
                if '://' not in href and not href.startswith('#'):
                    target = (path.parent / href.split('#')[0]).resolve()
                    require(target.is_relative_to(root.resolve()) and target.is_file(),
                            f'Invalid reference in {path}: {href}')
    return codex['version'], len(entries), shared


def build(root=ROOT, mcp_root=None, manifest_path=None):
    version, count, shared = validate(root)
    crosscheck_mcp_source(root, mcp_root=mcp_root, manifest_path=manifest_path)
    digests = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared}
    digest = hashlib.sha256(json.dumps(digests, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    manifest = {'version': version, 'skills_count': count, 'sha256': digest,
                'capability_directories': ['/workspace/vox-ai/skills'], 'files': digests}
    (root / 'bundle-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    destination = root / 'dist'
    destination.mkdir(exist_ok=True)
    common = shared + [root / 'bundle-manifest.json', root / 'catalog.json']
    external = common + [root / '.codex-plugin/plugin.json', root / '.claude-plugin/plugin.json',
                         root / '.mcp.json', root / 'README.md']
    for name, paths in [('vox-ai-plugin.zip', external), ('vox-ai-skills.zip', common)]:
        with zipfile.ZipFile(destination / name, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(paths):
                info = zipfile.ZipInfo(str(path.relative_to(root)), date_time=(2026, 9, 16, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(destination / 'vox-ai-skills.zip') as hosted:
        require(not any('plugin.json' in n or 'mcp.json' in n for n in hosted.namelist()),
                'Host connection leaked into skill-only archive')
        with zipfile.ZipFile(destination / 'vox-ai-plugin.zip') as external_zip:
            require(all(hosted.read(name) == external_zip.read(name) for name in hosted.namelist()),
                    'Shared archives differ')
    print(json.dumps({'skills': count, 'shared_sha256': digest, 'links': 'valid',
                      'tool_examples': 'schema-valid', 'artifacts': 2}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mcp-root', help='Optional pinned MCP checkout for manifest/schema cross-check')
    parser.add_argument('--manifest', help='Optional explicit implemented-tools manifest path')
    args = parser.parse_args()
    build(mcp_root=args.mcp_root, manifest_path=args.manifest)


if __name__ == '__main__':
    main()
