# 只读参考：catalog.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/catalog.schema.json",
  "title": "SelfWorkFlow compiled catalog envelope",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "catalog", "catalogHash"],
  "properties": {
    "schemaVersion": {"enum": [1, 2]},
    "catalog": {"$ref": "#/$defs/catalog"},
    "catalogHash": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    }
  },
  "$defs": {
    "identifier": {
      "type": "string",
      "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"
    },
    "relativeSourcePath": {
      "type": "string",
      "minLength": 1,
      "maxLength": 1024
    },
    "stringList": {
      "type": "array",
      "maxItems": 256,
      "uniqueItems": true,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 512
      }
    },
    "identifierList": {
      "type": "array",
      "maxItems": 256,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/identifier"}
    },
    "fileExtensionList": {
      "type": "array",
      "maxItems": 128,
      "uniqueItems": true,
      "items": {
        "type": "string",
        "pattern": "^\\.[a-z0-9][a-z0-9+._-]{0,31}$"
      }
    },
    "operationType": {
      "enum": [
        "analyze",
        "design",
        "plan",
        "implement",
        "debug",
        "review",
        "verify",
        "document",
        "install",
        "publish",
        "knowledge-read",
        "knowledge-write"
      ]
    },
    "operationTypeList": {
      "type": "array",
      "maxItems": 12,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/operationType"}
    },
    "selectors": {
      "type": "object",
      "additionalProperties": false,
      "required": ["fileExtensions", "operationTypes", "semanticTerms"],
      "properties": {
        "fileExtensions": {"$ref": "#/$defs/fileExtensionList"},
        "operationTypes": {"$ref": "#/$defs/operationTypeList"},
        "semanticTerms": {"$ref": "#/$defs/stringList"}
      }
    },
    "mandatoryWhen": {
      "type": "object",
      "additionalProperties": false,
      "required": ["match", "scopes", "fileExtensions", "operationTypes"],
      "properties": {
        "match": {"enum": ["any", "all"]},
        "scopes": {
          "type": "array",
          "maxItems": 3,
          "uniqueItems": true,
          "items": {"enum": ["global", "safety", "project"]}
        },
        "fileExtensions": {"$ref": "#/$defs/fileExtensionList"},
        "operationTypes": {"$ref": "#/$defs/operationTypeList"}
      }
    },
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "path", "revision", "contentHash"],
      "properties": {
        "kind": {"enum": ["workflow", "skill", "planned"]},
        "path": {"$ref": "#/$defs/relativeSourcePath"},
        "revision": {
          "type": "string",
          "pattern": "^git:[0-9a-f]{40}$"
        },
        "contentHash": {
          "type": "string",
          "pattern": "^sha256:[0-9a-f]{64}$"
        }
      }
    },
    "alias": {
      "type": "object",
      "additionalProperties": false,
      "required": ["name", "target"],
      "properties": {
        "name": {"$ref": "#/$defs/identifier"},
        "target": {"$ref": "#/$defs/identifier"}
      }
    },
    "constraint": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "target", "mode", "value"],
      "properties": {
        "kind": {
          "enum": [
            "capability-state",
            "verification-status",
            "review-level",
            "workflow-action"
          ]
        },
        "target": {"$ref": "#/$defs/identifier"},
        "mode": {"enum": ["equals", "at-least", "recommend"]},
        "value": {
          "enum": [
            "supported",
            "passed",
            "L0",
            "L1",
            "L2",
            "L3",
            "perform",
            "record"
          ]
        }
      }
    },
    "protectedRuleOperation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["operation", "id", "constraint"],
      "properties": {
        "operation": {"enum": ["add-requirement", "advisory"]},
        "id": {"$ref": "#/$defs/identifier"},
        "constraint": {"$ref": "#/$defs/constraint"}
      }
    },
    "supportEvidence": {
      "type": "object",
      "additionalProperties": false,
      "required": ["sourceIntegrity", "adapterSupport", "runtimeCapability", "behaviorEvidence"],
      "properties": {
        "sourceIntegrity": {"enum": ["supported", "unverified", "unsupported"]},
        "adapterSupport": {"enum": ["supported", "unverified", "unsupported"]},
        "runtimeCapability": {"enum": ["supported", "unverified", "unsupported"]},
        "behaviorEvidence": {"enum": ["supported", "unverified", "unsupported"]}
      }
    },
    "module": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "sourceEntryId", "contractVersion", "stage", "slot", "activation", "invocation", "inputContract", "outputContract", "requiredCapabilities", "sideEffects", "dependencies", "conflicts", "priority", "supportEvidence", "when"],
      "properties": {
        "id": {"$ref": "#/$defs/identifier"},
        "sourceEntryId": {"$ref": "#/$defs/identifier"},
        "contractVersion": {"const": 2},
        "stage": {"enum": ["discovered", "capability-checked", "classified", "designed", "planned", "implemented", "reviewed", "verified", "completed"]},
        "slot": {"$ref": "#/$defs/identifier"},
        "activation": {"enum": ["mandatory", "default", "explicit", "deterministic", "full-default", "deep-default"]},
        "invocation": {"type": "object", "additionalProperties": false, "required": ["kind", "ref"], "properties": {"kind": {"enum": ["agent-native", "skill", "mcp"]}, "ref": {"type": "string", "minLength": 1, "maxLength": 512}}},
        "inputContract": {"type": "string", "minLength": 1, "maxLength": 256},
        "outputContract": {"type": "string", "minLength": 1, "maxLength": 256},
        "requiredCapabilities": {"$ref": "#/$defs/identifierList"},
        "sideEffects": {"type": "object", "additionalProperties": false, "required": ["level", "requiresConfirmation"], "properties": {"level": {"enum": ["none", "read", "local-write", "external-write"]}, "requiresConfirmation": {"type": "boolean"}}},
        "dependencies": {"$ref": "#/$defs/identifierList"},
        "conflicts": {"$ref": "#/$defs/identifierList"},
        "priority": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "supportEvidence": {"$ref": "#/$defs/supportEvidence"},
        "when": {"type": "object", "additionalProperties": false, "required": ["operationTypes", "strengths", "writeTask"], "properties": {"operationTypes": {"$ref": "#/$defs/operationTypeList"}, "strengths": {"type": "array", "uniqueItems": true, "items": {"enum": ["Light", "Full", "Deep"]}}, "writeTask": {"enum": [true, false, "any"]}}}
      }
    },
    "moduleRegistry": {
      "type": "object", "additionalProperties": false,
      "required": ["schemaVersion", "modules"],
      "properties": {"schemaVersion": {"const": 2}, "modules": {"type": "array", "maxItems": 4096, "items": {"$ref": "#/$defs/module"}}}
    },
    "entry": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "domain",
        "id",
        "displayName",
        "source",
        "aliases",
        "triggers",
        "exclusions",
        "selectors",
        "stages",
        "requiredCapabilities",
        "dependencies",
        "conflicts",
        "composition",
        "mandatory",
        "mandatoryWhen",
        "priority",
        "contextCost",
        "supportStatus",
        "protectedRuleOperations"
      ],
      "properties": {
        "domain": {"$ref": "#/$defs/identifier"},
        "id": {"$ref": "#/$defs/identifier"},
        "displayName": {
          "type": "string",
          "minLength": 1,
          "maxLength": 256
        },
        "source": {"$ref": "#/$defs/source"},
        "aliases": {
          "type": "array",
          "maxItems": 64,
          "items": {"$ref": "#/$defs/alias"}
        },
        "triggers": {"$ref": "#/$defs/stringList"},
        "exclusions": {"$ref": "#/$defs/stringList"},
        "selectors": {"$ref": "#/$defs/selectors"},
        "stages": {
          "type": "array",
          "maxItems": 9,
          "uniqueItems": true,
          "items": {
            "enum": [
              "discovered",
              "capability-checked",
              "classified",
              "designed",
              "planned",
              "implemented",
              "reviewed",
              "verified",
              "completed"
            ]
          }
        },
        "requiredCapabilities": {"$ref": "#/$defs/identifierList"},
        "dependencies": {"$ref": "#/$defs/identifierList"},
        "conflicts": {"$ref": "#/$defs/identifierList"},
        "composition": {"enum": ["standalone", "augment", "exclusive"]},
        "mandatory": {"type": "boolean"},
        "mandatoryWhen": {"$ref": "#/$defs/mandatoryWhen"},
        "priority": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "contextCost": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "supportStatus": {"enum": ["supported", "unverified"]},
        "protectedRuleOperations": {
          "type": "array",
          "maxItems": 256,
          "items": {"$ref": "#/$defs/protectedRuleOperation"}
        }
      }
    },
    "sourceEntry": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id",
        "displayName",
        "source",
        "aliases",
        "triggers",
        "exclusions",
        "selectors",
        "stages",
        "requiredCapabilities",
        "dependencies",
        "conflicts",
        "composition",
        "mandatory",
        "mandatoryWhen",
        "priority",
        "contextCost",
        "supportStatus",
        "protectedRuleOperations"
      ],
      "properties": {
        "id": {"$ref": "#/$defs/identifier"},
        "displayName": {
          "type": "string",
          "minLength": 1,
          "maxLength": 256
        },
        "source": {"$ref": "#/$defs/source"},
        "aliases": {
          "type": "array",
          "maxItems": 64,
          "items": {"$ref": "#/$defs/alias"}
        },
        "triggers": {"$ref": "#/$defs/stringList"},
        "exclusions": {"$ref": "#/$defs/stringList"},
        "selectors": {"$ref": "#/$defs/selectors"},
        "stages": {
          "type": "array",
          "maxItems": 9,
          "uniqueItems": true,
          "items": {
            "enum": [
              "discovered",
              "capability-checked",
              "classified",
              "designed",
              "planned",
              "implemented",
              "reviewed",
              "verified",
              "completed"
            ]
          }
        },
        "requiredCapabilities": {"$ref": "#/$defs/identifierList"},
        "dependencies": {"$ref": "#/$defs/identifierList"},
        "conflicts": {"$ref": "#/$defs/identifierList"},
        "composition": {"enum": ["standalone", "augment", "exclusive"]},
        "mandatory": {"type": "boolean"},
        "mandatoryWhen": {"$ref": "#/$defs/mandatoryWhen"},
        "priority": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "contextCost": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "supportStatus": {"enum": ["supported", "unverified"]},
        "protectedRuleOperations": {
          "type": "array",
          "maxItems": 256,
          "items": {"$ref": "#/$defs/protectedRuleOperation"}
        }
      }
    },
    "catalog": {
      "type": "object",
      "additionalProperties": false,
      "required": ["domains", "entries", "modules", "standardCapabilities"],
      "properties": {
        "domains": {
          "type": "array",
          "maxItems": 128,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/identifier"}
        },
        "entries": {
          "type": "array",
          "maxItems": 4096,
          "items": {"$ref": "#/$defs/entry"}
        },
        "modules": {"type": "array", "maxItems": 4096, "items": {"$ref": "#/$defs/module"}},
        "standardCapabilities": {
          "type": "array",
          "maxItems": 256,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/identifier"}
        }
      }
    },
    "index": {
      "type": "object",
      "additionalProperties": false,
      "required": ["schemaVersion", "domains", "modules", "standardCapabilities"],
      "properties": {
        "schemaVersion": {"enum": [1, 2]},
        "domains": {
          "type": "array",
          "maxItems": 128,
          "uniqueItems": true,
          "items": {
            "type": "string",
            "pattern": "^domains/[a-z0-9][a-z0-9._-]{0,127}\\.yaml$"
          }
        },
        "modules": {"oneOf": [{"type": "null"}, {"type": "string", "pattern": "^modules\\.yaml$"}]},
        "standardCapabilities": {
          "type": "array",
          "maxItems": 256,
          "uniqueItems": true,
          "items": {"$ref": "#/$defs/identifier"}
        }
      }
    },
    "domain": {
      "type": "object",
      "additionalProperties": false,
      "required": ["schemaVersion", "domain", "entries"],
      "properties": {
        "schemaVersion": {"const": 1},
        "domain": {"$ref": "#/$defs/identifier"},
        "entries": {
          "type": "array",
          "maxItems": 4096,
          "items": {"$ref": "#/$defs/sourceEntry"}
        }
      }
    }
  }
}

````
