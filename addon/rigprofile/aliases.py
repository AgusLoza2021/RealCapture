"""Authored alias lists for auto-matching rig controls to canonical channels.

Original lists, written for RealCapture. They encode the naming conventions we
observed across common rigs (Rigify/FaceIt, Unity/Unreal exports, VRM/MMD
models) but no list is copied from a licensed project. Stems are side-neutral:
the matcher applies the side of the target control separately.

Keys for SHAPE_ALIASES are side-neutral channel bases (``channel_base()``);
keys for BONE_ALIASES are point roles or channel bases. The exact ARKit name
itself is always tried first by the matcher and needs no entry here.
"""

from __future__ import annotations

SHAPE_ALIASES: dict[str, tuple[str, ...]] = {
    # Eyes
    "eyeblink": ("blink", "mabataki", "eye_close", "close_eye"),
    "eyelookdown": ("look_down", "eyedown", "eye_down"),
    "eyelookin": ("look_in", "eyein", "cross_eye", "crossed"),
    "eyelookout": ("look_out", "eyeout"),
    "eyelookup": ("look_up", "eyeup", "eye_up"),
    "eyesquint": ("squint", "mihiraki"),
    "eyewide": ("wide", "eye_wide", "surprise"),
    # Jaw
    "jawforward": ("jaw_forward", "jawfwd"),
    "jawleft": ("jaw_left", "jawl"),
    "jawopen": ("jaw", "jaw_open", "open_mouth", "mouth_open", "ako"),
    "jawright": ("jaw_right", "jawr"),
    # Mouth
    "mouthclose": ("mouth_close", "lips_close"),
    "mouthdimple": ("dimple", "mouth_dimple"),
    "mouthfrown": ("frown", "mouth_frown", "sad"),
    "mouthfunnel": ("funnel", "mouth_funnel", "o_shape"),
    "mouthleft": ("mouth_left", "mouthl"),
    "mouthlowerdown": ("lower_down", "lip_lower_down", "mouth_lower_down",
                       "lower_lip_down", "frown_lower"),
    "mouthpress": ("press", "mouth_press", "lip_press", "tight_lips"),
    "mouthpucker": ("pucker", "mouth_pucker", "kiss", "tsumami"),
    "mouthright": ("mouth_right", "mouthr"),
    "mouthroll": ("roll", "mouth_roll", "lip_roll"),
    "mouthshrug": ("shrug", "mouth_shrug", "lip_shrug"),
    "mouthsmile": ("smile", "mouth_smile", "nico", "joy", "laugh"),
    "mouthstretch": ("stretch", "mouth_stretch", "wide_mouth"),
    "mouthupperup": ("upper_up", "lip_upper_up", "mouth_upper_up",
                     "upper_lip_up", "snarl"),
    # Nose
    "nosesneer": ("sneer", "nose_sneer", "sniff", "nose_up"),
    # Cheeks
    "cheekpuff": ("puff", "cheek_puff", "blow", "huff"),
    "cheeksquint": ("cheek_squint", "squint_cheek", "cheek_raise",
                    "hoho", "cheek_up"),
    # Brows
    "browdown": ("brow_down", "eyebrow_down", "angry", "frown_brow", "iko"),
    "browinnerup": ("brow_inner", "inner_brow_up", "brow_raise_inner",
                    "inner_brow", "brow_raiser"),
    "browouterup": ("brow_outer", "outer_brow_up", "brow_raise",
                    "brow_up", "eyebrow_up", "metuki"),
    # Tongue
    "tongueout": ("tongue", "tongue_out", "shita", "tongue_out_long"),
    # Japanese-style vowel shapes (VRM/MMD tradition) map best to mouth open/
    # wide/pucker families; kept as low-priority aliases.
    "_vowel_a": ("vowel_a", "a_shape", "mouth_a"),
    "_vowel_i": ("vowel_i", "i_shape", "mouth_i", "ee"),
    "_vowel_u": ("vowel_u", "u_shape", "mouth_u"),
    "_vowel_e": ("vowel_e", "e_shape", "mouth_e"),
    "_vowel_o": ("vowel_o", "o_shape", "mouth_o"),
}

# Bone-role aliases for Face Point Driver followers. Keys are point roles
# (with side handled by the matcher) or channel bases for pose-only channels.
BONE_ALIASES: dict[str, tuple[str, ...]] = {
    "jaw": ("jaw", "jaw_bone", "mandible", "chin_bone", "lower_jaw"),
    "eye_lid": ("eyelid", "eye_lid", "lid", "upper_lid", "lid_top",
                "eyelid_upper", "blink"),
    "eye": ("eye", "eyeball", "eye_look", "gaze", "eyeball_l"),
    "brow": ("brow", "eyebrow", "brow_brow", "mayu"),
    "brow_inner": ("brow_inner", "inner_brow", "brow_middle"),
    "mouth_corner": ("mouth_corner", "corner", "lip_corner", "mouth_edge"),
    "lip_top": ("lip_top", "upper_lip", "lip_upper", "lip_up"),
    "lip_bottom": ("lip_bottom", "lower_lip", "lip_lower", "lip_down"),
    "cheek": ("cheek", "hoho"),
    "tongueout": ("tongue", "tongue_tip", "tongue_01"),
}
