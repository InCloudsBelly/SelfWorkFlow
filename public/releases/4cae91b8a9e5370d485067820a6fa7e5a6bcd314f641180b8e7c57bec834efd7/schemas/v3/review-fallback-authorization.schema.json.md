# 只读参考：review-fallback-authorization.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/review-fallback-authorization.schema.json",
  "title": "SelfWorkFlow V3 review fallback authorization",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "designHash", "reviewerPolicyHash", "planHash", "attemptRef", "inputSummaryHash", "reason", "fallbackMode", "confirmationSource", "issuedAt", "expiresAt", "nonce", "revocationState", "authorizationHash"],
  "properties": {
    "schemaVersion": {"const": 3},
    "designHash": {"$ref": "#/$defs/hash"},
    "reviewerPolicyHash": {"$ref": "#/$defs/hash"},
    "planHash": {"$ref": "#/$defs/hash"},
    "attemptRef": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "inputSummaryHash": {"$ref": "#/$defs/hash"},
    "reason": {"enum": ["host-attestation-unavailable", "independent-context-unavailable"]},
    "fallbackMode": {"enum": ["independent-context-without-attestation", "same-agent-structured-review"]},
    "confirmationSource": {"const": "user-confirmation"},
    "issuedAt": {"type": "string", "format": "utc-date-time"},
    "expiresAt": {"type": "string", "format": "utc-date-time"},
    "nonce": {"type": "string", "minLength": 1, "maxLength": 256},
    "revocationState": {"enum": ["active", "revoked"]},
    "authorizationHash": {"$ref": "#/$defs/hash"}
  },
  "allOf": [
    {
      "if": {"properties": {"fallbackMode": {"const": "independent-context-without-attestation"}}, "required": ["fallbackMode"]},
      "then": {"properties": {"reason": {"const": "host-attestation-unavailable"}}}
    },
    {
      "if": {"properties": {"fallbackMode": {"const": "same-agent-structured-review"}}, "required": ["fallbackMode"]},
      "then": {"properties": {"reason": {"const": "independent-context-unavailable"}}}
    }
  ],
  "$defs": {"hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}}
}

````
