import json
from dataclasses import dataclass

from network.canonical import canonical_json, content_digest, valid_digest


MEMBERS = ('analysis.json', 'report.json', 'study.json')
MANIFEST = 'manifest.json'
_PREFIXES = {'analysis.json': 'analysis:', 'report.json': 'report:', 'study.json': 'study:'}


@dataclass(frozen=True)
class PackageManifest:
    members: dict


def canonical_member_bytes(value):
    return canonical_json(value)


def decode_canonical_member(raw):
    value = json.loads(raw)
    if canonical_member_bytes(value) != raw:
        raise ValueError('package member is not canonically encoded')
    return value


def _validate_entries(entries):
    if not isinstance(entries, dict) or set(entries) != set(MEMBERS):
        raise ValueError('invalid manifest member set')
    for name, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {'id', 'sha256'}:
            raise ValueError('invalid manifest member entry')
        identity = entry['id']
        prefix = _PREFIXES[name]
        if not isinstance(identity, str) or not identity.startswith(prefix) or not valid_digest(identity[len(prefix):]):
            raise ValueError('invalid manifest member identity')
        if not valid_digest(entry['sha256']):
            raise ValueError('invalid manifest member digest')


def build_manifest(members, identities):
    if set(members) != set(MEMBERS) or set(identities) != set(MEMBERS):
        raise ValueError('incomplete package member set')
    entries = {name: {'id': identities[name], 'sha256': content_digest(members[name])} for name in MEMBERS}
    _validate_entries(entries)
    return PackageManifest(entries)


def encode_manifest(manifest):
    _validate_entries(manifest.members)
    return canonical_member_bytes({'version': 1, 'members': manifest.members})


def decode_manifest(raw):
    payload = decode_canonical_member(raw)
    if not isinstance(payload, dict) or set(payload) != {'version', 'members'}:
        raise ValueError('invalid package manifest fields')
    if type(payload['version']) is not int or payload['version'] != 1:
        raise ValueError('unsupported package manifest version')
    _validate_entries(payload['members'])
    return PackageManifest(payload['members'])


def verify_member_digests(manifest, members):
    if set(members) != set(MEMBERS):
        raise ValueError('package member set does not match manifest')
    for name in MEMBERS:
        if content_digest(members[name]) != manifest.members[name]['sha256']:
            raise ValueError(f'digest mismatch for {name}')
