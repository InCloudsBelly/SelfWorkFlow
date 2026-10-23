# 只读参考：bootstrap-tool-manifest.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/bootstrap-tool-manifest.schema.json",
  "title": "SelfWorkFlow Bootstrap Tool Manifest",
  "type": "object",
  "additionalProperties": false,
  "$defs": {
    "canonicalSemVer": {
      "type": "string",
      "pattern": "^(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$"
    }
  },
  "required": [
    "schemaVersion",
    "bootstrapRoot",
    "package",
    "packageTreeHash",
    "daclSddl",
    "expectedCliVersion",
    "cliVersionVerification",
    "planHash"
  ],
  "properties": {
    "schemaVersion": {
      "const": 2
    },
    "bootstrapRoot": {
      "type": "string",
      "pattern": "^[A-Za-z]:\\\\(?!\\.{1,2}(?:\\\\|$))(?!.*\\\\\\.{1,2}(?:\\\\|$))[^/\\r\\n]*[^\\\\/\\r\\n]$"
    },
    "package": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "name",
        "version",
        "integrity"
      ],
      "properties": {
        "name": {
          "const": "@openai/codex"
        },
        "version": {
          "$ref": "#/$defs/canonicalSemVer"
        },
        "integrity": {
          "type": "string",
          "pattern": "^sha(256|384|512)-[A-Za-z0-9+/_=-]+$"
        }
      }
    },
    "packageTreeHash": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "daclSddl": {
      "type": "string",
      "pattern": "^D:P",
      "not": {
        "pattern": "\\([^)]*;;;(?:WD|S-1-1-0)\\)"
      }
    },
    "expectedCliVersion": {
      "$ref": "#/$defs/canonicalSemVer"
    },
    "cliVersionVerification": {
      "const": "not-run"
    },
    "planHash": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$"
    }
  }
}

````
