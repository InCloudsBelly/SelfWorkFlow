# 只读参考：design-review-summary.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/design-review-summary.schema.json",
  "title": "SelfWorkFlow V3 design review summary",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "summaryId", "designHash", "reviewerPolicyHash", "objective", "scope", "constraints", "assumptions", "alternatives", "risks", "acceptanceCriteria", "summaryHash"],
  "properties": {
    "schemaVersion": {"const": 3},
    "summaryId": {"$ref": "#/$defs/id"},
    "designHash": {"$ref": "#/$defs/hash"},
    "reviewerPolicyHash": {"$ref": "#/$defs/hash"},
    "objective": {"$ref": "#/$defs/text"},
    "scope": {
      "type": "object", "additionalProperties": false,
      "required": ["included", "excluded"],
      "properties": {
        "included": {"$ref": "#/$defs/textList"},
        "excluded": {"$ref": "#/$defs/textList"}
      }
    },
    "constraints": {"$ref": "#/$defs/textList"},
    "assumptions": {"$ref": "#/$defs/textList"},
    "alternatives": {
      "type": "array", "minItems": 1, "maxItems": 64, "uniqueItems": true,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["alternativeId", "summary", "disposition"],
        "properties": {
          "alternativeId": {"$ref": "#/$defs/id"},
          "summary": {"$ref": "#/$defs/text"},
          "disposition": {"enum": ["selected", "rejected", "deferred"]}
        }
      }
    },
    "risks": {
      "type": "array", "minItems": 1, "maxItems": 128, "uniqueItems": true,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["riskId", "description", "mitigation"],
        "properties": {
          "riskId": {"$ref": "#/$defs/id"},
          "description": {"$ref": "#/$defs/text"},
          "mitigation": {"$ref": "#/$defs/text"}
        }
      }
    },
    "acceptanceCriteria": {
      "type": "array", "minItems": 1, "maxItems": 128, "uniqueItems": true,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["criterionId", "description", "evidenceExpectation"],
        "properties": {
          "criterionId": {"$ref": "#/$defs/id"},
          "description": {"$ref": "#/$defs/text"},
          "evidenceExpectation": {"$ref": "#/$defs/text"}
        }
      }
    },
    "summaryHash": {"$ref": "#/$defs/hash"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "text": {"type": "string", "minLength": 1, "maxLength": 4096},
    "textList": {"type": "array", "maxItems": 128, "uniqueItems": true, "items": {"$ref": "#/$defs/text"}}
  }
}

````
