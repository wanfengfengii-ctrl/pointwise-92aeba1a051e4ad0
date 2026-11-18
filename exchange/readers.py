from zipfile import ZipFile

from delivery.analysis_store import decode_artifact_record
from exchange.manifests import MANIFEST, MEMBERS, decode_canonical_member
from study.timeline import validate_position_sources


def read_package_members(path):
    with ZipFile(path, 'r') as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate package member')
        if set(names) != {MANIFEST, *MEMBERS}:
            raise ValueError('package members are missing or unexpected')
        return {name: package.read(name) for name in names}


def decode_artifact_payload(raw):
    return decode_artifact_record(decode_canonical_member(raw))


def resolve_report_sources(report):
    validate_position_sources(report.positions)
    return tuple({'index': item['index'], 'kind': item['kind'], 'time': item['time'],
                  'refs': [dict(ref) for ref in item['refs']]} for item in report.positions)
