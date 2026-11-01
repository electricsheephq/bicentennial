"""T2-lite answer contract acceptance."""

import copy

import pytest

from bicentennial.director.compiler import answer_contract as ac

SPAN = (
    '\n\nReply with one JSON object and nothing else, in this form:\n'
    '{"type": "span", "value": "<the words, exactly as they were said>", '
    '"confidence_milli": <a whole number from 0 to 1000>, '
    '"citation": {"quote": "<the exact words where it was said>", "context_offset": 0}}\n'
    'If you do not know, reply {"type": "unknown", "value": null, "confidence_milli": 0, "citation": null}.\n'
    'A confidence of 500 or more asserts the answer; below 500 it is a guess. '
    'Copy the quote exactly from what you saw, or give "citation": null.'
)
FORMS = {
    "span": '"<the words, exactly as they were said>"',
    "premise_correction": '"<the correction, in the words it was said>"',
    "citation": '"<the words, exactly as they were said>"',
    "entity": '"<the name, exactly as it was written>"',
    "number": "<the number, in digits>",
    "boolean": "<true or false>",
    "datetime": "<the time, in Unix seconds, UTC>",
    "set": "[<each item, exactly as it was written>]",
    "ordered_list": "[<each item in order, exactly as it was written>]",
}


def test_contract_object_and_fixed_hash():
    assert ac.CONTRACT == dict(
        version="t2lite-answer-contract-v1", unsupported=["env_state"], value_forms=FORMS,
        template=SPAN.replace('"span"', '"<<TYPE>>"', 1).replace(FORMS["span"], "<<VALUE>>", 1))
    assert ac.contract_hash() == ac.CONTRACT_SHA256 == (
        "bafd5869f968a10d691a9d7f0bfd765d88a2242d0c55cb89467b799a3bfe26af")


@pytest.mark.parametrize("field", ["template", *FORMS])
def test_every_single_character_drift_changes_hash(field, monkeypatch):
    original = copy.deepcopy(ac.CONTRACT)
    contract = copy.deepcopy(original)
    monkeypatch.setattr(ac, "CONTRACT", contract)
    parent = contract if field == "template" else contract["value_forms"]
    text = parent[field]
    for index, character in enumerate(text):
        changed = "X" if character != "X" else "Y"
        parent[field] = text[:index] + changed + text[index + 1:]
        assert ac.contract_hash() != ac.CONTRACT_SHA256, (field, index)
    assert original != contract


@pytest.mark.parametrize("kind", FORMS)
def test_every_supported_type_renders_literally(kind):
    options = [{"type": kind}, {"type": "unknown"}, {"type": kind}]
    before = copy.deepcopy(options)
    assert ac.answer_type(options) == kind
    assert ac.render(options) == ac.CONTRACT["template"].replace(
        "<<TYPE>>", kind).replace("<<VALUE>>", FORMS[kind])
    assert options == before


@pytest.mark.parametrize("kinds", [("span",), ("span", "unknown"), ("unknown", "span")])
def test_exact_span_and_unknown_in_either_order(kinds):
    options = [{"type": kind} for kind in kinds]
    assert ac.answer_type(options) == "span"
    assert ac.render(options) == SPAN


@pytest.mark.parametrize("kinds,reason", [
    ([], "missing"), (["unknown"], "missing"), (["unknown", "unknown"], "missing"),
    (["span", "number"], "mixed"), (["number", "span"], "mixed"),
    (["env_state"], "unsupported:env_state"), (["future_type"], "unsupported:future_type"),
])
@pytest.mark.parametrize("function", [ac.answer_type, ac.render])
def test_type_refusals(kinds, reason, function):
    with pytest.raises(ValueError) as error:
        function([{"type": kind} for kind in kinds])
    assert str(error.value) == "answer_contract_type:" + reason


@pytest.mark.parametrize("function", [ac.answer_type, ac.render])
def test_missing_value_form_is_refused(function, monkeypatch):
    monkeypatch.delitem(ac.CONTRACT["value_forms"], "span")
    with pytest.raises(ValueError, match="^answer_contract_type:unsupported:span$"):
        function([{"type": "span"}])
