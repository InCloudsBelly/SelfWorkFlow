# 只读参考：decision-record.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "decisionId", "question", "alternatives", "recommendationId", "selectedId", "rationaleSummary", "impact", "reviewContext", "verificationRefs"],
  "properties": {
    "schemaVersion": {"const": 1},
    "decisionId": {"$ref": "#/$defs/id"},
    "question": {"type": "string", "minLength": 1, "maxLength": 1024},
    "alternatives": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"$ref": "#/$defs/alternative"}},
    "recommendationId": {"$ref": "#/$defs/id"},
    "selectedId": {"$ref": "#/$defs/id"},
    "rationaleSummary": {"type": "string", "minLength": 1, "maxLength": 2048},
    "impact": {"$ref": "#/$defs/impact"},
    "reviewContext": {"$ref": "#/$defs/reviewContext"},
    "verificationRefs": {"type": "array", "maxItems": 16, "uniqueItems": true, "items": {"$ref": "#/$defs/reference"}}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"},
    "alternative": {
      "type": "object", "additionalProperties": false,
      "required": ["id", "summary"],
      "properties": {"id": {"$ref": "#/$defs/id"}, "summary": {"type": "string", "minLength": 1, "maxLength": 1024}}
    },
    "impact": {
      "type": "object", "additionalProperties": false,
      "required": ["scope", "rollback", "compatibility", "security", "externalSideEffects", "uncertainty"],
      "properties": {
        "scope": {"const": "local-component"}, "rollback": {"const": "easy"},
        "compatibility": {"const": "unchanged"}, "security": {"const": "unchanged"},
        "externalSideEffects": {"const": false}, "uncertainty": {"const": "low"}
      }
    },
    "reviewContext": {
      "type": "object", "additionalProperties": false,
      "required": ["mode", "contextId", "independence"],
      "properties": {
        "mode": {"enum": ["independent-subagent", "structured-self-review"]},
        "contextId": {"$ref": "#/$defs/id"},
        "independence": {"enum": ["independent", "unverified"]}
      },
      "allOf": [
        {"if": {"properties": {"mode": {"const": "independent-subagent"}}, "required": ["mode"]}, "then": {"properties": {"independence": {"const": "independent"}}}},
        {"if": {"properties": {"mode": {"const": "structured-self-review"}}, "required": ["mode"]}, "then": {"properties": {"independence": {"const": "unverified"}}}}
      ]
    },
    "reference": {
      "type": "object", "additionalProperties": false,
      "required": ["id", "kind", "sha256", "sizeBytes"],
      "properties": {
        "id": {"$ref": "#/$defs/id"},
        "kind": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,63}$"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "sizeBytes": {"type": "integer", "minimum": 0, "maximum": 1073741824}
      }
    }
  }
}

````
