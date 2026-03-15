ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

def _is_allowed_image(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def _profile_context(session) -> dict[str, str]:
    username = session.get('username', 'Guest User')
    return {
        "name": session.get('profile_name', username),
        "role": session.get('profile_role', 'Player'),
        "avatar": session.get('profile_picture', ''),
    }