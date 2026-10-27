"""Deterministic JUnit cases keyed by probe or invariant identity."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from bicentennial.canon import canon
from bicentennial.contracts.bundle import NONRESULTS


@dataclass(frozen=True)
class Case:
    name: str
    classname: str
    outcome: str
    type: str | None = None
    message: str | None = None

    def __post_init__(self):
        if self.outcome not in ("passed", "failure", "error", "skipped") or (
                self.outcome == "passed" and (self.type is not None or self.message is not None)):
            raise ValueError("invalid JUnit outcome or passed-case detail")


def item_cases(items) -> list[Case]:
    cases = []
    for i in items:
        name, classname = i["item_id"], f"{i['stage']}.{i['track']}.{i['cell_id']}"
        failure, score = i["failure_class"], i["score_milli"]
        if failure in NONRESULTS:
            case = Case(name, classname, "skipped", failure, failure)
        elif failure == "SYSTEM_FAILURE":
            case = Case(name, classname, "error", failure, "score_milli=0 worst_case_milli=-1000")
        elif score == 1000:
            case = Case(name, classname, "passed")
        else:
            message = f"score_milli={score}"
            if i["tuesday_class"]:
                message += f" tuesday_class={i['tuesday_class']}"
            if i["benign_extra"]:
                message += " benign_extra"
            case = Case(name, classname, "failure", i["base_verdict"] or "QA", message)
        cases.append(case)
    return cases


def item_suite(card, arm, properties=()):
    if arm not in ("system", "wiped", "no_memory"):
        raise ValueError("unknown Ring 0 arm")
    return f"ring0.{card['tier']}.{card['system']}.{arm}", properties, item_cases(card["items"])


def _properties(pairs):
    rows = [(name, v if isinstance(v, str) else canon(v).decode()) for name, v in pairs]
    if len(rows) != len({name for name, _ in rows}):
        raise ValueError("duplicate JUnit property name")
    return sorted(rows)


def run_properties(reduced, extra=()):
    rows = [(f"accuracy.{k}", reduced["accuracy"][k]) for k in
            ("figure_milli", "incomplete", "label")]
    rows.append(("coverage.incomplete", reduced["coverage"]["incomplete"]))
    rows.extend((f"single_item.{r['stage']}.{r['track']}", r["score_milli"])
                for r in reduced["single_item"])
    return _properties([*rows, *extra])


def junit_cases_from_invariants(verdicts):
    """Read canonical Verdict.to_obj() rows, as stored in invariants.json."""
    outcomes = dict(PASS="passed", FAIL="failure", INFRA_FAILURE="error",
                    INCONCLUSIVE="skipped", NOT_EXERCISED="skipped")
    return [Case(v["invariant"], "ring0.invariants", outcomes[v["status"]],
                 None if v["status"] == "PASS" else v["status"],
                 None if v["status"] == "PASS" else v["status"]) for v in verdicts]


def _xml_text(s):
    if not isinstance(s, str) or any(not (c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF
            or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in s):
        raise ValueError("invalid XML 1.0 string")
    return s


def junit_xml(suites) -> bytes:
    root, names = ET.Element("testsuites", name="bicentennial"), set()
    totals = dict(tests=0, failures=0, errors=0)
    for name, properties, cases in suites:
        if name in names:
            raise ValueError("duplicate JUnit suite name")
        names.add(name)
        cases = sorted(cases, key=lambda c: c.name)
        if len(cases) != len({c.name for c in cases}):
            raise ValueError("duplicate JUnit case name")
        counts = dict(tests=len(cases), failures=sum(c.outcome == "failure" for c in cases),
                      errors=sum(c.outcome == "error" for c in cases),
                      skipped=sum(c.outcome == "skipped" for c in cases))
        suite = ET.SubElement(root, "testsuite", name=_xml_text(name),
                              **{k: str(v) for k, v in counts.items()})
        for k in totals:
            totals[k] += counts[k]
        properties = _properties(properties)
        if properties:
            parent = ET.SubElement(suite, "properties")
            for key, value in properties:
                ET.SubElement(parent, "property", name=_xml_text(key), value=_xml_text(value))
        for case in cases:
            node = ET.SubElement(suite, "testcase", name=_xml_text(case.name),
                                 classname=_xml_text(case.classname))
            if case.outcome != "passed":
                ET.SubElement(node, case.outcome, type=_xml_text(case.type or ""),
                              message=_xml_text(case.message or ""))
    root.attrib.update({k: str(v) for k, v in totals.items()})
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n"
