from quality.encoding import QualityReport, encode_report
from quality.lifetimes import InvalidAnalysis, lifetimes_from_analysis


class ReportService:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def create_report(self, analysis_id, request_id):
        existing = self.artifacts.find_receipt('report', request_id, analysis_id)
        if existing is not None:
            return existing
        analysis = self.artifacts.read_artifact(analysis_id)
        if analysis.kind != 'analysis' or analysis.payload.get('study_id') != analysis.parent_id:
            raise InvalidAnalysis('expected a frozen analysis with its exact study parent')
        intervals = lifetimes_from_analysis(analysis.payload)
        report = QualityReport(analysis.artifact_id, analysis.payload['positions'], intervals)
        return self.artifacts.publish('report', request_id, analysis.artifact_id, encode_report(report))
