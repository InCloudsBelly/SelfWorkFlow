# 只读参考：knowledge-contract.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "optional", "phases", "invariants", "defaultRouting"],
  "properties": {
    "schemaVersion": {"const": 1},
    "optional": {"const": true},
    "phases": {
      "type": "object", "additionalProperties": false,
      "required": ["read", "propose", "update"],
      "properties": {
        "read": {
          "type": "object", "additionalProperties": false,
          "required": ["publishesKnowledge", "requiredEvidence"],
          "properties": {
            "publishesKnowledge": {"const": false},
            "requiredEvidence": {"const": ["sourceId", "revision", "contentHash", "verificationStatus"]}
          }
        },
        "propose": {
          "type": "object", "additionalProperties": false,
          "required": ["publishesKnowledge", "runtimeSideEffectsMayOccur"],
          "properties": {
            "publishesKnowledge": {"const": false},
            "runtimeSideEffectsMayOccur": {"const": ["oauth-refresh", "temporary-transaction"]}
          }
        },
        "update": {
          "type": "object", "additionalProperties": false,
          "required": ["requiresExplicitConfirmation", "requiresCompareAndSwap", "requiresIndependentReview"],
          "properties": {
            "requiresExplicitConfirmation": {"const": true},
            "requiresCompareAndSwap": {"const": true},
            "requiresIndependentReview": {"const": true}
          }
        }
      }
    },
    "invariants": {
      "type": "object", "additionalProperties": false,
      "required": ["privateModelReasoning", "missingBackendForCodeTask"],
      "properties": {
        "privateModelReasoning": {"const": "forbidden"},
        "missingBackendForCodeTask": {"const": "knowledge-sync-todo"}
      }
    },
    "defaultRouting": {
      "type": "object",
      "additionalProperties": false,
      "required": ["profile", "backend", "intents", "fallback"],
      "properties": {
        "profile": {"const": "knowledge"},
        "backend": {"const": "selfopenwiki"},
        "intents": {
          "const": ["wiki-visualize", "wiki-summary", "wiki-organize", "wiki-update"]
        },
        "fallback": {"const": "forbidden"}
      }
    }
  }
}

````
