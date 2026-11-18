import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from delivery.analysis_store import ArtifactStore, PublicationConflict
from delivery.database import ArchiveDatabase
from exchange.export import export_report
from exchange.import_check import PackageVerificationError, accept_package, verify_package
from network.revisions import RevisionRepository
from quality.reports import ReportService
from study.cohorts import StudyService
from topology.inclusions import AnalysisService


EXAMPLES = {
    "a": (False, "morning", "morning", "morning"),
    "followup": (False, "morning", "morning", "followup"),
    "b": (True, "morning", "morning", "morning"),
    "study_conflict": (True, "morning", "other-analysis", "study-conflict"),
    "analysis_conflict": (True, "other-study", "morning", "analysis-conflict"),
    "report_conflict": (True, "other-study", "other-analysis", "morning"),
}


def publish_example(database, name):
    filled, study_request, analysis_request, report_request = EXAMPLES[name]
    ref = RevisionRepository(database).save_network(
        "ridge", 1, [1, 2, 3], [(1, 2), (2, 3), (1, 3)],
        [(1, 2, 3)] if filled else [],
    )
    studies = StudyService(database)
    study = studies.freeze_study(study_request, [(900, ref)])
    store = ArtifactStore(database)
    analysis = AnalysisService(studies, store).analyze_study(study.study_id, analysis_request)
    report = ReportService(store).create_report(analysis.artifact_id, report_request)
    return store, report


def write_fixtures(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    paths = {name: root / f"{name}.zip" for name in EXAMPLES}
    with ArchiveDatabase.open(":memory:") as database:
        for name in ("a", "followup"):
            store, report = publish_example(database, name)
            export_report(store, report.artifact_id, paths[name])
    for name in ("b", "study_conflict", "analysis_conflict", "report_conflict"):
        with ArchiveDatabase.open(":memory:") as database:
            store, report = publish_example(database, name)
            export_report(store, report.artifact_id, paths[name])
    paths["damaged"] = root / "damaged.zip"
    with ZipFile(paths["a"]) as original, ZipFile(paths["damaged"], "w") as damaged:
        for member in original.namelist():
            body = original.read(member)
            damaged.writestr(member, body + b"\n" if member == "study.json" else body)
    return paths


def verify_fixtures(paths):
    summaries = {}
    for name, (filled, *requests) in EXAMPLES.items():
        verified = verify_package(paths[name])
        intervals = [[item.start, item.end, item.multiplicity] for item in verified.report.intervals]
        expected = [] if filled else [[0, 0, 1]]
        if intervals != expected:
            raise AssertionError(f"{name}: {intervals!r} != {expected!r}")
        with ZipFile(paths[name]) as package:
            analysis = json.loads(package.read("analysis.json"))
            report = json.loads(package.read("report.json"))
        actual_requests = [verified.study.request_id, analysis["request_id"], report["request_id"]]
        if actual_requests != requests:
            raise AssertionError(f"{name}: unexpected source requests {actual_requests!r}")
        summaries[name] = {
            "requests": actual_requests,
            "ids": [verified.study.study_id, analysis["id"], verified.report_id],
            "intervals": intervals,
        }
    a, b, followup = (summaries[name]["ids"] for name in ("a", "b", "followup"))
    if any(left == right for left, right in zip(a, b)) or a[:2] != followup[:2] or a[2] == followup[2]:
        raise AssertionError("fixture parent identities do not match the scenario")
    try:
        verify_package(paths["damaged"])
    except PackageVerificationError as error:
        if "digest mismatch for study.json" not in str(error):
            raise
    else:
        raise AssertionError("damaged package passed V1 verification")
    return summaries


def acceptance_scenario(directory):
    """Accept fixtures, reject conflicts, reopen and reissue from the frozen analysis."""
    root = Path(directory)
    paths = write_fixtures(root / "packages")
    archive = root / "receiver.sqlite"
    with ArchiveDatabase.open(archive) as database:
        store = ArtifactStore(database)
        a = accept_package(store, "A", paths["a"])
        b = accept_package(store, "B", paths["b"])
        followup = accept_package(store, "A", paths["followup"])
        if not (a.report_request_id == b.report_request_id == "morning" and a.analysis_id == followup.analysis_id):
            raise AssertionError("same-name sources or shared parents were not kept apart")
        if a.analysis_id == b.analysis_id:
            raise AssertionError("independent sources collapsed onto one analysis")
        rejected = {}
        for name in ("study_conflict", "analysis_conflict", "report_conflict"):
            try:
                accept_package(store, "A", paths[name])
            except PublicationConflict as error:
                rejected[name] = str(error)
            else:
                raise AssertionError(f"{name} was accepted into source A")
        if accept_package(store, "A", paths["a"]) != a:
            raise AssertionError("redelivering the same report did not return the original receipt")
        try:
            accept_package(store, "A", paths["damaged"])
        except PackageVerificationError as error:
            rejected["damaged"] = str(error)
        else:
            raise AssertionError("damaged package was accepted")
    with ArchiveDatabase.open(archive) as database:
        store = ArtifactStore(database)
        if store.find_acceptance("A", "morning") != a or store.find_acceptance("A", "followup") != followup:
            raise AssertionError("source receipts did not survive reopening")
        if StudyService(database).get_study(a.study_id).request_id != "morning":
            raise AssertionError("accepted study did not reopen under its original identity")
        original_analysis = store.read_artifact(a.analysis_id)
        local = ReportService(store).create_report(a.analysis_id, "morning")
        if local.payload["intervals"] != [[0, 0, 1]] or local.parent_id != original_analysis.artifact_id:
            raise AssertionError("local report did not consume the accepted analysis")
        if store.find_receipt("report", "morning") != local or store.find_acceptance("A", "morning") != a:
            raise AssertionError("local and source request spaces were not kept apart")
        original_zip = export_report(store, a.report_id, root / "original.zip")
        local_zip = export_report(store, local.artifact_id, root / "local.zip")
        followup_zip = export_report(store, followup.report_id, root / "followup.zip")
    checked_original = verify_package(original_zip)
    checked_local = verify_package(local_zip)
    checked_followup = verify_package(followup_zip)
    if checked_original.report_id != a.report_id or checked_local.analysis.study_id != a.study_id:
        raise AssertionError("re-exported packages did not verify against the accepted chain")
    if checked_followup.report_id != followup.report_id or checked_followup.analysis.study_id != a.study_id:
        raise AssertionError("follow-up delivery did not re-export along the shared parents")
    return {
        "accepted": {"A/morning": a.record(), "B/morning": b.record(), "A/followup": followup.record()},
        "shared": {"study": a.study_id, "analysis": a.analysis_id},
        "rejected": rejected,
        "local_report": {"report_id": local.artifact_id, "intervals": local.payload["intervals"]},
        "reverified": {"original": checked_original.report_id, "local": checked_local.report_id,
                       "followup": checked_followup.report_id},
    }


def main():
    with TemporaryDirectory(prefix="chengchuan-intake-") as directory:
        summaries = verify_fixtures(write_fixtures(directory))
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
        print(json.dumps(acceptance_scenario(Path(directory) / "receiver"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
