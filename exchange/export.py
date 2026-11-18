import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile, ZipInfo

from delivery.analysis_store import ArtifactIntegrityError, UnknownArtifact
from exchange.manifests import MANIFEST, build_manifest, canonical_member_bytes, encode_manifest


class ExportError(ValueError):
    pass


def export_report(store, report_id, path):
    temporary = None
    try:
        destination = Path(path).absolute()
        if destination.resolve() in store.database.archive_paths():
            raise ExportError('output conflicts with the source archive')
        report, analysis, study = store.read_parent_chain(report_id)
        members = {
            'report.json': canonical_member_bytes(report.record()),
            'analysis.json': canonical_member_bytes(analysis.record()),
            'study.json': canonical_member_bytes(study),
        }
        manifest = build_manifest(members, {'report.json': report.artifact_id, 'analysis.json': analysis.artifact_id,
                                            'study.json': analysis.parent_id})
        members[MANIFEST] = encode_manifest(manifest)
        with NamedTemporaryFile(dir=destination.parent, prefix='.quality-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            with ZipFile(stream, 'w') as package:
                for name, body in sorted(members.items()):
                    package.writestr(ZipInfo(name), body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return destination
    except (OSError, TypeError, ValueError, UnknownArtifact, ArtifactIntegrityError) as error:
        raise ExportError(str(error)) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
