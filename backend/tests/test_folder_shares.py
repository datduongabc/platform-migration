from uuid import uuid4

ME = str(uuid4())
OTHER = str(uuid4())


def get_meeting_role(
    meeting_user_id: str, meeting_folder_id: str, current_user_id: str, folders: list
) -> str:
    if meeting_user_id == current_user_id:
        return "owner"
    for f in folders:
        if f["id"] == meeting_folder_id:
            if f["user_id"] == current_user_id or f.get("myRole") == "owner":
                return "owner"
            return f.get("myRole", "viewer")
    return "viewer"


def can_pin(meeting_user_id: str, current_user_id: str) -> bool:
    return meeting_user_id == current_user_id


def can_edit(role: str) -> bool:
    return role in ("owner", "editor")


def can_delete(role: str) -> bool:
    return role in ("owner", "editor")


def can_manage_shares(folder_owner_id: str, current_user_id: str) -> bool:
    return folder_owner_id == current_user_id


def test_get_meeting_role_owner():
    folders = []
    assert get_meeting_role(ME, None, ME, folders) == "owner"


def test_get_meeting_role_editor():
    editor_folder_id = str(uuid4())
    folders = [{"id": editor_folder_id, "user_id": OTHER, "myRole": "editor"}]
    assert get_meeting_role(OTHER, editor_folder_id, ME, folders) == "editor"


def test_get_meeting_role_viewer():
    viewer_folder_id = str(uuid4())
    folders = [{"id": viewer_folder_id, "user_id": OTHER, "myRole": "viewer"}]
    assert get_meeting_role(OTHER, viewer_folder_id, ME, folders) == "viewer"


def test_can_pin():
    assert can_pin(ME, ME) is True
    assert can_pin(OTHER, ME) is False


def test_can_edit():
    assert can_edit("owner") is True
    assert can_edit("editor") is True
    assert can_edit("viewer") is False


def test_can_delete():
    assert can_delete("owner") is True
    assert can_delete("editor") is True
    assert can_delete("viewer") is False


def test_can_manage_shares():
    assert can_manage_shares(ME, ME) is True
    assert can_manage_shares(OTHER, ME) is False
