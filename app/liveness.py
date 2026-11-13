"""Head-turn liveness: the app asks the user to look straight, turn one way, then the other,
and sends one frame per pose. A real head changes where the nose sits relative to the eyes;
a flat photo or screen held up and tilted barely does.

Which way counts as "left" depends on whether the camera mirrors the image, so we only
require the two turned frames to go in OPPOSITE directions from the straight one."""
from . import face

MIN_TURN = 0.15  # yaw change vs. the straight frame; a tilted flat photo moves ~0.03
SAME_PERSON = 0.25  # looser than MATCH_THRESHOLD because turned faces match worse


def check(faces: list[face.Face | None]) -> list[str]:
    """faces = [straight, turn_one_way, turn_other_way]. Returns issues (empty = live)."""
    if len(faces) != 3:
        return ["send exactly 3 frames: straight, turn one way, turn the other way"]
    if any(f is None for f in faces):
        return ["no face found in one of the selfie frames"]
    straight, a, b = faces
    da, db = a.yaw - straight.yaw, b.yaw - straight.yaw
    issues = []
    if min(abs(da), abs(db)) < MIN_TURN or da * db > 0:
        issues.append("head turn not detected; turn your head one way, then the other")
    if min(face.similarity(straight, a), face.similarity(straight, b)) < SAME_PERSON:
        issues.append("selfie frames don't look like the same person")
    return issues
