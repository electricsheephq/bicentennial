"""The fixed, system-neutral T2-lite QA instruction (issue #338)."""

from hashlib import sha256

from bicentennial.canon import canon

CONTRACT = {
    "version": "t2lite-answer-contract-v1",
    "template": (
        "\n\nReply with one JSON object and nothing else, in this form:\n"
        '{"type": "<<TYPE>>", "value": <<VALUE>>, "confidence_milli": <a whole number from 0 to 1000>, '
        '"citation": {"quote": "<the exact words where it was said>", "context_offset": 0}}\n'
        'If you do not know, reply {"type": "unknown", "value": null, "confidence_milli": 0, "citation": null}.\n'
        "A confidence of 500 or more asserts the answer; below 500 it is a guess. "
        'Copy the quote exactly from what you saw, or give "citation": null.'
    ),
    "value_forms": {
        "span": '"<the words, exactly as they were said>"',
        "premise_correction": '"<the correction, in the words it was said>"',
        "citation": '"<the words, exactly as they were said>"',
        "entity": '"<the name, exactly as it was written>"',
        "number": "<the number, in digits>",
        "boolean": "<true or false>",
        "datetime": "<the time, in Unix seconds, UTC>",
        "set": "[<each item, exactly as it was written>]",
        "ordered_list": "[<each item in order, exactly as it was written>]",
    },
    "unsupported": ["env_state"],
}
CONTRACT_SHA256 = "bafd5869f968a10d691a9d7f0bfd765d88a2242d0c55cb89467b799a3bfe26af"


def contract_hash() -> str:
    """Hash the complete contract, including its literal text and value forms."""
    return sha256(canon(CONTRACT)).hexdigest()


def answer_type(option_envelopes) -> str:
    """Require one supported type across every non-unknown option envelope."""
    kinds = {envelope["type"] for envelope in option_envelopes if envelope["type"] != "unknown"}
    if not kinds:
        raise ValueError("answer_contract_type:missing")
    if len(kinds) != 1:
        raise ValueError("answer_contract_type:mixed")
    kind = kinds.pop()
    if kind in CONTRACT["unsupported"] or kind not in CONTRACT["value_forms"]:
        raise ValueError(f"answer_contract_type:unsupported:{kind}")
    return kind


def render(option_envelopes) -> str:
    """Substitute literal markers, preserving every JSON brace in the template."""
    kind = answer_type(option_envelopes)
    return CONTRACT["template"].replace("<<TYPE>>", kind).replace(
        "<<VALUE>>", CONTRACT["value_forms"][kind])
