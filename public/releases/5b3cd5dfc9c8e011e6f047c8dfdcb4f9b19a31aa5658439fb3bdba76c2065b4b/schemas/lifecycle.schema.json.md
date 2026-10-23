# 只读参考：lifecycle.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/lifecycle.schema.json",
  "title": "SelfWorkFlow lifecycle configuration",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion",
    "phases",
    "executionStatuses",
    "verificationStatuses",
    "capabilities",
    "derivedVerification"
  ],
  "properties": {
    "schemaVersion": {
      "const": 1
    },
    "phases": {
      "type": "array",
      "prefixItems": [
        {"const": "discovered"},
        {"const": "capability-checked"},
        {"const": "classified"},
        {"const": "designed"},
        {"const": "planned"},
        {"const": "implemented"},
        {"const": "reviewed"},
        {"const": "verified"},
        {"const": "completed"}
      ],
      "items": false,
      "minItems": 9
    },
    "executionStatuses": {
      "type": "array",
      "prefixItems": [
        {"const": "active"},
        {"const": "paused"},
        {"const": "blocked"},
        {"const": "failed"},
        {"const": "completed"}
      ],
      "items": false,
      "minItems": 5
    },
    "verificationStatuses": {
      "type": "array",
      "prefixItems": [
        {"const": "not-applicable"},
        {"const": "not-run"},
        {"const": "partial"},
        {"const": "passed"},
        {"const": "failed"}
      ],
      "items": false,
      "minItems": 5
    },
    "capabilities": {
      "type": "object",
      "additionalProperties": false,
      "required": ["states", "standardNames"],
      "properties": {
        "states": {
          "type": "array",
          "prefixItems": [
            {"const": "supported"},
            {"const": "unsupported"},
            {"const": "unverified"}
          ],
          "items": false,
          "minItems": 3
        },
        "standardNames": {
          "type": "array",
          "prefixItems": [
            {"const": "skill-discovery"},
            {"const": "independent-context"},
            {"const": "command-execution"},
            {"const": "filesystem-read"},
            {"const": "filesystem-write"},
            {"const": "test-execution"},
            {"const": "user-confirmation"},
            {"const": "task-resume"},
            {"const": "knowledge-read"},
            {"const": "knowledge-write"}
          ],
          "items": false,
          "minItems": 10
        }
      }
    },
    "derivedVerification": {
      "type": "object",
      "additionalProperties": false,
      "required": ["unverifiedFrom"],
      "properties": {
        "unverifiedFrom": {
          "type": "array",
          "prefixItems": [
            {"const": "not-run"},
            {"const": "partial"}
          ],
          "items": false,
          "minItems": 2
        }
      }
    }
  }
}

````
