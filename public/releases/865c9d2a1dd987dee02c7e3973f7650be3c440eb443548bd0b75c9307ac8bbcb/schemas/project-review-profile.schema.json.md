# 只读参考：project-review-profile.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/project-review-profile.schema.json",
  "title": "SelfWorkFlow project review profile",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "additionalReviewSkills"],
  "properties": {
    "schemaVersion": {"const": 1},
    "additionalReviewSkills": {
      "type": "array",
      "maxItems": 32,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/skill"}
    }
  },
  "$defs": {
    "stableId": {
      "type": "string",
      "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"
    },
    "sha256": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "skill": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "path", "contentHash", "required"],
      "properties": {
        "id": {"$ref": "#/$defs/stableId"},
        "path": {
          "type": "string",
          "minLength": 1,
          "maxLength": 1024,
          "pattern": "^(?![A-Za-z]:)(?!/)(?!\\\\)(?!.*\\\\)(?!.*:)(?!.*(?:^|/)\\.{1,2}(?:/|$))[^\\x00-\\x1f]+$"
        },
        "contentHash": {"$ref": "#/$defs/sha256"},
        "required": {"type": "boolean"}
      }
    }
  }
}

````
