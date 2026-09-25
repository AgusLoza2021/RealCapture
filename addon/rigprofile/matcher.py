"""Auto-matching engine: propose bindings from a rig's shape keys and bones.

Workflow (Rokoko-style, implemented from scratch): standardize candidate
names, split sides, compare against side-neutral alias stems, and assign
best-first one-to-one so two channels never claim the same control. Every
proposal carries a confidence and a reason; the wizard UI is the reviewer —
nothing is applied blindly.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import channels as ch
from . import naming
from .aliases import BONE_ALIASES, SHAPE_ALIASES

CONF_EXACT = 1.0
CONF_ALIAS = 0.85
CONF_SEGMENT = 0.5
CONF_SIDE_PENALTY = 0.35  # unsided candidate serving a sided channel
_MIN_STEM_LEN = 4        # min length for prefix-containment scoring


@dataclass
class Proposal:
    key: str            # ARKit channel (shapekey match) or point role (bone match)
    kind: str           # "shapekey" | "bone"
    target: str         # control name in the rig
    confidence: float
    reason: str         # "exact" | "alias" | "segment"

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.key} -> {self.target} ({self.confidence:.2f}, {self.reason})"


def match_shapekeys(shape_key_names: list[str]) -> list[Proposal]:
    """Match ARKit channels against mesh shape key names."""
    candidates = [(name, *_split(name)) for name in shape_key_names]
    wanted = [(channel, ch.channel_base(channel), ch.channel_side(channel))
              for channel in ch.ARKIT_CHANNELS]
    pairs = _score_pairs(wanted, candidates, SHAPE_ALIASES)
    return _assign(pairs, kind="shapekey")


def match_bones(bone_names: list[str]) -> list[Proposal]:
    """Match FPD point roles (and their follower bones) against armature bones."""
    candidates = [(name, *_split(name)) for name in bone_names]
    wanted: list[tuple[str, str, str | None]] = []
    for role in ch.point_roles():
        if role.endswith((".L", ".R")):
            wanted.append((role, role[:-2], role[-1]))
        else:
            wanted.append((role, role, None))
    pairs = _score_pairs(wanted, candidates, BONE_ALIASES)
    return _assign(pairs, kind="bone")


def _split(name: str) -> tuple[str, str | None]:
    base, side = naming.split_side(name)
    return base.replace("_", ""), side


def _score_pairs(
    wanted: list[tuple[str, str, str | None]],
    candidates: list[tuple[str, str, str | None]],
    alias_map: dict[str, tuple[str, ...]],
) -> list[tuple[float, str, str, str]]:
    """Score every (key, candidate) pair; return (confidence, key, target, reason)."""
    scored: list[tuple[float, str, str, str]] = []
    for key, key_base, key_side in wanted:
        stems = {key_base} | set(alias_map.get(key_base, ()))
        stems = {s.replace("_", "") for s in stems}
        for target, cand_base, cand_side in candidates:
            side_penalty = 0.0
            if key_side and cand_side and cand_side != key_side:
                continue  # wrong side: never a match
            if key_side and cand_side is None:
                side_penalty = CONF_SIDE_PENALTY  # unsided "blink" can serve both eyes
            if cand_base == key_base:
                scored.append((CONF_EXACT - side_penalty, key, target, "exact"))
            elif cand_base in stems:
                scored.append((CONF_ALIAS - side_penalty, key, target, "alias"))
            elif _stem_prefix_match(cand_base, stems):
                # Rigify-style fragments: "eyelidt" (eyelid.T) for "eyelid".
                scored.append((CONF_SEGMENT - side_penalty, key, target, "segment"))
            else:
                shared = _shared_segments(key_base, cand_base)
                if shared >= 1:
                    score = CONF_SEGMENT * (shared / max(1, len(key_base.split("_"))))
                    scored.append((score - side_penalty, key, target, "segment"))
    return scored


def _stem_prefix_match(cand_base: str, stems: set[str]) -> bool:
    """True when the candidate is a prefix of (or extends) a known stem."""
    if len(cand_base) < _MIN_STEM_LEN:
        return False
    for stem in stems:
        if len(stem) < _MIN_STEM_LEN:
            continue
        if stem.startswith(cand_base) or cand_base.startswith(stem):
            return True
    return False


def _shared_segments(key_base: str, cand_base: str) -> int:
    """Count key segments found as whole underscore-separated parts of the candidate."""
    key_parts = key_base.split("_")
    cand_parts = set(cand_base.split("_"))
    return sum(1 for part in key_parts if part in cand_parts)


def _assign(
    pairs: list[tuple[float, str, str, str]], kind: str
) -> list[Proposal]:
    """Greedy best-first one-to-one assignment."""
    proposals: list[Proposal] = []
    used_keys: set[str] = set()
    used_targets: set[str] = set()
    for confidence, key, target, reason in sorted(pairs, reverse=True):
        if key in used_keys or target in used_targets or confidence <= 0:
            continue
        used_keys.add(key)
        used_targets.add(target)
        proposals.append(Proposal(key=key, kind=kind, target=target,
                                  confidence=confidence, reason=reason))
    proposals.sort(key=lambda p: p.key)
    return proposals
