# 只读参考：grill-completion-attestation.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/grill-completion-attestation.schema.json",
  "title": "SelfWorkFlow V3 Grill completion attestation",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion", "moduleId", "triggerSource", "grillStatus",
    "commonUnderstandingConfirmed", "confirmationSource", "designHash",
    "summaryHash", "planHash", "attemptRef", "issuedAt", "expiresAt",
    "nonce", "attestationHash"
  ],
  "properties": {
    "schemaVersion": {"const": 3},
    "moduleId": {"const": "design-grill-me"},
    "triggerSource": {"enum": ["automatic-deep", "explicit-user-request"]},
    "grillStatus": {"const": "completed"},
    "commonUnderstandingConfirmed": {"const": true},
    "confirmationSource": {"const": "user-confirmation"},
    "designHash": {"$ref": "#/$defs/hash"},
    "summaryHash": {"$ref": "#/$defs/hash"},
    "planHash": {"$ref": "#/$defs/hash"},
    "attemptRef": {"$ref": "#/$defs/id"},
    "issuedAt": {"type": "string", "format": "utc-date-time"},
    "expiresAt": {"type": "string", "format": "utc-date-time"},
    "nonce": {"$ref": "#/$defs/id"},
    "attestationHash": {"$ref": "#/$defs/hash"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
