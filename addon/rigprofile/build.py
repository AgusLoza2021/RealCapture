"""Build a RigProfile from wizard proposals — pure logic, no bpy.

The wizard produces Proposal lists (from the matcher, possibly user-corrected)
plus a channel catalog (the packet schema channels actually streamed). This
module turns them into a complete profile: default point transforms for the
bound roles, shape key bindings, and bone bindings.
"""

from __future__ import annotations

from .channels import ARKIT_CHANNELS
from .defaults import default_point_transforms
from .matcher import Proposal
from .profile import BoneBinding, RigProfile, ShapeKeyBinding


def build_profile(
    name: str,
    shapekey_proposals: list[Proposal],
    bone_proposals: list[Proposal],
    channel_catalog: set[str] | None = None,
    head_bone: str | None = None,
    rig_kind: str = "custom",
) -> RigProfile:
    """Assemble a RigProfile.

    Point transforms are the defaults for every role that has at least one
    bone binding (a following bone needs a moving point); roles without
    followers are omitted to keep the rig lean.
    """
    catalog = channel_catalog if channel_catalog is not None else set(ARKIT_CHANNELS)

    profile = RigProfile(name=name, head_bone=head_bone, rig_kind=rig_kind)
    profile.shapekey_bindings = [
        ShapeKeyBinding(channel=p.key, target=p.target)
        for p in shapekey_proposals
        if p.kind == "shapekey" and p.key in catalog
    ]
    profile.bone_bindings = [
        BoneBinding(point=_binding_point(p), target=p.target,
                    constraint=_constraint_for(p))
        for p in bone_proposals
        if p.kind == "bone"
    ]

    bound_roles = sorted({b.point for b in profile.bone_bindings})
    if bound_roles:
        profile.points = [
            t for t in default_point_transforms(catalog) if t.role in bound_roles
        ]
        # Drop bone bindings whose point ended up with no transforms at all.
        driven_roles = {t.role for t in profile.points}
        profile.bone_bindings = [
            b for b in profile.bone_bindings if b.point in driven_roles
        ]
    return profile


def as_matcher_proposals(items) -> list[Proposal]:
    """Rebuild matcher Proposals from wizard review rows (duck-typed: .key,
    .target, .confidence attributes — no bpy import needed)."""
    return [Proposal(key=item.key, kind="shapekey", target=item.target,
                     confidence=item.confidence, reason="review")
            for item in items]


def _binding_point(proposal: Proposal) -> str:
    """Point role a bone follows. The matcher keys bones by role directly."""
    return proposal.key


def _constraint_for(proposal: Proposal) -> str:
    """Constraint kind per role semantics. Eyelids/jaw rotate, rest copy location.

    v1 heuristic: bone followers use copy_location (predictable, axis-explicit
    through the point transforms). copy_rotation stays available for hand-tuned
    profiles; damped_track is reserved for gaze aim in a later iteration.
    """
    return "copy_location"
