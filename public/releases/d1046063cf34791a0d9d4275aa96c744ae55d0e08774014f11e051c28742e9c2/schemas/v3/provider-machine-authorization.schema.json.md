# 只读参考：provider-machine-authorization.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/provider-machine-authorization.schema.json",
  "title": "SelfWorkFlow V3 machine Provider authorization",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "authorizationHash", "providerId", "canonicalProjectRootHash", "subjectKind", "operationId", "sideEffectClass", "executionNonce", "attemptRef", "issuedAt", "expiresAt", "nonce", "issuerId", "confirmationSource", "revocationState"],
  "properties": {
    "schemaVersion": {"const": 3},
    "authorizationHash": {"$ref": "#/$defs/hash"},
    "providerId": {"$ref": "#/$defs/id"},
    "canonicalProjectRootHash": {"$ref": "#/$defs/hash"},
    "subjectKind": {"enum": ["operation-plan", "query-plan"]},
    "operationId": {"$ref": "#/$defs/id"},
    "sideEffectClass": {"enum": ["local-write", "network"]},
    "executionNonce": {"$ref": "#/$defs/id"},
    "attemptRef": {"$ref": "#/$defs/id"},
    "issuedAt": {"type": "string", "format": "utc-date-time"},
    "expiresAt": {"type": "string", "format": "utc-date-time"},
    "nonce": {"$ref": "#/$defs/id"},
    "issuerId": {"$ref": "#/$defs/id"},
    "confirmationSource": {"enum": ["user-confirmation", "machine-policy", "test-fixture"]},
    "revocationState": {"enum": ["active", "revoked", "expired"]}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
