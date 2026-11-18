# 只读参考：stage-result.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "status", "summary", "typedArtifacts", "typedEvidenceRefs", "issues", "nextStageRequest"],
  "properties": {
    "schemaVersion": {"const": 1},
    "status": {"enum": ["passed", "failed", "paused", "skipped"]},
    "summary": {"type": "string", "maxLength": 4096},
    "typedArtifacts": {"type": "array", "maxItems": 256, "items": {"$ref": "#/$defs/reference"}},
    "typedEvidenceRefs": {"type": "array", "maxItems": 256, "items": {"$ref": "#/$defs/reference"}},
    "issues": {"type": "array", "maxItems": 256, "items": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,127}$"}},
    "nextStageRequest": {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": false, "required": ["stageId", "reasonCode"], "properties": {"stageId": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,63}$"}, "reasonCode": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,127}$"}}}]}
  },
  "$defs": {
    "reference": {"type": "object", "additionalProperties": false, "required": ["id", "kind", "sha256", "sizeBytes"], "properties": {"id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}, "kind": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,63}$"}, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "sizeBytes": {"type": "integer", "minimum": 0, "maximum": 1073741824}}}
  }
}

````
