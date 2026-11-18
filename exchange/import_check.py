from dataclasses import dataclass
from zipfile import BadZipFile

from delivery.analysis_store import PublishedArtifact
from exchange.manifests import (MANIFEST, canonical_member_bytes, decode_canonical_member, decode_manifest,
                                verify_member_digests)
from exchange.readers import decode_artifact_payload, read_package_members, resolve_report_sources
from network.model import valid_text
from quality.encoding import QualityReport, decode_report
from quality.lifetimes import validate_lifetime_reconstruction
from study.cohorts import FrozenStudy, decode_frozen_study
from study.timeline import position_sources
from topology.inclusions import FrozenAnalysis, validate_analysis_relations


class PackageVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedPackage:
    report_id: str
    report: QualityReport
    analysis: FrozenAnalysis
    study: FrozenStudy
    sources: tuple[dict, ...]


@dataclass(frozen=True)
class CheckedMembers:
    """The exact records one verification pass confirmed, ready to be accepted."""

    report: PublishedArtifact
    analysis: PublishedArtifact
    study: FrozenStudy
    verified: VerifiedPackage


def validate_parent_chain(manifest, report, analysis, study):
    identities = {'report.json': report.artifact_id, 'analysis.json': analysis.artifact_id,
                  'study.json': study.study_id}
    if any(manifest.members[name]['id'] != identity for name, identity in identities.items()):
        raise ValueError('manifest identity does not match its member')
    if report.kind != 'report' or analysis.kind != 'analysis':
        raise ValueError('incorrect artifact kind in parent chain')
    if report.parent_id != analysis.artifact_id or analysis.parent_id != study.study_id:
        raise ValueError('package parent chain mismatch')
    if report.payload.get('analysis_id') != analysis.artifact_id or analysis.payload.get('study_id') != study.study_id:
        raise ValueError('payload parent identity mismatch')


def validate_relation_structure(study, analysis_payload, report):
    analysis = validate_analysis_relations(analysis_payload)
    expected_sources = canonical_member_bytes(position_sources(study.positions))
    if (canonical_member_bytes(analysis.positions) != expected_sources
            or canonical_member_bytes(report.positions) != expected_sources):
        raise ValueError('report or analysis position sources disagree with frozen study')
    validate_lifetime_reconstruction(report.intervals, analysis.dimensions)
    return analysis


def verify_package(path):
    return _check_package(path).verified


def accept_package(store, source_id, path):
    """Verify one V1 ZIP and store the very members that verification confirmed."""
    if not valid_text(source_id):
        raise ValueError('source identity must be nonempty text')
    checked = _check_package(path)
    return store.accept(source_id, checked.study, checked.analysis, checked.report)


def _check_package(path):
    try:
        members = read_package_members(path)
        manifest = decode_manifest(members.pop(MANIFEST))
        verify_member_digests(manifest, members)
        report_record = decode_artifact_payload(members['report.json'])
        analysis_record = decode_artifact_payload(members['analysis.json'])
        study = decode_frozen_study(manifest.members['study.json']['id'], decode_canonical_member(members['study.json']))
        validate_parent_chain(manifest, report_record, analysis_record, study)
        report = decode_report(report_record.payload)
        analysis = validate_relation_structure(study, analysis_record.payload, report)
        verified = VerifiedPackage(report_record.artifact_id, report, analysis, study, resolve_report_sources(report))
        return CheckedMembers(report_record, analysis_record, study, verified)
    except (OSError, BadZipFile, ValueError, TypeError, NotImplementedError, RuntimeError) as error:
        raise PackageVerificationError(str(error)) from error
