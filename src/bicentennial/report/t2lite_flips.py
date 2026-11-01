"""Pure developer comparisons; never a gate, scorer or publication caller."""

from dataclasses import asdict, dataclass
from fractions import Fraction

from bicentennial.canon import milli
from bicentennial.report.t2lite_card import validate_t2lite_card

BASELINE_FIELDS = (
    "system", "pack_hash", "seed_hash", "model", "effort", "pins.harness_hash",
    "answer_contract_sha256", "pins.benchmark_commit", "pins.generator_commit",
    "pins.director_commit", "pins.scorer_commit", "profile",
)
# The card records the registered system name, not a local checkout or registry object.
# report/ may not import systems/, so a test keeps both lists equal to the registry.
PLUGIN_SYSTEMS = frozenset({"holographic", "mem0-oss", "omega"})
MODEL_CACHE_SYSTEMS = frozenset({"omega"})  # its worker settings name {model_cache}
NO_BAND = "no A/A′ band"
# The fields both a card row and an outcome record carry that decide a row's flip or exclusion.
VOUCHED_FIELDS = ("score_milli", "failure_class", "base_verdict", "stage")


class BaselineRefused(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _validate(card, side):
    try:
        validate_t2lite_card(card)
    except (ValueError, TypeError, KeyError) as error:
        raise BaselineRefused(f"invalid_card:{side}") from error


def _compare(card, baseline_card, prefix):
    for field in BASELINE_FIELDS:
        value, baseline = card, baseline_card
        for part in field.split("."):
            value, baseline = value[part], baseline[part]
        if value != baseline:
            raise BaselineRefused(prefix + field)


def check_baseline_t2lite(current_card, baseline_card) -> None:
    """Validate both cards before comparing the frozen comparability fields."""
    _validate(current_card, "current")
    _validate(baseline_card, "baseline")
    _compare(current_card, baseline_card, "")


@dataclass(frozen=True)
class ItemOutcome:
    """Joined item/outcome/shadow metadata; envelope is 'parsed' or 'missing'.

    from_dict projects plain joined records, ignoring unrelated runner fields.
    An envelope object becomes 'parsed', and None becomes 'missing'; its value
    and citation agreement are the caller's L4 diagnostics, never recomputed here.
    """

    item_id: str
    score_milli: int | None
    failure_class: str | None
    base_verdict: str | None
    life: str
    branch: str
    probe_point: int
    probe_session: int
    cell_id: str
    track: str
    stage: str
    template_ref: str
    genre: str
    twin_bundle: str | None
    twin_flip: bool | None
    in_context: bool | None
    stage_attribution: str | None
    envelope: str
    value_match: bool | None
    citation_match: bool | None
    crosses_cold_restart: bool
    swap_position: str

    @classmethod
    def from_dict(cls, record):
        values = {key: record[key] for key in cls.__dataclass_fields__}
        envelope = values["envelope"]
        if envelope is None:
            values["envelope"] = "missing"
        elif isinstance(envelope, dict):
            values["envelope"] = "parsed"
        elif envelope not in ("parsed", "missing"):
            raise ValueError("envelope must be parsed or missing")
        return cls(**values)


def _outcomes(outcomes):
    records = {}
    for item_id, value in outcomes.items():
        record = (value if isinstance(value, ItemOutcome)
                  else ItemOutcome.from_dict(dict(value, item_id=value.get("item_id", item_id))))
        if record.item_id != item_id:
            raise ValueError("outcome key differs from item_id")
        records[item_id] = record
    return records


def _exclusion(*records):
    for reason in ("INFRA", "INFRA_FAILURE", "BLOCKED"):
        if any(reason in (r.failure_class, r.base_verdict) for r in records):
            return reason
    if any(r.stage == "act" and r.genre == "G2" for r in records):
        return "not_scored_live"
    return None


def _scored(*records):
    return _exclusion(*records) is None and all(type(r.score_milli) is int for r in records)


def _differs(a, b):
    return (a.score_milli, a.failure_class) != (b.score_milli, b.failure_class)


def flip_list(baseline_outcomes, current_outcomes, *, aa_prime=None, rerun=None):
    """Return rows, exclusions, exact q0, q0_milli, labels and counts.

    Runs must cover identical item ids; missing results must be explicit records.
    aa_prime contains only outcomes; flip_report checks its card against the baseline.
    q0 uses items scored in both A and A′, independently of the current run.
    An empty scored A/A′ intersection has q0=None. Row instability compares the
    A/A′ outcomes of every item measured in both; it is None where either is
    INFRA, BLOCKED or a G2 act, and without A′. counts.unstable is the scored
    numerator used by q0. rerun is a pure ItemOutcome-to-string callable.
    """
    baseline, current = _outcomes(baseline_outcomes), _outcomes(current_outcomes)
    prime = None if aa_prime is None else _outcomes(aa_prime)
    if baseline.keys() != current.keys() or prime is not None and baseline.keys() != prime.keys():
        raise ValueError("runs must have identical item ids")
    unstable = {} if prime is None else {
        iid: None if _exclusion(a, prime[iid]) else _differs(a, prime[iid])
        for iid, a in baseline.items()}
    scored_band = [] if prime is None else [
        unstable[iid] for iid, a in baseline.items() if _scored(a, prime[iid])]
    q0 = Fraction(sum(scored_band), len(scored_band)) if scored_band else None
    rows, excluded = [], []
    for iid in sorted(baseline, key=lambda i: (
            baseline[i].life, baseline[i].branch, baseline[i].probe_point, i)):
        a, b = baseline[iid], current[iid]
        reason = _exclusion(a, b)
        pair = dict(item_id=iid, baseline=asdict(a), current=asdict(b))
        if reason is not None:
            excluded.append(dict(pair, reason=reason))
        elif _differs(a, b):
            rows.append(dict(pair, unstable=unstable.get(iid),
                             rerun=None if rerun is None else rerun(a)))
    return dict(rows=rows, excluded=excluded, q0=q0,
                q0_milli=None if q0 is None else milli(q0),
                labels=[NO_BAND] if prime is None else [],
                counts=dict(items=len(baseline), flips=len(rows), excluded=len(excluded),
                            scored=sum(_scored(a, current[i]) for i, a in baseline.items()),
                            aa_prime_scored=len(scored_band), unstable=sum(scored_band)))


def _token(value):
    if (type(value) is not str or not value or value.startswith("-")
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                   for c in value)):
        raise ValueError("rerun requires a simple identifier")
    return value


