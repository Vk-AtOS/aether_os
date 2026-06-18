"""
Aether-One Approvals Core

Enterprise-grade, offline, deterministic approval engine.

Responsibilities:
- Persist approval tickets to a SQLite database scoped to the project.
- Track ticket status over time:
    - PENDING
    - APPROVED
    - DENIED
- Record every action taken on a ticket:
    - who acted (actor)
    - what they did (APPROVE, DENY, COMMENT)
    - when they did it (UTC timestamp)
    - optional comment / justification

This module does NOT:
- Provide HTTP endpoints or CLI commands (those will call this layer).
- Make any network calls.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


TICKET_STATUS_PENDING = "PENDING"
TICKET_STATUS_APPROVED = "APPROVED"
TICKET_STATUS_DENIED = "DENIED"

ACTION_APPROVE = "APPROVE"
ACTION_DENY = "DENY"
ACTION_COMMENT = "COMMENT"

VALID_STATUSES = {TICKET_STATUS_PENDING, TICKET_STATUS_APPROVED, TICKET_STATUS_DENIED}
VALID_ACTIONS = {ACTION_APPROVE, ACTION_DENY, ACTION_COMMENT}


def _utc_now_iso() -> str:
    """
    Return current UTC time as ISO-8601 string with Z suffix.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ApprovalTicket:
    """
    A single approval ticket representing a requested operation.

    Attributes:
        id:
            Integer primary key from the database.

        created_at:
            UTC timestamp (ISO-8601) when the ticket was created.

        updated_at:
            UTC timestamp when the ticket was last updated.

        status:
            PENDING / APPROVED / DENIED.

        operation_type:
            Aether-One operation identifier (e.g. "guarded_python_fix").

        risk_level:
            Risk level string (LOW/MEDIUM/HIGH) for logging/audit.

        requester:
            Identifier for the entity/user that requested the operation
            (e.g. email, username, or "local-dev").

        summary:
            Short human-readable summary of what is being requested.

        payload_json:
            JSON string with structured payload describing the operation.
            (E.g. file paths, diff summary, etc.)
    """
    id: int
    created_at: str
    updated_at: str
    status: str
    operation_type: str
    risk_level: str
    requester: str
    summary: str
    payload_json: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        try:
            data["payload"] = json.loads(self.payload_json)
        except Exception as exc:
            logger.debug("ApprovalTicket.to_dict: payload_json parse failed: %s", exc)
            data["payload"] = None
        return data


