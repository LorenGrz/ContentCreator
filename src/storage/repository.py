"""Thin DynamoDB access layer. All domain code goes through this class so the
key scheme lives in exactly one place and tests can drive it with ``moto``.

No GSI: at this scale (one user, a handful of drafts/day) every read is a
``Query`` on a single ``DATE#`` partition, or a short loop over recent dates.
"""

from __future__ import annotations

from datetime import date, timedelta

from boto3.dynamodb.conditions import Key

from config import TABLE_NAME
from storage.models import Draft, Signal, date_pk


class Repository:
    def __init__(self, table=None):
        if table is None:
            import boto3

            table = boto3.resource("dynamodb").Table(TABLE_NAME)
        self._table = table

    # --- Signals -------------------------------------------------------

    def put_signal(self, signal: Signal) -> None:
        self._table.put_item(Item=signal.to_item())

    def list_signals_for_date(self, activity_date: str) -> list[Signal]:
        resp = self._table.query(
            KeyConditionExpression=Key("pk").eq(date_pk(activity_date))
            & Key("sk").begins_with("SIGNAL#")
        )
        return [Signal.from_item(i) for i in resp.get("Items", [])]

    # --- Drafts -------------------------------------------------------

    def put_draft(self, draft: Draft) -> None:
        self._table.put_item(Item=draft.to_item())

    def get_draft(self, target_date: str, sk: str) -> Draft | None:
        resp = self._table.get_item(Key={"pk": date_pk(target_date), "sk": sk})
        item = resp.get("Item")
        return Draft.from_item(item) if item else None

    def list_drafts_for_date(self, target_date: str) -> list[Draft]:
        resp = self._table.query(
            KeyConditionExpression=Key("pk").eq(date_pk(target_date))
            & Key("sk").begins_with("DRAFT#")
        )
        return [Draft.from_item(i) for i in resp.get("Items", [])]

    def list_recent_drafts(self, reference_date: str, days: int) -> list[Draft]:
        """Every draft on ``[reference_date - days + 1, reference_date]``."""
        ref = date.fromisoformat(reference_date)
        out: list[Draft] = []
        for offset in range(days):
            day = (ref - timedelta(days=offset)).isoformat()
            out.extend(self.list_drafts_for_date(day))
        return out

    def recent_topic_tags(self, reference_date: str, days: int) -> list[str]:
        seen: dict[str, None] = {}
        for draft in self.list_recent_drafts(reference_date, days):
            for tag in draft.topic_tags:
                seen.setdefault(tag, None)
        return list(seen)

    def update_draft_status(
        self, target_date: str, sk: str, status: str, decided_at: str
    ) -> Draft | None:
        """Idempotent decision write: only flips a still-``pending`` draft, so a
        double-tap on the Telegram button can't overwrite the first decision."""
        from botocore.exceptions import ClientError

        try:
            resp = self._table.update_item(
                Key={"pk": date_pk(target_date), "sk": sk},
                UpdateExpression="SET #s = :new, decided_at = :d",
                ConditionExpression="attribute_exists(pk) AND #s = :pending",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":new": status,
                    ":d": decided_at,
                    ":pending": "pending",
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return self.get_draft(target_date, sk)
            raise
        return Draft.from_item(resp["Attributes"])

    def update_draft_content(
        self, target_date: str, sk: str, content: str, edited_at: str
    ) -> Draft | None:
        """Overwrite a draft's text (used by the Telegram edit flow). Returns
        ``None`` if the draft no longer exists."""
        from botocore.exceptions import ClientError

        try:
            resp = self._table.update_item(
                Key={"pk": date_pk(target_date), "sk": sk},
                UpdateExpression="SET content = :c, edited_at = :e",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={":c": content, ":e": edited_at},
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return Draft.from_item(resp["Attributes"])

    # --- Per-chat conversation state (Telegram edit flow) -------------

    @staticmethod
    def _chat_key(chat_id: str) -> dict:
        return {"pk": f"CHAT#{chat_id}", "sk": "STATE"}

    def get_chat_state(self, chat_id: str) -> dict | None:
        resp = self._table.get_item(Key=self._chat_key(chat_id))
        return resp.get("Item")

    def set_chat_state(self, chat_id: str, **attrs) -> None:
        item = {**self._chat_key(chat_id), **attrs}
        self._table.put_item(Item=item)

    def clear_chat_state(self, chat_id: str) -> None:
        # Overwrite rather than delete: the execution role is scoped to
        # Put/Update/Get/Query only (no DeleteItem). ``_edit_session`` treats
        # any non-"awaiting_edit" mode as "no open session".
        self._table.put_item(Item={**self._chat_key(chat_id), "mode": "idle"})
