# 只读参考：design-review-summary-attestation.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/design-review-summary-attestation.schema.json",
  "title": "SelfWorkFlow V3 Host-attested design review summary provenance",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion", "summaryHash", "designHash", "reviewerPolicyHash",
    "planHash", "attemptRef", "sourceClasses", "sourceFields",
    "grillTranscriptReceived", "grillReasoningReceived", "parentContextReceived",
    "issuedAt", "expiresAt", "nonce", "attestationHash"
  ],
  "properties": {
    "schemaVersion": {"const": 3},
    "summaryHash": {"$ref": "#/$defs/hash"},
    "designHash": {"$ref": "#/$defs/hash"},
    "reviewerPolicyHash": {"$ref": "#/$defs/hash"},
    "planHash": {"$ref": "#/$defs/hash"},
    "attemptRef": {"$ref": "#/$defs/id"},
    "sourceClasses": {"const": ["acceptance-criteria", "confirmed-design"]},
    "sourceFields": {
      "const": [
        "acceptanceCriteria", "alternatives", "assumptions", "constraints",
        "objective", "risks", "scope.excluded", "scope.included"
      ]
    },
    "grillTranscriptReceived": {"const": false},
    "grillReasoningReceived": {"const": false},
    "parentContextReceived": {"const": false},
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
