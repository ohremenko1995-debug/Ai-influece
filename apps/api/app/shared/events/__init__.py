"""Domain action vocabulary.

Audit rows are only useful if the `action` column is a closed set. Free-text
action names drift ("influencer.update" vs "influencer_updated") and make the
audit log unqueryable, so every writer passes a `DomainAction` member.
"""

from app.shared.events.actions import DomainAction

__all__ = ["DomainAction"]