def rerun_command(card, item):
    """Format a publishable command; paths are always literal placeholders."""
    item = item if isinstance(item, ItemOutcome) else ItemOutcome.from_dict(item)
    system, life, branch = (_token(v) for v in (card["system"], item.life, item.branch))
    digest = card["pack_hash"]
    if (type(digest) is not str or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("invalid pack_hash")
    if type(item.probe_point) is not int or item.probe_point < 1:
        raise ValueError("invalid probe_point")
    plugin = " --plugin-source <plugin checkout>" if system in PLUGIN_SYSTEMS else ""
    if system in MODEL_CACHE_SYSTEMS:
        plugin += " --model-cache <model cache>"
    return (f"PYTHONHASHSEED=0 bicentennial t2lite --system {system} --packs <packs> "
            f"--pack-hash {digest} --hermes <hermes checkout>{plugin} "
            f"--login-home <login home> --max-sends <max sends> "
            f"--only {life}:{branch}:{item.probe_point} --repeat 3 --out <new dir>")


def _vouch(card, outcomes, side):
    """A card vouches only for its own run: the same ids and the same decision fields."""
    items = {item["item_id"]: item for item in card["items"]}
    if items.keys() != outcomes.keys() or any(
            (type(getattr(record, key)), getattr(record, key))
            != (type(items[iid][key]), items[iid][key])
            for iid, record in outcomes.items() for key in VOUCHED_FIELDS):
        raise BaselineRefused(f"items:{side}")


def flip_report(current_card, baseline_card, baseline_outcomes, current_outcomes, *,
                aa_prime=None, aa_prime_card=None):
    """Return a fresh JSON object, ready for canon; no files are written.

    A′ outcomes come with their card, which records aa_prime: true and is checked
    against the baseline card like the current one. Each card vouches for its outcomes.
    """
    check_baseline_t2lite(current_card, baseline_card)
    if aa_prime is not None and aa_prime_card is None:
        raise BaselineRefused("aa_prime:no_card")
    if aa_prime_card is not None:
        if aa_prime is None:
            raise BaselineRefused("aa_prime:no_outcomes")
        _validate(aa_prime_card, "aa_prime")
        _compare(aa_prime_card, baseline_card, "aa_prime:")
        if aa_prime_card["aa_prime"] is not True:
            raise BaselineRefused("aa_prime:flag")
    runs = [("current", current_card, current_outcomes), ("baseline", baseline_card, baseline_outcomes)]
    if aa_prime is not None:
        runs.append(("aa_prime", aa_prime_card, aa_prime))
    for side, card, outcomes in runs:
        _vouch(card, _outcomes(outcomes), side)
    result = flip_list(baseline_outcomes, current_outcomes, aa_prime=aa_prime,
                       rerun=lambda item: rerun_command(current_card, item))
    q0 = result.pop("q0")
    q0_milli = result.pop("q0_milli")
    result["q0"] = (None if q0 is None else dict(
        numerator=q0.numerator, denominator=q0.denominator, milli=q0_milli))
    result["labels"] = [current_card["labels"][key] for key in sorted(current_card["labels"])] + result["labels"]
    return result
