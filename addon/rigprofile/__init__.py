"""Universal Rig Connector: pure core (no bpy imports).

Canonical channels, name standardization, authored alias lists, versioned
RigProfile JSON documents, and the auto-match engine. The Blender binding
layer (empties, drivers, constraints) lives in the addon and turns profiles
into native, artist-editable links.
"""

from .profile import BoneBinding, PointTransform, ProfileError, RigProfile, ShapeKeyBinding
from .matcher import Proposal, match_bones, match_shapekeys

__all__ = [
    "BoneBinding", "PointTransform", "ProfileError", "RigProfile",
    "ShapeKeyBinding", "Proposal", "match_bones", "match_shapekeys",
]

