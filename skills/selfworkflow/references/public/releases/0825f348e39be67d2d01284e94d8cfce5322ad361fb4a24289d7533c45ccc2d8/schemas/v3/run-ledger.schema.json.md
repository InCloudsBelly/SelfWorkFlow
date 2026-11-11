# 只读参考：run-ledger.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/run-ledger.schema.json",
  "title": "SelfWorkFlow V3 execution run ledger",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion", "planHash", "requestHash", "capabilitySnapshotHash", "status", "stages"
  ],
  "properties": {
    "schemaVersion": {"const": 3},
    "planHash": {"$ref": "#/$defs/sha256"},
    "requestHash": {"$ref": "#/$defs/sha256"},
    "capabilitySnapshotHash": {"$ref": "#/$defs/sha256"},
    "status": {"enum": ["pending", "active", "paused", "failed", "completed", "superseded"]},
    "stages": {
      "type": "array",
      "minItems": 1,
      "maxItems": 128,
      "items": {"$ref": "#/$defs/stage"}
    },
    "supersededByPlanHash": {"$ref": "#/$defs/sha256"}
  },
  "allOf": [
    {
      "if": {"properties": {"status": {"const": "superseded"}}, "required": ["status"]},
      "then": {"required": ["supersededByPlanHash"]},
      "else": {"not": {"required": ["supersededByPlanHash"]}}
    }
  ],
  "$defs": {
    "stableId": {
      "type": "string",
      "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"
    },
    "sha256": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "utcTimestamp": {
      "type": "string",
      "format": "date-time",
      "pattern": "^\\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\\d|3[01])T(?:[01]\\d|2[0-3]):[0-5]\\d:[0-5]\\d(?:\\.\\d+)?Z$"
    },
    "hashList": {
      "type": "array",
      "maxItems": 4096,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/sha256"}
    },
    "attempt": {
      "type": "object",
      "additionalProperties": false,
      "required": ["attemptRef", "ordinal", "previousAttemptRef", "startedAt"],
      "properties": {
        "attemptRef": {"$ref": "#/$defs/stableId"},
        "ordinal": {"type": "integer", "minimum": 1, "maximum": 4096},
        "previousAttemptRef": {
          "oneOf": [{"type": "null"}, {"$ref": "#/$defs/stableId"}]
        },
        "startedAt": {"$ref": "#/$defs/utcTimestamp"},
        "completedAt": {"$ref": "#/$defs/utcTimestamp"},
        "inputArtifactHashes": {"$ref": "#/$defs/hashList"}
      }
    },
    "slotResult": {
      "type": "object",
      "additionalProperties": false,
      "required": ["attemptRef", "slotId", "moduleId", "artifactHash"],
      "properties": {
        "attemptRef": {"$ref": "#/$defs/stableId"},
        "slotId": {"$ref": "#/$defs/stableId"},
        "moduleId": {"$ref": "#/$defs/stableId"},
        "artifactHash": {"$ref": "#/$defs/sha256"}
      }
    },
    "gateResult": {
      "type": "object",
      "additionalProperties": false,
      "required": ["attemptRef", "gateId", "outcome", "artifactHash"],
      "properties": {
        "attemptRef": {"$ref": "#/$defs/stableId"},
        "gateId": {"$ref": "#/$defs/stableId"},
        "outcome": {"enum": ["passed", "failed", "paused"]},
        "artifactHash": {"$ref": "#/$defs/sha256"}
      }
    },
    "runtimeSkip": {
      "type": "object",
      "additionalProperties": false,
      "required": ["attemptRef", "slotId", "reasonCode", "evidenceHash"],
      "properties": {
        "attemptRef": {"$ref": "#/$defs/stableId"},
        "slotId": {"$ref": "#/$defs/stableId"},
        "reasonCode": {"$ref": "#/$defs/stableId"},
        "evidenceHash": {"$ref": "#/$defs/sha256"}
      }
    },
    "selectionReceiptRef": {
      "type": "object",
      "additionalProperties": false,
      "required": ["attemptRef", "receiptHash"],
      "properties": {
        "attemptRef": {"$ref": "#/$defs/stableId"},
        "receiptHash": {"$ref": "#/$defs/sha256"}
      }
    },
    "teaReceipt": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "schemaVersion", "planHash", "attemptRef", "stageId", "slotId", "moduleId",
        "workflowId", "referenceHash", "inputHash", "outputRelative", "outputHash",
        "status", "receiptHash"
      ],
      "properties": {
        "schemaVersion": {"const": 1},
        "planHash": {"$ref": "#/$defs/sha256"},
        "attemptRef": {"$ref": "#/$defs/stableId"},
        "stageId": {"$ref": "#/$defs/stableId"},
        "slotId": {"$ref": "#/$defs/stableId"},
        "moduleId": {"$ref": "#/$defs/stableId"},
        "workflowId": {"enum": ["test-design", "atdd", "test-review", "trace", "nfr"]},
        "referenceHash": {"$ref": "#/$defs/sha256"},
        "inputHash": {"$ref": "#/$defs/sha256"},
        "outputRelative": {"type": "string", "pattern": "^[^./][^:]*[^./]$"},
        "outputHash": {"$ref": "#/$defs/sha256"},
        "status": {"const": "validated"},
        "receiptHash": {"$ref": "#/$defs/sha256"}
      }
    },
    "stage": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "stageId", "status", "attempts", "slotResults", "gateResults", "runtimeSkips",
        "selectionReceiptRefs", "reviewAggregateHashes", "coverageResultHashes", "artifactHashes"
      ],
      "properties": {
        "stageId": {"$ref": "#/$defs/stableId"},
        "status": {"enum": ["pending", "active", "passed", "failed", "paused", "skipped"]},
        "attempts": {
          "type": "array",
          "maxItems": 4096,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/attempt"}
        },
        "slotResults": {
          "type": "array",
          "maxItems": 4096,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/slotResult"}
        },
        "gateResults": {
          "type": "array",
          "maxItems": 4096,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/gateResult"}
        },
        "runtimeSkips": {
          "type": "array",
          "maxItems": 4096,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/runtimeSkip"}
        },
        "selectionReceiptRefs": {
          "type": "array",
          "maxItems": 4096,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/selectionReceiptRef"}
        },
        "teaReceipts": {
          "type": "array",
          "maxItems": 4096,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/teaReceipt"}
        },
        "teaReceiptHashes": {"$ref": "#/$defs/hashList"},
        "reviewAggregateHashes": {"$ref": "#/$defs/hashList"},
        "coverageResultHashes": {"$ref": "#/$defs/hashList"},
        "artifactHashes": {"$ref": "#/$defs/hashList"}
      }
    }
  }
}

````
