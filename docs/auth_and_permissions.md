# UAE v3 — Auth and Permissions

## Authentication Methods

### 1. JWT Bearer Tokens (Human Users)

```http
Authorization: Bearer <jwt>
```

Issue tokens via:
```python
from core.auth.jwt_service import get_jwt_service
from core.auth.roles import Role

svc = get_jwt_service()
token = svc.issue_token("user-id", Role.REVIEWER, node_id="my-node")
```

Token lifetime: `UAE_JWT_TTL_SECS` (default: 3600 seconds)

### 2. API Keys (Service Accounts)

```http
X-API-Key: <raw-key>
```

Configure via `UAE_API_KEYS` environment variable:
```json
[
  {"key": "my-admin-key", "role": "admin", "name": "admin-account"},
  {"key": "fed-key", "role": "federation_node", "name": "node-b", "node_id": "node-b-id"}
]
```

### Development Mode

Set `UAE_AUTH_ENABLED=false` to bypass all auth (dev/test only).
All requests get admin context. Never use in production.

## Roles

| Role | Level | Description |
|------|-------|-------------|
| `read_only` | 0 | Read-only access to all non-sensitive data |
| `auditor` | 1 | read_only + audit report generation |
| `reviewer` | 2 | auditor + claim verification and attestations |
| `issuer` | 3 | reviewer + credential issuance |
| `curriculum_operator` | 4 | issuer + course creation and publishing |
| `admin` | 5 | Full access to all operations |
| `federation_node` | peer | Service account for inter-node transport |

## Permission Matrix (Key Operations)

| Operation | Minimum Role |
|-----------|-------------|
| Read sources/claims/courses | read_only |
| Create claims | reviewer |
| Verify claims | reviewer |
| Issue credentials | issuer |
| Publish courses | curriculum_operator |
| Register nodes | admin |
| Manage API keys | admin |
| Receive federation transport | federation_node |

## Using Auth in Route Handlers

```python
from api.dependencies.auth import require_permission
from fastapi import Depends

@router.post("/claims/{id}/verify")
async def verify_claim(
    id: str,
    auth = Depends(require_permission("claims:verify")),
    db = Depends(get_async_session),
):
    # auth.user_id, auth.role, auth.node_id available
    ...
```

## Federation Node Auth

Federation nodes authenticate with an API key of role `federation_node`.
They are authorized for `federation:transport:receive` and `federation:transport:handshake`.
They are NOT automatically authorized for admin operations.
