"""Structural JSON Schema tests for ``schemas/atmlib-score-v1.schema.json``.

The repository does not depend on the third-party ``jsonschema`` package, so
this module carries a small, self-contained structural validator covering the
JSON Schema keywords the public v1 schema actually uses (``type``, ``const``,
``required``, ``properties``, ``additionalProperties``, ``propertyNames``,
``items``/``minItems``/``maxItems``, ``minimum``/``maximum``, ``pattern``,
``maxLength``, ``maxProperties``/``minProperties``, ``oneOf`` and ``$ref``).

These tests guard the public contract fix for ``ATMlib2FX-9jo``: the root is
``additionalProperties: false`` but accepts an optional boolean ``loop`` field
(omission equivalent to false). Semantic loop lowering and validation remain the
CLI's responsibility; only the structural shape is asserted here.
"""

from __future__ import annotations

import copy
import glob
import json
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

SCHEMA_PATH = os.path.join(REPO_ROOT, "schemas", "atmlib-score-v1.schema.json")
DEMO_GLOB = os.path.join(
    REPO_ROOT, "examples", "music_authoring", "**", "song.json"
)
DEMO_LOOP_TRUE = os.path.join(
    REPO_ROOT, "examples", "music_authoring", "basic", "song.json"
)
FIXTURE_SONG = os.path.join(_HERE, "fixtures", "basic", "song.json")


def _json_type_ok(instance, expected: str) -> bool:
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "null":
        return instance is None
    return True


def _resolve(root_schema: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref {ref!r}")
    target = root_schema
    for part in ref[2:].split("/"):
        target = target[part]
    return target


def validate(instance, schema: dict, root_schema: dict, path: str = "") -> list[str]:
    """Return a list of structural error messages for ``instance``.

    Deliberately narrow: it implements exactly the keywords used by the v1
    schema, which is enough to prove the demo scores are structurally valid and
    that the root object rejects unknown properties while accepting ``loop``.
    """

    errors: list[str] = []

    if "$ref" in schema:
        return validate(instance, _resolve(root_schema, schema["$ref"]), root_schema, path)

    if "oneOf" in schema:
        matching = [
            sub
            for sub in schema["oneOf"]
            if not validate(instance, sub, root_schema, path)
        ]
        if len(matching) != 1:
            errors.append(f"{path or '/'}: expected exactly one oneOf match, got {len(matching)}")
        return errors

    expected_type = schema.get("type")
    if expected_type is not None:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_json_type_ok(instance, t) for t in types):
            errors.append(f"{path or '/'}: expected type {expected_type!r}")
            return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path or '/'}: expected const {schema['const']!r}")

    if isinstance(instance, str):
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path or '/'}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path or '/'}: does not match pattern {schema['pattern']!r}")

    if isinstance(instance, int) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path or '/'}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path or '/'}: above maximum {schema['maximum']}")

    if isinstance(instance, dict):
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(f"{path or '/'}: fewer than minProperties {schema['minProperties']}")
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            errors.append(f"{path or '/'}: more than maxProperties {schema['maxProperties']}")
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path or '/'}: missing required property {name!r}")
        if "propertyNames" in schema:
            name_schema = schema["propertyNames"]
            for key in instance:
                for message in validate(key, name_schema, root_schema, f"{path}/{key}"):
                    errors.append(message)
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            child = f"{path}/{key}"
            if key in properties:
                errors.extend(validate(value, properties[key], root_schema, child))
            elif additional is False:
                errors.append(f"{child}: unknown property not allowed by additionalProperties:false")
            elif isinstance(additional, dict):
                errors.extend(validate(value, additional, root_schema, child))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path or '/'}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path or '/'}: more than maxItems {schema['maxItems']}")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], root_schema, f"{path}/{index}"))

    return errors


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class StructuralValidatorSelfTests(unittest.TestCase):
    """Sanity checks that the tiny validator actually rejects bad documents."""

    def setUp(self) -> None:
        self.schema = load_json(SCHEMA_PATH)

    def test_validator_accepts_fixture_song(self) -> None:
        self.assertEqual(validate(load_json(FIXTURE_SONG), self.schema, self.schema), [])

    def test_validator_rejects_missing_required_root_field(self) -> None:
        document = load_json(FIXTURE_SONG)
        del document["tracks"]
        self.assertTrue(validate(document, self.schema, self.schema))

    def test_validator_rejects_wrong_scalar_types(self) -> None:
        document = load_json(FIXTURE_SONG)
        document["version"] = "1"
        self.assertTrue(validate(document, self.schema, self.schema))


