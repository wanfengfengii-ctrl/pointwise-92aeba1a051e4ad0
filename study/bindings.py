from dataclasses import dataclass
from math import isfinite

from network.canonical import canonical_json, content_digest, reference_data
from network.model import NetworkRevision, RevisionRef, valid_text


MAX_SAMPLES = 16


@dataclass(frozen=True)
class SampleBinding:
    time: int | float | str
    revision: NetworkRevision


def _time_family(value):
    if type(value) is int or (type(value) is float and isfinite(value)):
        return 'number'
    if valid_text(value):
        return 'text'
    raise ValueError('sample time must be a finite number or nonempty text')


def validate_sample_order(times):
    times = tuple(times)
    if not 1 <= len(times) <= MAX_SAMPLES:
        raise ValueError('expected between 1 and 16 samples')
    family = _time_family(times[0])
    for previous, current in zip(times, times[1:]):
        if _time_family(current) != family or not previous < current:
            raise ValueError('sample times must be comparable and strictly increasing')


def sample_request(samples):
    try:
        pairs = tuple((time, ref) for time, ref in samples)
    except (TypeError, ValueError) as error:
        raise ValueError('expected pairs of sample time and revision reference') from error
    validate_sample_order(time for time, _ in pairs)
    if any(not isinstance(ref, RevisionRef) for _, ref in pairs):
        raise ValueError('each sample requires an exact revision reference')
    return pairs


def bind_revisions(repository, samples):
    return tuple(SampleBinding(time, repository.get_revision(ref))
                 for time, ref in sample_request(samples))


def binding_fingerprint(pairs):
    return content_digest(canonical_json([[time, reference_data(ref)] for time, ref in pairs]))
