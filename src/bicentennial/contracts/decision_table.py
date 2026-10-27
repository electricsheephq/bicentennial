"""Per-template decision tables (PREREG §3, DESIGN §7.1a): data from the template build (C-7)."""

from .run import register_check


def predicate_names(table) -> list[str]:
    """Every predicate the table names, in table order: admissible, disqualifiers, benign."""
    return [*table["admissible"], *(row["predicate"] for row in table["disqualifiers"]),
            *table["benign_extras"]]


def check_decision_table(table):
    names = predicate_names(table)
    if len(names) != len(set(names)):
        raise ValueError("decision_table: a predicate is named more than once")
    if not table["timed"] and any(row["tuesday_class"] is not None for row in table["disqualifiers"]):
        raise ValueError("decision_table: a Tuesday class needs a timed table")
    # A correct rejection (refrain, false premise, never observed) changes no state, so it
    # has no admissible state; an act gold must name at least one.
    if (table["gold"] == "act") != bool(table["admissible"]):
        raise ValueError("decision_table: act gold needs admissible predicates, refrain gold none")


register_check("decision_table", check_decision_table)
