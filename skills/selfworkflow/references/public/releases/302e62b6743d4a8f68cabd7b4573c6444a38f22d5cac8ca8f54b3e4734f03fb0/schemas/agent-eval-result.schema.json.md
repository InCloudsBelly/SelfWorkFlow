# 只读参考：agent-eval-result.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/agent-eval-result.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion",
    "scenarioId",
    "summary",
    "criticalPassed",
    "bonusPassed",
    "prohibitedHits",
    "model",
    "reasoningEffort"
  ],
  "properties": {
    "schemaVersion": {"const": 1},
    "scenarioId": {"type": "string", "minLength": 1, "maxLength": 128},
    "summary": {"type": "string", "minLength": 1, "maxLength": 4096},
    "criticalPassed": {
      "type": "array",
      "maxItems": 128,
      "uniqueItems": true,
      "items": {"type": "string", "minLength": 1, "maxLength": 128}
    },
    "bonusPassed": {
      "type": "array",
      "maxItems": 128,
      "uniqueItems": true,
      "items": {"type": "string", "minLength": 1, "maxLength": 128}
    },
    "prohibitedHits": {
      "type": "array",
      "maxItems": 128,
      "uniqueItems": true,
      "items": {"type": "string", "minLength": 1, "maxLength": 128}
    },
    "model": {"type": "string", "minLength": 1, "maxLength": 128},
    "reasoningEffort": {"enum": ["low", "medium", "high", "xhigh", "max", "ultra"]}
  }
}

````
