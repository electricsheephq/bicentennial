CREATE TABLE meta (
    generator_version TEXT NOT NULL, genre TEXT NOT NULL, seed TEXT NOT NULL,
    scale INTEGER NOT NULL CHECK(scale > 0)
) STRICT;
CREATE TRIGGER meta_singleton BEFORE INSERT ON meta WHEN EXISTS(SELECT 1 FROM meta)
BEGIN SELECT RAISE(ABORT, 'meta already exists'); END;
CREATE TABLE entity (
    id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL, canonical_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL CHECK(canonical_json(aliases_json, 'strings')),
    created_t INTEGER NOT NULL, retired_t INTEGER CHECK(retired_t >= created_t)
) STRICT;
CREATE TABLE event (
    id TEXT PRIMARY KEY NOT NULL, t_sim INTEGER NOT NULL, kind TEXT NOT NULL,
    channel TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES entity(id),
    audience_json TEXT NOT NULL CHECK(canonical_json(audience_json, 'strings')),
    visibility TEXT NOT NULL, salience INTEGER NOT NULL CHECK(salience BETWEEN 0 AND 1000),
    payload_json TEXT NOT NULL CHECK(canonical_json(payload_json, 'object'))
) STRICT;
CREATE TABLE attr (
    entity_id TEXT NOT NULL REFERENCES entity(id), key TEXT NOT NULL,
    value TEXT NOT NULL CHECK(canonical_json(value, 'any')), valid_from_t INTEGER NOT NULL,
    valid_to_t INTEGER CHECK(valid_to_t > valid_from_t), recorded_t INTEGER NOT NULL,
    source_event_id TEXT NOT NULL REFERENCES event(id), PRIMARY KEY(entity_id, key, valid_from_t)
) STRICT;
CREATE TRIGGER attr_history BEFORE INSERT ON attr BEGIN
    SELECT RAISE(ABORT, 'overlapping validity') WHERE EXISTS (
        SELECT 1 FROM attr WHERE entity_id = NEW.entity_id AND key = NEW.key
        AND (NEW.valid_to_t IS NULL OR valid_from_t < NEW.valid_to_t)
        AND (valid_to_t IS NULL OR NEW.valid_from_t < valid_to_t));
    SELECT RAISE(ABORT, 'recorded before source event') WHERE NEW.recorded_t <
        (SELECT t_sim FROM event WHERE id = NEW.source_event_id);
END;
CREATE TABLE fact (
    id TEXT PRIMARY KEY NOT NULL, subject_id TEXT NOT NULL REFERENCES entity(id),
    predicate TEXT NOT NULL, object TEXT NOT NULL CHECK(canonical_json(object, 'any')),
    polarity TEXT NOT NULL CHECK(polarity IN ('affirm','negate')),
    modality TEXT NOT NULL CHECK(modality IN ('stated','observed','inferred_allowed','retracted','planted')),
    strength INTEGER NOT NULL CHECK(strength BETWEEN 0 AND 1000),
    speech_act TEXT NOT NULL CHECK(speech_act GLOB '[a-z]*' AND speech_act NOT GLOB '*[^a-z_]*')
) STRICT;
CREATE TABLE link (
    event_id TEXT NOT NULL REFERENCES event(id), fact_id TEXT NOT NULL REFERENCES fact(id),
    role TEXT NOT NULL CHECK(role IN ('assert','retract','mention')), PRIMARY KEY(event_id, fact_id, role)
) STRICT;
CREATE TABLE lineage (
    artifact_id TEXT NOT NULL, artifact_kind TEXT NOT NULL,
    source_fact_id TEXT NOT NULL REFERENCES fact(id), PRIMARY KEY(artifact_id, artifact_kind, source_fact_id)
) STRICT;
CREATE TABLE session (
    idx INTEGER PRIMARY KEY, t_start INTEGER NOT NULL, t_end INTEGER NOT NULL CHECK(t_end > t_start),
    kind TEXT NOT NULL
) STRICT;
CREATE TABLE commitment (
    fact_id TEXT PRIMARY KEY NOT NULL REFERENCES fact(id), trigger_kind TEXT NOT NULL,
    window_open_t INTEGER NOT NULL, window_close_t INTEGER NOT NULL CHECK(window_open_t < window_close_t),
    lures_json TEXT NOT NULL CHECK(canonical_json(lures_json, 'array'))
) STRICT;
CREATE TABLE plant (
    fact_id TEXT NOT NULL REFERENCES fact(id), carrier_event_id TEXT NOT NULL REFERENCES event(id),
    kind TEXT NOT NULL, PRIMARY KEY(fact_id, carrier_event_id, kind)
) STRICT;
CREATE TABLE forget_request (
    event_id TEXT PRIMARY KEY NOT NULL REFERENCES event(id),
    covered_fact_ids_json TEXT NOT NULL CHECK(canonical_json(covered_fact_ids_json, 'strings'))
) STRICT;
CREATE TRIGGER forget_references BEFORE INSERT ON forget_request BEGIN
    SELECT RAISE(ABORT, 'unknown covered fact') WHERE EXISTS (
        SELECT 1 FROM json_each(NEW.covered_fact_ids_json) WHERE value NOT IN (SELECT id FROM fact));
END;
CREATE TABLE locked_token (
    token_id TEXT PRIMARY KEY NOT NULL, fact_id TEXT NOT NULL REFERENCES fact(id),
    kind TEXT NOT NULL CHECK(kind IN ('number','name','date','code')),
    value TEXT NOT NULL CHECK(length(value) >= 4)
) STRICT;
CREATE TABLE fact_surface (
    fact_id TEXT NOT NULL REFERENCES fact(id),
    surface TEXT NOT NULL CHECK(surface IN ('mail','notes','repo','tracker','calendar')),
    from_t INTEGER NOT NULL, PRIMARY KEY(fact_id, surface, from_t)
) STRICT;
