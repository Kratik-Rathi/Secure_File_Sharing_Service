import io
import time

from tests.conftest import auth_header


def upload(client, headers, content=b"hello secure world", name="test.txt"):
    return client.post(
        "/files",
        headers=headers,
        files={"file": (name, io.BytesIO(content), "text/plain")},
    )


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_upload_requires_auth(client):
    assert upload(client, {}).status_code in (401, 403)


def test_upload_then_sign_then_download(client):
    headers = auth_header(client, "alice", "alice-pw")

    created = upload(client, headers)
    assert created.status_code == 201
    file_id = created.json()["id"]

    signed = client.post(
        f"/files/{file_id}/sign", headers=headers, json={"ttl_seconds": 300}
    )
    assert signed.status_code == 200

    url = signed.json()["download_url"]
    resp = client.get(url.replace("http://testserver", ""))
    assert resp.status_code == 200
    assert resp.content == b"hello secure world"


def test_tampered_signature_returns_403(client):
    headers = auth_header(client, "alice", "alice-pw")
    file_id = upload(client, headers).json()["id"]
    url = client.post(
        f"/files/{file_id}/sign", headers=headers, json={"ttl_seconds": 300}
    ).json()["download_url"]

    path = url.replace("http://testserver", "")
    forged = path[:-1] + ("0" if path[-1] != "0" else "1")
    assert client.get(forged).status_code == 403


def test_expired_link_returns_410(client):
    headers = auth_header(client, "alice", "alice-pw")
    file_id = upload(client, headers).json()["id"]
    url = client.post(
        f"/files/{file_id}/sign", headers=headers, json={"ttl_seconds": 1}
    ).json()["download_url"]

    time.sleep(2)
    assert client.get(url.replace("http://testserver", "")).status_code == 410


def test_user_cannot_see_another_users_file(client):
    alice = auth_header(client, "alice", "alice-pw")
    bob = auth_header(client, "bob", "bob-pw")

    file_id = upload(client, alice).json()["id"]

    assert client.get(f"/files/{file_id}", headers=bob).status_code == 404
    assert (
        client.post(
            f"/files/{file_id}/sign", headers=bob, json={"ttl_seconds": 60}
        ).status_code
        == 404
    )


def test_file_list_is_scoped_to_owner(client):
    alice = auth_header(client, "alice", "alice-pw")
    bob = auth_header(client, "bob", "bob-pw")
    upload(client, alice)

    assert len(client.get("/files", headers=alice).json()) == 1
    assert client.get("/files", headers=bob).json() == []


def test_invalid_ttl_rejected(client):
    headers = auth_header(client, "alice", "alice-pw")
    file_id = upload(client, headers).json()["id"]

    for bad in (0, -5, 999999):
        resp = client.post(
            f"/files/{file_id}/sign", headers=headers, json={"ttl_seconds": bad}
        )
        assert resp.status_code == 422


def test_bad_credentials_rejected(client):
    assert (
        client.post(
            "/auth/login", json={"username": "alice", "password": "wrong"}
        ).status_code
        == 401
    )


def test_link_generation_is_audited(client):
    headers = auth_header(client, "alice", "alice-pw")
    file_id = upload(client, headers).json()["id"]
    client.post(f"/files/{file_id}/sign", headers=headers, json={"ttl_seconds": 60})

    events = client.get(f"/files/{file_id}/audit", headers=headers).json()
    assert any(e["event_type"] == "link_generated" for e in events)


def test_delete_file_removes_it(client):
    headers = auth_header(client, "alice", "alice-pw")
    file_id = upload(client, headers).json()["id"]

    assert client.delete(f"/files/{file_id}", headers=headers).status_code == 204
    assert client.get(f"/files/{file_id}", headers=headers).status_code == 404
    assert client.get("/files", headers=headers).json() == []


def test_cannot_delete_another_users_file(client):
    alice = auth_header(client, "alice", "alice-pw")
    bob = auth_header(client, "bob", "bob-pw")
    file_id = upload(client, alice).json()["id"]

    assert client.delete(f"/files/{file_id}", headers=bob).status_code == 404
    assert client.get(f"/files/{file_id}", headers=alice).status_code == 200


def test_deleted_file_link_no_longer_resolves(client):
    headers = auth_header(client, "alice", "alice-pw")
    file_id = upload(client, headers).json()["id"]
    url = client.post(
        f"/files/{file_id}/sign", headers=headers, json={"ttl_seconds": 300}
    ).json()["download_url"]

    client.delete(f"/files/{file_id}", headers=headers)
    assert client.get(url.replace("http://testserver", "")).status_code == 404
    