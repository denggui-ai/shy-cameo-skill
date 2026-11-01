from coshoot.schema_lite import validate

SCHEMA = {
    "type": "object",
    "required": ["id", "tags"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z]+$"},
        "kind": {"enum": ["a", "b"]},
        "v": {"const": "1"},
        "n": {"type": "integer"},
        "tags": {"type": "array", "maxItems": 2, "items": {"$ref": "#/$defs/tag"}},
    },
    "$defs": {"tag": {"type": "string", "minLength": 1}},
}


def test_valid_instance_has_no_errors():
    assert validate({"id": "abc", "tags": ["x"], "kind": "a", "v": "1", "n": 3}, SCHEMA) == []


def test_missing_required_and_unexpected_property():
    errors = validate({"tags": [], "extra": 1}, SCHEMA)
    assert "$: missing required 'id'" in errors
    assert "$: unexpected property 'extra'" in errors


def test_pattern_enum_const_errors():
    errors = validate({"id": "ABC", "tags": [], "kind": "z", "v": "2"}, SCHEMA)
    assert any(e.startswith("$.id: does not match") for e in errors)
    assert any(e.startswith("$.kind: must be one of") for e in errors)
    assert any(e.startswith("$.v: must equal") for e in errors)


def test_array_limits_and_ref_items():
    errors = validate({"id": "a", "tags": ["x", "", "z"]}, SCHEMA)
    assert "$.tags: more than 2 items" in errors
    assert "$.tags[1]: shorter than 1" in errors


def test_bool_is_not_integer():
    assert validate({"id": "a", "tags": [], "n": True}, SCHEMA) == ["$.n: expected type integer"]
