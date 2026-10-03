"""integrity constraints, term snapshots, ticket units, restrict cascades

Revision ID: a1b2c3d4e5f6
Revises: 538fc085a8ba
Create Date: 2026-10-03 17:30:00.000000

Data reconciliation (authorized by prompt policy — derived state, not discarding entitlements):
- memberships.status = 'expired' → 'active'
  Effective expiry is now derived from ends_at; paid rows are preserved.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "538fc085a8ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _swap_fk(table: str, name: str, cols: list[str], ref_table: str, ref_cols: list[str]) -> None:
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, ref_table, cols, ref_cols, ondelete="RESTRICT")


def upgrade() -> None:
    # --- reconcile legacy membership statuses before check constraint ---
    op.execute(
        sa.text("UPDATE memberships SET status = 'active' WHERE status = 'expired'")
    )

    # --- order item term snapshots ---
    op.add_column("order_items", sa.Column("duration_days_snapshot", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("fixed_expires_on_snapshot", sa.Date(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE order_items AS oi
            SET duration_days_snapshot = mp.duration_days,
                fixed_expires_on_snapshot = mp.fixed_expires_on
            FROM membership_plans AS mp
            WHERE oi.item_kind = 'membership'
              AND oi.membership_plan_id = mp.id
              AND oi.duration_days_snapshot IS NULL
              AND oi.fixed_expires_on_snapshot IS NULL
            """
        )
    )

    # --- ticket unit identity ---
    op.add_column(
        "tickets",
        sa.Column("unit_index", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            WITH numbered AS (
              SELECT id, ROW_NUMBER() OVER (PARTITION BY order_item_id ORDER BY issued_at, id) - 1 AS idx
              FROM tickets
            )
            UPDATE tickets AS t
            SET unit_index = numbered.idx
            FROM numbered
            WHERE t.id = numbered.id
            """
        )
    )
    op.alter_column("tickets", "unit_index", nullable=False, server_default="0")
    op.create_unique_constraint("uq_tickets_item_unit", "tickets", ["order_item_id", "unit_index"])
    op.create_check_constraint("ck_tickets_unit_index_nonneg", "tickets", "unit_index >= 0")

    # widen sealed credential storage for Fernet blobs
    op.alter_column(
        "tickets",
        "qr_token_sealed",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=False,
    )

    # --- status / numeric check constraints ---
    op.create_check_constraint(
        "ck_orders_status",
        "orders",
        "status IN ('pending', 'paid', 'cancelled', 'refund_required')",
    )
    op.create_check_constraint(
        "ck_payments_status",
        "payments",
        "status IN ('pending', 'confirmed', 'failed', 'refund_required')",
    )
    op.create_check_constraint(
        "ck_order_items_kind",
        "order_items",
        "item_kind IN ('membership', 'ticket')",
    )
    op.create_check_constraint(
        "ck_order_items_quantity_positive",
        "order_items",
        "quantity >= 1",
    )
    op.create_check_constraint(
        "ck_order_items_membership_term_snapshot",
        "order_items",
        "(item_kind = 'ticket' AND duration_days_snapshot IS NULL AND fixed_expires_on_snapshot IS NULL) OR "
        "(item_kind = 'membership' AND ("
        "(duration_days_snapshot IS NOT NULL AND fixed_expires_on_snapshot IS NULL) OR "
        "(duration_days_snapshot IS NULL AND fixed_expires_on_snapshot IS NOT NULL)"
        "))",
    )
    op.create_check_constraint(
        "ck_order_items_duration_positive",
        "order_items",
        "duration_days_snapshot IS NULL OR duration_days_snapshot > 0",
    )
    op.create_check_constraint(
        "ck_membership_plans_duration_positive",
        "membership_plans",
        "duration_days IS NULL OR duration_days > 0",
    )
    op.create_check_constraint(
        "ck_memberships_status",
        "memberships",
        "status IN ('active', 'revoked')",
    )
    op.create_check_constraint(
        "ck_events_status",
        "events",
        "status IN ('draft', 'published', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_events_sales_window",
        "events",
        "sales_opens_at IS NULL OR sales_closes_at IS NULL OR sales_closes_at > sales_opens_at",
    )
    op.create_check_constraint(
        "ck_tickets_status",
        "tickets",
        "status IN ('valid', 'cancelled', 'refund_required', 'used')",
    )
    op.create_check_constraint(
        "ck_club_role_assignments_period",
        "club_role_assignments",
        "ends_at IS NULL OR ends_at > starts_at",
    )

    # --- prefer RESTRICT on purchase / entitlement history ---
    _swap_fk("orders", "orders_club_id_fkey", ["club_id"], "clubs", ["id"])
    _swap_fk("orders", "orders_user_id_fkey", ["user_id"], "users", ["id"])
    _swap_fk("order_items", "order_items_order_id_fkey", ["order_id"], "orders", ["id"])
    _swap_fk("payments", "payments_order_id_fkey", ["order_id"], "orders", ["id"])
    _swap_fk("payment_events", "payment_events_payment_id_fkey", ["payment_id"], "payments", ["id"])
    _swap_fk("membership_plans", "membership_plans_club_id_fkey", ["club_id"], "clubs", ["id"])
    _swap_fk("memberships", "memberships_club_id_fkey", ["club_id"], "clubs", ["id"])
    _swap_fk("memberships", "memberships_user_id_fkey", ["user_id"], "users", ["id"])
    _swap_fk("events", "events_club_id_fkey", ["club_id"], "clubs", ["id"])
    _swap_fk("ticket_types", "ticket_types_event_id_fkey", ["event_id"], "events", ["id"])
    _swap_fk("ticket_prices", "ticket_prices_ticket_type_id_fkey", ["ticket_type_id"], "ticket_types", ["id"])
    _swap_fk("tickets", "tickets_club_id_fkey", ["club_id"], "clubs", ["id"])
    _swap_fk("tickets", "tickets_event_id_fkey", ["event_id"], "events", ["id"])
    _swap_fk("tickets", "tickets_user_id_fkey", ["user_id"], "users", ["id"])
    _swap_fk("ticket_checkins", "ticket_checkins_event_id_fkey", ["event_id"], "events", ["id"])
    _swap_fk("ticket_checkins", "ticket_checkins_ticket_id_fkey", ["ticket_id"], "tickets", ["id"])

    # Keep denormalized ticket/check-in club/event/type fields for query performance;
    # enforce consistency with triggers instead of dropping the columns.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION campusos_enforce_ticket_consistency()
            RETURNS trigger AS $$
            DECLARE
              tt_event uuid;
              ev_club uuid;
              ord_user uuid;
              ord_club uuid;
            BEGIN
              SELECT event_id INTO tt_event FROM ticket_types WHERE id = NEW.ticket_type_id;
              IF tt_event IS NULL OR tt_event <> NEW.event_id THEN
                RAISE EXCEPTION 'cross_club_violation: ticket.event_id must match ticket_type.event_id';
              END IF;
              SELECT club_id INTO ev_club FROM events WHERE id = NEW.event_id;
              IF ev_club IS NULL OR ev_club <> NEW.club_id THEN
                RAISE EXCEPTION 'cross_club_violation: ticket.club_id must match event.club_id';
              END IF;
              SELECT o.user_id, o.club_id INTO ord_user, ord_club
              FROM order_items oi JOIN orders o ON o.id = oi.order_id
              WHERE oi.id = NEW.order_item_id;
              IF ord_user IS NULL OR ord_user <> NEW.user_id OR ord_club <> NEW.club_id THEN
                RAISE EXCEPTION 'cross_club_violation: ticket user/club must match order';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    # asyncpg rejects multi-statement prepared SQL — keep DROP/CREATE separate.
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_tickets_consistency ON tickets"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_tickets_consistency
            BEFORE INSERT OR UPDATE ON tickets
            FOR EACH ROW EXECUTE FUNCTION campusos_enforce_ticket_consistency();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION campusos_enforce_membership_consistency()
            RETURNS trigger AS $$
            DECLARE
              plan_club uuid;
              ord_club uuid;
              ord_user uuid;
            BEGIN
              SELECT club_id INTO plan_club FROM membership_plans WHERE id = NEW.plan_id;
              IF plan_club IS NULL OR plan_club <> NEW.club_id THEN
                RAISE EXCEPTION 'cross_club_violation: membership.club_id must match plan.club_id';
              END IF;
              SELECT o.club_id, o.user_id INTO ord_club, ord_user
              FROM order_items oi JOIN orders o ON o.id = oi.order_id
              WHERE oi.id = NEW.order_item_id;
              IF ord_club IS NULL OR ord_club <> NEW.club_id OR ord_user <> NEW.user_id THEN
                RAISE EXCEPTION 'cross_club_violation: membership must match order club/user';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_memberships_consistency ON memberships"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_memberships_consistency
            BEFORE INSERT OR UPDATE ON memberships
            FOR EACH ROW EXECUTE FUNCTION campusos_enforce_membership_consistency();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION campusos_enforce_checkin_consistency()
            RETURNS trigger AS $$
            DECLARE
              t_event uuid;
            BEGIN
              SELECT event_id INTO t_event FROM tickets WHERE id = NEW.ticket_id;
              IF t_event IS NULL OR t_event <> NEW.event_id THEN
                RAISE EXCEPTION 'cross_club_violation: check-in event must match ticket.event_id';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ticket_checkins_consistency ON ticket_checkins"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ticket_checkins_consistency
            BEFORE INSERT OR UPDATE ON ticket_checkins
            FOR EACH ROW EXECUTE FUNCTION campusos_enforce_checkin_consistency();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ticket_checkins_consistency ON ticket_checkins"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_memberships_consistency ON memberships"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_tickets_consistency ON tickets"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS campusos_enforce_checkin_consistency()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS campusos_enforce_membership_consistency()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS campusos_enforce_ticket_consistency()"))

    # Downgrade restores CASCADE (historical behavior) — destructive deletes return.
    for table, name, cols, ref in [
        ("ticket_checkins", "ticket_checkins_ticket_id_fkey", ["ticket_id"], "tickets"),
        ("ticket_checkins", "ticket_checkins_event_id_fkey", ["event_id"], "events"),
        ("tickets", "tickets_user_id_fkey", ["user_id"], "users"),
        ("tickets", "tickets_event_id_fkey", ["event_id"], "events"),
        ("tickets", "tickets_club_id_fkey", ["club_id"], "clubs"),
        ("ticket_prices", "ticket_prices_ticket_type_id_fkey", ["ticket_type_id"], "ticket_types"),
        ("ticket_types", "ticket_types_event_id_fkey", ["event_id"], "events"),
        ("events", "events_club_id_fkey", ["club_id"], "clubs"),
        ("memberships", "memberships_user_id_fkey", ["user_id"], "users"),
        ("memberships", "memberships_club_id_fkey", ["club_id"], "clubs"),
        ("membership_plans", "membership_plans_club_id_fkey", ["club_id"], "clubs"),
        ("payment_events", "payment_events_payment_id_fkey", ["payment_id"], "payments"),
        ("payments", "payments_order_id_fkey", ["order_id"], "orders"),
        ("order_items", "order_items_order_id_fkey", ["order_id"], "orders"),
        ("orders", "orders_user_id_fkey", ["user_id"], "users"),
        ("orders", "orders_club_id_fkey", ["club_id"], "clubs"),
    ]:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, ref, cols, ["id"], ondelete="CASCADE")

    for name, table in [
        ("ck_club_role_assignments_period", "club_role_assignments"),
        ("ck_tickets_status", "tickets"),
        ("ck_events_sales_window", "events"),
        ("ck_events_status", "events"),
        ("ck_memberships_status", "memberships"),
        ("ck_membership_plans_duration_positive", "membership_plans"),
        ("ck_order_items_duration_positive", "order_items"),
        ("ck_order_items_membership_term_snapshot", "order_items"),
        ("ck_order_items_quantity_positive", "order_items"),
        ("ck_order_items_kind", "order_items"),
        ("ck_payments_status", "payments"),
        ("ck_orders_status", "orders"),
        ("ck_tickets_unit_index_nonneg", "tickets"),
    ]:
        op.drop_constraint(name, table, type_="check")

    op.drop_constraint("uq_tickets_item_unit", "tickets", type_="unique")
    op.drop_column("tickets", "unit_index")
    op.alter_column(
        "tickets",
        "qr_token_sealed",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=False,
    )
    op.drop_column("order_items", "fixed_expires_on_snapshot")
    op.drop_column("order_items", "duration_days_snapshot")
