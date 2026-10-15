"""Graph schema: labels, relationship types and allowed values (contract file, frozen).

Source of truth: docs/LLD.md §4.1 (labels and properties) and docs/ARCHITECTURE.md §4
(relationships). Nobody types a label, relationship type or status as a plain string
anywhere else; import it from here. Changing this file is a contract change: tell all
three workstreams first and bump SCHEMA_VERSION.

Every tenant has its own graph with this same schema (see core/tenant_registry.py).
"""

from enum import StrEnum

SCHEMA_VERSION = 1


class Label(StrEnum):
    # Environment: seeded by B from data/inventory/
    HOST = "Host"
    USER = "User"
    SERVICE = "Service"
    ENDPOINT = "Endpoint"
    ASSET_TAG = "AssetTag"
    # Activity: written by the ingestor (A)
    ALERT = "Alert"
    IOC = "IOC"
    TECHNIQUE = "Technique"
    # Memory: written by the agents (A) and the API (C)
    CASE = "Case"
    DECISION = "Decision"
    FEEDBACK = "Feedback"
    PLAYBOOK = "Playbook"
    AGENT_RUN = "AgentRun"


# The properties that identify one node of each label (what MERGE matches on).
NODE_KEYS: dict[Label, tuple[str, ...]] = {
    Label.HOST: ("hostname",),
    Label.USER: ("username",),
    Label.SERVICE: ("name",),
    Label.ENDPOINT: ("path", "app"),
    Label.ASSET_TAG: ("name",),
    Label.ALERT: ("incident_id",),
    Label.IOC: ("type", "value"),
    Label.TECHNIQUE: ("mitre_id",),
    Label.CASE: ("id",),
    Label.DECISION: ("id",),
    Label.FEEDBACK: ("id",),
    Label.PLAYBOOK: ("name", "version"),
    Label.AGENT_RUN: ("id",),
}


class Rel(StrEnum):
    # Environment
    LOGGED_INTO = "LOGGED_INTO"  # carries last_seen
    CONNECTS_TO = "CONNECTS_TO"  # carries port
    RUNS = "RUNS"
    SERVED_BY = "SERVED_BY"
    TAGGED = "TAGGED"
    # Activity
    ON_HOST = "ON_HOST"
    INVOLVES = "INVOLVES"
    TARGETED = "TARGETED"
    MAPS_TO = "MAPS_TO"
    # Memory
    CONTAINS = "CONTAINS"
    HAS_DECISION = "HAS_DECISION"
    ACTED_ON = "ACTED_ON"
    ON = "ON"
    LEARNED_FROM = "LEARNED_FROM"
    WROTE = "WROTE"
    HANDED_OFF_TO = "HANDED_OFF_TO"
    # A playbook that closed a case or drove a decision. Not drawn in ARCHITECTURE.md §4;
    # needed by close_case_auto and explain_decision (Q6) to cite the playbook.
    APPLIED = "APPLIED"


# Every allowed (from label, relationship, to label). Writes use only these.
EDGES: frozenset[tuple[Label, Rel, Label]] = frozenset(
    {
        (Label.USER, Rel.LOGGED_INTO, Label.HOST),
        (Label.HOST, Rel.CONNECTS_TO, Label.HOST),
        (Label.HOST, Rel.RUNS, Label.SERVICE),
        (Label.ENDPOINT, Rel.SERVED_BY, Label.HOST),
        (Label.HOST, Rel.TAGGED, Label.ASSET_TAG),
        (Label.ALERT, Rel.ON_HOST, Label.HOST),
        (Label.ALERT, Rel.INVOLVES, Label.USER),
        (Label.ALERT, Rel.INVOLVES, Label.IOC),
        (Label.ALERT, Rel.TARGETED, Label.ENDPOINT),
        (Label.ALERT, Rel.MAPS_TO, Label.TECHNIQUE),
        (Label.CASE, Rel.CONTAINS, Label.ALERT),
        (Label.CASE, Rel.HAS_DECISION, Label.DECISION),
        (Label.DECISION, Rel.ACTED_ON, Label.HOST),
        (Label.DECISION, Rel.ACTED_ON, Label.USER),
        (Label.DECISION, Rel.ACTED_ON, Label.IOC),
        (Label.FEEDBACK, Rel.ON, Label.CASE),
        (Label.PLAYBOOK, Rel.LEARNED_FROM, Label.FEEDBACK),
        (Label.AGENT_RUN, Rel.WROTE, Label.CASE),
        (Label.AGENT_RUN, Rel.WROTE, Label.DECISION),
        (Label.AGENT_RUN, Rel.HANDED_OFF_TO, Label.AGENT_RUN),
        (Label.CASE, Rel.APPLIED, Label.PLAYBOOK),
        (Label.DECISION, Rel.APPLIED, Label.PLAYBOOK),
    }
)


class CaseStatus(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    INVESTIGATED = "investigated"
    AWAITING_APPROVAL = "awaiting_approval"
    CLOSED = "closed"
    AUTO_CLOSED = "auto_closed"


# The names the LLD uses, e.g. `claim_case(tenant, TRIAGED, ...)`.
NEW = CaseStatus.NEW
TRIAGED = CaseStatus.TRIAGED
INVESTIGATED = CaseStatus.INVESTIGATED
AWAITING_APPROVAL = CaseStatus.AWAITING_APPROVAL
CLOSED = CaseStatus.CLOSED
AUTO_CLOSED = CaseStatus.AUTO_CLOSED

OPEN_CASE_STATUSES = frozenset(
    {CaseStatus.NEW, CaseStatus.TRIAGED, CaseStatus.INVESTIGATED, CaseStatus.AWAITING_APPROVAL}
)


class Priority(StrEnum):
    """Case priority; order matters: info < low < medium < high < critical (LLD §6.2)."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


PRIORITY_ORDER: tuple[Priority, ...] = tuple(Priority)


class AlertStatus(StrEnum):
    NEW = "new"  # ingested, not yet in a case
    CASED = "cased"


class Zone(StrEnum):
    DMZ = "dmz"
    APP = "app"
    DATA = "data"
    CORP = "corp"


CRITICALITY_MIN, CRITICALITY_MAX = 1, 5
CROWN_JEWEL_TAG = "crown-jewel"


class IocType(StrEnum):
    IP = "ip"
    DOMAIN = "domain"
    URL = "url"
    HASH = "hash"


class IocVerdict(StrEnum):
    UNKNOWN = "unknown"
    MALICIOUS = "malicious"
    BENIGN = "benign"


class FeedbackVerdict(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    BENIGN = "benign"


class DecisionOutcome(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO = "auto"


class AgentName(StrEnum):
    TRIAGE = "triage"
    INVESTIGATOR = "investigator"
    RESPONDER = "responder"


class PlaybookAction(StrEnum):
    AUTO_CLOSE = "auto_close"
