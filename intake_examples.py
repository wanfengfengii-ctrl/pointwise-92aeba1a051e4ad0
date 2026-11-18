import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from delivery.analysis_store import ArtifactStore
from delivery.database import ArchiveDatabase
from exchange.export import export_report
from exchange.import_check import PackageVerificationError, verify_package
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


def main():
    with TemporaryDirectory(prefix="chengchuan-intake-") as directory:
        summaries = verify_fixtures(write_fixtures(directory))
        print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
