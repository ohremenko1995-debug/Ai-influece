"""Role-based access control: the role set, the permission set and the matrix."""

from app.shared.permissions.matrix import (
    AGENT_FORBIDDEN_PERMISSIONS,
    ROLE_PERMISSIONS,
    permissions_for_role,
    role_has_permission,
)
from app.shared.permissions.permissions import Permission
from app.shared.permissions.roles import ActorType, Role

__all__ = [
    "AGENT_FORBIDDEN_PERMISSIONS",
    "ROLE_PERMISSIONS",
    "ActorType",
    "Permission",
    "Role",
    "permissions_for_role",
    "role_has_permission",
]
