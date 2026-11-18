from quality.decomposition import decompose_intervals, reconstruct_dimensions
from topology.inclusions import AnalysisError, validate_analysis_relations


class InvalidAnalysis(ValueError):
    pass


def validate_lifetime_reconstruction(intervals, dimensions):
    if reconstruct_dimensions(intervals, len(dimensions)) != tuple(dimensions):
        raise InvalidAnalysis('intervals do not reconstruct the frozen position dimensions')


def lifetimes_from_analysis(payload):
    try:
        analysis = validate_analysis_relations(payload)
        intervals = decompose_intervals(analysis.dimensions, analysis.maps)
    except (AnalysisError, ValueError) as error:
        raise InvalidAnalysis(str(error)) from error
    validate_lifetime_reconstruction(intervals, analysis.dimensions)
    return intervals
