"""Single source of truth for role → permission mapping.

The frontend must render navigation from permissions returned by the API.
It must not redefine this policy independently.
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    MANAGE_PLANS = "manage_plans"
    MANAGE_MEMBERS = "manage_members"
    CONFIRM_DUES = "confirm_dues"
    MANAGE_EVENTS = "manage_events"
    CHECK_IN = "check_in"
    VIEW_ATTENDANCE = "view_attendance"
    MANAGE_ANNOUNCEMENTS = "manage_announcements"
    MANAGE_MAILING_LIST = "manage_mailing_list"
    MANAGE_ROLES = "manage_roles"
    VIEW_AUDIT = "view_audit"
    MANAGE_MERCHANDISE = "manage_merchandise"
    FULFILL_MERCHANDISE = "fulfill_merchandise"
    MANAGE_PROJECTS = "manage_projects"
    REVIEW_EXPENSES = "review_expenses"
    RECORD_REIMBURSEMENT = "record_reimbursement"
    MANAGE_BUDGETS = "manage_budgets"
    VIEW_FINANCE = "view_finance"
    RECORD_REFUNDS = "record_refunds"


class RoleCode(StrEnum):
    CLUB_ADMIN = "club_admin"
    MEMBERSHIP_MANAGER = "membership_manager"
    EVENT_ORGANIZER = "event_organizer"
    COMMUNICATIONS_OFFICER = "communications_officer"
    FINANCE_OFFICER = "finance_officer"


ROLE_PERMISSIONS: dict[RoleCode, frozenset[Permission]] = {
    RoleCode.CLUB_ADMIN: frozenset(Permission),
    RoleCode.MEMBERSHIP_MANAGER: frozenset(
        {
            Permission.MANAGE_MEMBERS,
            Permission.CONFIRM_DUES,
            Permission.MANAGE_PLANS,
        }
    ),
    RoleCode.EVENT_ORGANIZER: frozenset(
        {
            Permission.MANAGE_EVENTS,
            Permission.CHECK_IN,
            Permission.VIEW_ATTENDANCE,
            Permission.MANAGE_MERCHANDISE,
            Permission.FULFILL_MERCHANDISE,
            Permission.MANAGE_PROJECTS,
        }
    ),
    RoleCode.COMMUNICATIONS_OFFICER: frozenset(
        {
            Permission.MANAGE_ANNOUNCEMENTS,
            Permission.MANAGE_MAILING_LIST,
        }
    ),
    RoleCode.FINANCE_OFFICER: frozenset(
        {
            Permission.REVIEW_EXPENSES,
            Permission.RECORD_REIMBURSEMENT,
            Permission.MANAGE_BUDGETS,
            Permission.VIEW_FINANCE,
            Permission.RECORD_REFUNDS,
        }
    ),
}


def permissions_for_roles(role_codes: set[str]) -> list[str]:
    granted: set[Permission] = set()
    for code in role_codes:
        try:
            role = RoleCode(code)
        except ValueError:
            continue
        granted.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return sorted(p.value for p in granted)