@dataclass
class ApprovalAction:
    """
    A single action taken on a ticket.

    Attributes:
        id:
            Integer primary key from the database.

        ticket_id:
            Foreign key referencing approvals_ticket(id).

        created_at:
            UTC timestamp when the action was recorded.

        actor:
            Identifier of the human / system that performed the action.

        action:
            APPROVE / DENY / COMMENT.

        comment:
            Optional textual comment / justification.
    """
    id: int
    ticket_id: int
    created_at: str
    actor: str
    action: str
    comment: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ApprovalsStore:
    """
    SQLite-backed store for approvals.

    This class is safe to use in a single-process, single-threaded context,
    which is the typical case for an Aether-One backend instance.

    DB schema (created on first use):

        CREATE TABLE IF NOT EXISTS approvals_ticket (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            requester TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS approvals_action (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            FOREIGN KEY(ticket_id) REFERENCES approvals_ticket(id)
        );

    """

    def __init__(self, project_root: str, db_name: str = ".aetherone_approvals.db") -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        os.makedirs(self.project_root, exist_ok=True)
        self.db_path = os.path.join(self.project_root, db_name)
        self._conn = sqlite3.connect(self.db_path)
        # Return rows as tuples; we map them manually.
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals_ticket (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                requester TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals_action (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                comment TEXT,
                FOREIGN KEY(ticket_id) REFERENCES approvals_ticket(id)
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception as exc:
            logger.debug("ApprovalsStore.close: error closing DB connection: %s", exc)

    # ------------------------------------------------------------------
    # Ticket helpers
    # ------------------------------------------------------------------

    def _row_to_ticket(self, row: Sequence[Any]) -> ApprovalTicket:
        return ApprovalTicket(
            id=row[0],
            created_at=row[1],
            updated_at=row[2],
            status=row[3],
            operation_type=row[4],
            risk_level=row[5],
            requester=row[6],
            summary=row[7],
            payload_json=row[8],
        )

    def _row_to_action(self, row: Sequence[Any]) -> ApprovalAction:
        return ApprovalAction(
            id=row[0],
            ticket_id=row[1],
            created_at=row[2],
            actor=row[3],
            action=row[4],
            comment=row[5],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_ticket(
        self,
        operation_type: str,
        risk_level: str,
        requester: str,
        summary: str,
        payload: Dict[str, Any],
        initial_status: str = TICKET_STATUS_PENDING,
    ) -> ApprovalTicket:
        """
        Create a new ticket and insert it into the database.

        Returns the created ApprovalTicket.
        """
        status = initial_status.strip().upper()
        if status not in VALID_STATUSES:
            status = TICKET_STATUS_PENDING

        created_at = _utc_now_iso()
        updated_at = created_at
        payload_json = json.dumps(payload, separators=(",", ":"))

        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO approvals_ticket (
                created_at, updated_at, status,
                operation_type, risk_level, requester,
                summary, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                updated_at,
                status,
                operation_type,
                risk_level,
                requester,
                summary,
                payload_json,
            ),
        )
        ticket_id = cur.lastrowid
        self._conn.commit()

        return ApprovalTicket(
            id=ticket_id,
            created_at=created_at,
            updated_at=updated_at,
            status=status,
            operation_type=operation_type,
            risk_level=risk_level,
            requester=requester,
            summary=summary,
            payload_json=payload_json,
        )

    def get_ticket(self, ticket_id: int) -> Optional[ApprovalTicket]:
        """
        Fetch a ticket by ID. Returns None if not found.
        """
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, created_at, updated_at, status,
                   operation_type, risk_level, requester,
                   summary, payload_json
            FROM approvals_ticket
            WHERE id = ?
            """,
            (ticket_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_ticket(row)

    def list_tickets(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ApprovalTicket]:
        """
        List tickets, optionally filtered by status.
        """
        cur = self._conn.cursor()
        if status:
            s = status.strip().upper()
            cur.execute(
                """
                SELECT id, created_at, updated_at, status,
                       operation_type, risk_level, requester,
                       summary, payload_json
                FROM approvals_ticket
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (s, limit, offset),
            )
        else:
            cur.execute(
                """
                SELECT id, created_at, updated_at, status,
                       operation_type, risk_level, requester,
                       summary, payload_json
                FROM approvals_ticket
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        rows = cur.fetchall()
        return [self._row_to_ticket(r) for r in rows]

    def list_actions_for_ticket(self, ticket_id: int) -> List[ApprovalAction]:
        """
        Return all actions recorded for a given ticket, ordered by created_at.
        """
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, ticket_id, created_at, actor, action, comment
            FROM approvals_action
            WHERE ticket_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (ticket_id,),
        )
        rows = cur.fetchall()
        return [self._row_to_action(r) for r in rows]

    def add_action(
        self,
        ticket_id: int,
        actor: str,
        action: str,
        comment: Optional[str] = None,
        new_status: Optional[str] = None,
    ) -> Tuple[Optional[ApprovalAction], Optional[ApprovalTicket]]:
        """
        Record an action on a ticket and optionally update its status.

        Parameters:
            ticket_id:
                ID of the ticket to act on.

            actor:
                Identifier for the actor performing the action.

            action:
                APPROVE / DENY / COMMENT.

            comment:
                Optional comment or justification.

            new_status:
                Optional explicit new status. If not provided:
                    - APPROVE -> APPROVED
                    - DENY    -> DENIED
                    - COMMENT -> no status change

        Returns:
            (ApprovalAction or None, Updated ApprovalTicket or None)

        If the ticket does not exist, returns (None, None).
        """
        # Check ticket exists
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            return None, None

        act = action.strip().upper()
        if act not in VALID_ACTIONS:
            act = ACTION_COMMENT

        status_to_set: Optional[str] = None
        if new_status is not None:
            ns = new_status.strip().upper()
            if ns in VALID_STATUSES:
                status_to_set = ns
        else:
            if act == ACTION_APPROVE:
                status_to_set = TICKET_STATUS_APPROVED
            elif act == ACTION_DENY:
                status_to_set = TICKET_STATUS_DENIED

        created_at = _utc_now_iso()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO approvals_action (
                ticket_id, created_at, actor, action, comment
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, created_at, actor, act, comment),
        )
        action_id = cur.lastrowid

        if status_to_set is not None:
            updated_at = created_at
            cur.execute(
                """
                UPDATE approvals_ticket
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status_to_set, updated_at, ticket_id),
            )
            self._conn.commit()
            ticket = self.get_ticket(ticket_id)  # reload
        else:
            self._conn.commit()
            # ticket unchanged; we reload anyway for consistency
            ticket = self.get_ticket(ticket_id)

        action_obj = ApprovalAction(
            id=action_id,
            ticket_id=ticket_id,
            created_at=created_at,
            actor=actor,
            action=act,
            comment=comment,
        )
        return action_obj, ticket

