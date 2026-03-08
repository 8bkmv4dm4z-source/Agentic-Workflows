from __future__ import annotations

"""Deterministic review policies for deciding re-run vs end-of-run."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """Decision emitted by a reviewer policy."""

    action: str
    reasons: list[str]
    rerun_mission_ids: list[int]
    weighted_score: float | None
    changed_files: list[str]
    unmet_requirements: dict[int, dict[str, list[str]]] | None = None


class Reviewer(Protocol):
    """Contract for deterministic reviewer implementations."""

    name: str

    def decide(
        self,
        *,
        audit_report: dict[str, Any] | None,
        mission_reports: list[dict[str, Any]],
        derived_snapshot: dict[str, Any] | None,
        changed_files: list[str],
    ) -> ReviewDecision:
        ...


def _mission_ids_for_level(
    audit_report: dict[str, Any] | None,
    *,
    level: str,
) -> set[int]:
    if not audit_report:
        return set()
    ids: set[int] = set()
    for finding in audit_report.get("findings", []):
        if finding.get("level") != level:
            continue
        mission_id = finding.get("mission_id")
        if isinstance(mission_id, int) and mission_id > 0:
            ids.add(mission_id)
    return ids


class FailOnlyReviewer:
    """Stable policy: re-run only when there are fail findings."""

    name = "fail_only"

    def decide(
        self,
        *,
        audit_report: dict[str, Any] | None,
        mission_reports: list[dict[str, Any]],
        derived_snapshot: dict[str, Any] | None,
        changed_files: list[str],
    ) -> ReviewDecision:
        del mission_reports, derived_snapshot
        fail_ids = sorted(_mission_ids_for_level(audit_report, level="fail"))
        if fail_ids:
            return ReviewDecision(
                action="rerun",
                reasons=[f"fail findings detected for mission ids {fail_ids}"],
                rerun_mission_ids=fail_ids,
                weighted_score=None,
                changed_files=changed_files,
            )
        return ReviewDecision(
            action="end",
            reasons=["no fail findings detected"],
            rerun_mission_ids=[],
            weighted_score=None,
            changed_files=changed_files,
        )


class WeightedReviewer:
    """Conservative weighted policy for rerun decisions."""

    name = "weighted"

    def __init__(self, *, threshold: float = 0.35) -> None:
        self.threshold = threshold

    def decide(
        self,
        *,
        audit_report: dict[str, Any] | None,
        mission_reports: list[dict[str, Any]],
        derived_snapshot: dict[str, Any] | None,
        changed_files: list[str],
    ) -> ReviewDecision:
        fail_ids = sorted(_mission_ids_for_level(audit_report, level="fail"))
        if fail_ids:
            return ReviewDecision(
                action="rerun",
                reasons=[
                    f"hard fail override: fail findings detected for mission ids {fail_ids}"
                ],
                rerun_mission_ids=fail_ids,
                weighted_score=1.0,
                changed_files=changed_files,
            )

        mission_count = max(1, len(mission_reports))
        warn_ids = sorted(_mission_ids_for_level(audit_report, level="warn"))
        warn_ratio = len(warn_ids) / mission_count

        missing_subtasks = 0
        total_subtasks = 0
        file_required = 0
        file_missing = 0
        rerun_ids: set[int] = set(warn_ids)
        changed_set = set(changed_files)

        for mission in mission_reports:
            mission_id = mission.get("mission_id")
            if not isinstance(mission_id, int) or mission_id <= 0:
                continue

            subtask_statuses = mission.get("subtask_statuses", [])
            if isinstance(subtask_statuses, list):
                for status in subtask_statuses:
                    if not isinstance(status, dict):
                        continue
                    total_subtasks += 1
                    if not bool(status.get("satisfied", False)):
                        missing_subtasks += 1
                        rerun_ids.add(mission_id)

            required_files = mission.get("required_files", [])
            if isinstance(required_files, list):
                for required in required_files:
                    basename = str(required).replace("\\", "/").rsplit("/", 1)[-1]
                    if not basename:
                        continue
                    file_required += 1
                    if basename not in changed_set:
                        file_missing += 1
                        rerun_ids.add(mission_id)

            status = str(mission.get("status", "")).strip().lower()
            if status not in {"completed", ""}:
                rerun_ids.add(mission_id)

        subtask_gap = (missing_subtasks / total_subtasks) if total_subtasks else 0.0
        file_gap = (file_missing / file_required) if file_required else 0.0
        weighted_score = round((0.45 * warn_ratio) + (0.35 * subtask_gap) + (0.20 * file_gap), 3)

        reasons = [
            (
                "weighted factors "
                f"warn_ratio={warn_ratio:.3f} subtask_gap={subtask_gap:.3f} "
                f"file_gap={file_gap:.3f} threshold={self.threshold:.3f}"
            )
        ]
        if weighted_score >= self.threshold:
            reasons.append("weighted score met rerun threshold")
            action = "rerun"
        else:
            reasons.append("weighted score below rerun threshold")
            action = "end"

        return ReviewDecision(
            action=action,
            reasons=reasons,
            rerun_mission_ids=sorted(rerun_ids),
            weighted_score=weighted_score,
            changed_files=changed_files,
        )
