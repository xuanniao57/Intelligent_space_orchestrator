"""Unitree G1 action table and JSON sequence compiler for the PC2 bridge.

The central hub does not import or call Unitree SDK. It only maintains the
action table and compiles selected actions into DeviceCommand JSON that PC2
192.168.1.172 decodes into real SDK calls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class G1ArmAction:
    id: int
    name: str
    label: str
    meaning: str
    release_after: bool = False


G1_ARM_ACTION_TABLE: tuple[G1ArmAction, ...] = (
    G1ArmAction(0, "release arm", "释放手臂", "释放手臂/回到手臂释放状态"),
    G1ArmAction(1, "shake hand", "握手", "握手后释放手臂", True),
    G1ArmAction(2, "high five", "击掌", "击掌后释放手臂", True),
    G1ArmAction(3, "hug", "拥抱", "拥抱动作后释放手臂", True),
    G1ArmAction(4, "high wave", "高位挥手", "高位挥手"),
    G1ArmAction(5, "clap", "鼓掌", "鼓掌"),
    G1ArmAction(6, "face wave", "面前挥手", "面前挥手"),
    G1ArmAction(7, "left kiss", "左手飞吻", "左手飞吻"),
    G1ArmAction(8, "heart", "比心", "比心后释放手臂", True),
    G1ArmAction(9, "right heart", "右手比心", "右手比心后释放手臂", True),
    G1ArmAction(10, "hands up", "双手举起", "双手举起后释放手臂", True),
    G1ArmAction(11, "x-ray", "X-ray", "x-ray 动作后释放手臂", True),
    G1ArmAction(12, "right hand up", "右手举起", "右手举起后释放手臂", True),
    G1ArmAction(13, "reject", "拒绝", "拒绝动作后释放手臂", True),
    G1ArmAction(14, "right kiss", "右手飞吻", "右手飞吻"),
    G1ArmAction(15, "two-hand kiss", "双手飞吻", "双手飞吻"),
)

G1_TEST_ACTIONS_10: tuple[str, ...] = (
    "release arm",
    "shake hand",
    "high five",
    "high wave",
    "clap",
    "face wave",
    "heart",
    "right heart",
    "hands up",
    "right hand up",
)

_ACTION_BY_ID = {action.id: action for action in G1_ARM_ACTION_TABLE}
_ACTION_BY_NAME = {action.name: action for action in G1_ARM_ACTION_TABLE}


def list_g1_actions() -> list[dict[str, Any]]:
    return [asdict(action) for action in G1_ARM_ACTION_TABLE]


def resolve_g1_action(action: str | int | Mapping[str, Any]) -> G1ArmAction:
    if isinstance(action, Mapping):
        raw = action.get("action_id", action.get("id", action.get("action_name", action.get("name"))))
    else:
        raw = action
    if isinstance(raw, int) or str(raw).strip().isdigit():
        action_id = int(raw)
        if action_id in _ACTION_BY_ID:
            return _ACTION_BY_ID[action_id]
        raise KeyError(f"unknown G1 action id: {raw}")
    name = str(raw or "").strip().lower().replace("_", " ")
    if name in _ACTION_BY_NAME:
        return _ACTION_BY_NAME[name]
    raise KeyError(f"unknown G1 action name: {raw}")


def planned_g1_steps(actions: Sequence[G1ArmAction], *, release_after_sec: float = 2.0) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for action in actions:
        steps.append({
            "client": "G1ArmActionClient",
            "method": "ExecuteAction",
            "action_id": action.id,
            "action_name": action.name,
        })
        if action.release_after and release_after_sec > 0:
            steps.append({"client": "BridgeRuntime", "method": "Sleep", "seconds": release_after_sec})
            steps.append({
                "client": "G1ArmActionClient",
                "method": "ExecuteAction",
                "action_id": 0,
                "action_name": "release arm",
                "auto_release": True,
            })
    return [{"seq": index, **step} for index, step in enumerate(steps, start=1)]
