"""Regenerate the bundled tool snapshot and contract lock from a pinned MCP checkout.

The implemented set is the manifest ``implemented_tools`` plus the MCP-native tools
(contracts with status ``mcp_native_tool_not_api_bound``), which are registered outside the
manifest, minus ``exposure.embedded_only`` tools, which only the embedded Copilot runtime sees
and this public plugin does not ship. Run ``python3 scripts/build.py --mcp-root <checkout>`` afterwards to cross-check.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.build import ROOT, canonical_sha256, load_json, require

NATIVE_STATUS = 'mcp_native_tool_not_api_bound'
SNAPSHOT_DATE = '2026-10-01'
SCOPE = ('Local MCP source contract candidate. The source worktree state is recorded below; this is not a '
         'deployed-server inventory. A connected host may expose fewer tools or permissions; inspect its live '
         'tools and schemas before acting.')


def git(checkout, *args):
    return subprocess.run(['git', '-C', str(checkout), *args], check=True, capture_output=True, text=True).stdout


def sync(mcp_root, root=ROOT):
    checkout = Path(mcp_root).resolve()
    contracts_dir = checkout / 'src/vox_mcp/contracts'
    manifest_file = contracts_dir / 'manifest.json'
    manifest_bytes = manifest_file.read_bytes()
    manifest = json.loads(manifest_bytes)

    native = sorted(path.stem for path in contracts_dir.glob('*.json')
                    if path.name != 'manifest.json' and load_json(path).get('status') == NATIVE_STATUS)
    require(native, 'No MCP-native tool contracts found')
    embedded_only = set(manifest.get('exposure', {}).get('embedded_only', []))
    api_tools = [name for name in manifest['implemented_tools'] if name not in embedded_only]
    implemented = sorted({*api_tools, *native})
    require(len(implemented) == len(api_tools) + len(native),
            'A native tool is also listed in the manifest implemented tools')
    public_excluded = sorted(manifest.get('exposure', {}).get('public_excluded', []))
    require(set(public_excluded) <= set(implemented), 'public_excluded names an unknown tool')

    changed = git(checkout, 'diff', '--name-only', 'HEAD', '--', 'src/vox_mcp/contracts').splitlines()
    untracked = git(checkout, 'ls-files', '--others', '--exclude-standard',
                    '--', 'src/vox_mcp/contracts').splitlines()
    dirty = sorted(Path(path).stem for path in {*changed, *untracked} if path.endswith('.json'))

    schemas_dir = root / 'references/tool-schemas'
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for stale in schemas_dir.glob('*.json'):
        if stale.stem not in implemented:
            stale.unlink()
    hashes = {}
    schemas = {}
    for name in implemented:
        contract = load_json(contracts_dir / f'{name}.json')
        require(contract.get('name') == name and isinstance(contract.get('inputSchema'), dict),
                f'Invalid MCP contract for {name}')
        (schemas_dir / f'{name}.json').write_text(
            json.dumps({'name': name, 'inputSchema': contract['inputSchema']}, indent=2, ensure_ascii=False) + '\n')
        hashes[name] = canonical_sha256(contract['inputSchema'])
        schemas[name] = {'path': f'tool-schemas/{name}.json', 'sha256': hashes[name]}

    source = {
        'mcp_commit': git(checkout, 'rev-parse', 'HEAD').strip(),
        'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'source_manifest_sha256': manifest['source_manifest_sha256'],
        'source_state': 'dirty_worktree_candidate' if dirty else 'clean_commit',
        'dirty_contracts': dirty,
    }
    lock = {**source, 'native_tools': native, 'public_excluded': public_excluded,
            'implemented_tools': implemented, 'input_schema_sha256': hashes}
    snapshot = {'snapshot_date': SNAPSHOT_DATE, 'scope': SCOPE, 'source': source,
                'native_tools': native, 'public_excluded': public_excluded,
                'implemented_tools': implemented, 'input_schemas': schemas}
    (root / 'tool-contract-lock.json').write_text(json.dumps(lock, indent=2, ensure_ascii=False) + '\n')
    (root / 'references/implemented-tools.snapshot.json').write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'mcp_commit': source['mcp_commit'], 'tools': len(implemented), 'native': native,
                      'public_excluded': public_excluded, 'source_state': source['source_state']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mcp-root', required=True, help='Pinned MCP checkout')
    sync(parser.parse_args().mcp_root)


if __name__ == '__main__':
    main()