class RootLoopSchemaTests(unittest.TestCase):
    """The root ``loop`` flag is optional and boolean-only (ATMlib2FX-9jo)."""

    def setUp(self) -> None:
        self.schema = load_json(SCHEMA_PATH)
        self.base = load_json(FIXTURE_SONG)

    def _validate(self, document: dict) -> list[str]:
        return validate(document, self.schema, self.schema)

    def test_schema_declares_optional_boolean_loop(self) -> None:
        loop_schema = self.schema["properties"].get("loop")
        self.assertIsNotNone(loop_schema, "root schema must declare a `loop` property")
        self.assertEqual(loop_schema.get("type"), "boolean")
        self.assertNotIn("loop", self.schema["required"])

    def test_root_additional_properties_still_false(self) -> None:
        self.assertIs(self.schema.get("additionalProperties"), False)

    def test_accepts_loop_true(self) -> None:
        document = copy.deepcopy(self.base)
        document["loop"] = True
        self.assertEqual(self._validate(document), [])

    def test_accepts_loop_false(self) -> None:
        document = copy.deepcopy(self.base)
        document["loop"] = False
        self.assertEqual(self._validate(document), [])

    def test_accepts_loop_omitted(self) -> None:
        document = copy.deepcopy(self.base)
        document.pop("loop", None)
        self.assertEqual(self._validate(document), [])

    def test_rejects_non_boolean_loop(self) -> None:
        for bad in ("true", "", 0, 1, [], {}, None):
            with self.subTest(bad=bad):
                document = copy.deepcopy(self.base)
                document["loop"] = bad
                errors = self._validate(document)
                self.assertTrue(errors, f"loop={bad!r} must be rejected")
                self.assertTrue(
                    any("/loop" in message for message in errors),
                    f"error should point at /loop: {errors}",
                )

    def test_rejects_unknown_root_property(self) -> None:
        document = copy.deepcopy(self.base)
        document["surprise"] = 1
        errors = self._validate(document)
        self.assertTrue(
            any("surprise" in message for message in errors),
            f"unknown root property must be rejected: {errors}",
        )


class DemoScoreStructuralTests(unittest.TestCase):
    """Every shipped demo score must satisfy the public structural schema."""

    def setUp(self) -> None:
        self.schema = load_json(SCHEMA_PATH)

    def test_all_demo_songs_validate_structurally(self) -> None:
        paths = sorted(glob.glob(DEMO_GLOB, recursive=True))
        self.assertTrue(paths, "expected at least one demo song.json")
        for path in paths:
            with self.subTest(song=os.path.relpath(path, REPO_ROOT)):
                self.assertEqual(
                    validate(load_json(path), self.schema, self.schema),
                    [],
                    f"{path} failed structural validation",
                )

    def test_demo_loop_true_variant_is_covered(self) -> None:
        document = load_json(DEMO_LOOP_TRUE)
        self.assertIs(document.get("loop"), True)
        self.assertEqual(validate(document, self.schema, self.schema), [])

    def test_demo_loop_false_variant_is_covered(self) -> None:
        document = copy.deepcopy(load_json(DEMO_LOOP_TRUE))
        document["loop"] = False
        self.assertEqual(validate(document, self.schema, self.schema), [])

    def test_demo_loop_omitted_variant_is_covered(self) -> None:
        document = load_json(FIXTURE_SONG)
        self.assertNotIn("loop", document)
        self.assertEqual(validate(document, self.schema, self.schema), [])


if __name__ == "__main__":
    unittest.main()
