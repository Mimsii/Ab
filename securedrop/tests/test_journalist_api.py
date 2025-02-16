import binascii
import hashlib
import json
import random
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from db import db
from encryption import EncryptionManager
from flask import url_for
from models import Journalist, Reply, Source, SourceStar, Submission
from tests.utils.api_helper import get_api_headers
from two_factor import TOTP

import redwood

random.seed("◔ ⌣ ◔")


def assert_valid_timestamp(timestamp: str) -> None:
    """verify the timestamp is encoded in the format we want"""
    assert timestamp == datetime.fromisoformat(timestamp).isoformat()


def test_unauthenticated_user_gets_all_endpoints(journalist_app):
    with journalist_app.test_client() as app:
        response = app.get(url_for("api.get_endpoints"))

        expected_endpoints = [
            "current_user_url",
            "all_users_url",
            "submissions_url",
            "sources_url",
            "auth_token_url",
            "replies_url",
            "seen_url",
        ]
        expected_endpoints.sort()
        sorted_observed_endpoints = list(response.json.keys())
        sorted_observed_endpoints.sort()
        assert expected_endpoints == sorted_observed_endpoints


def test_valid_user_can_get_an_api_token(journalist_app, test_journo):
    with journalist_app.test_client() as app:
        valid_token = TOTP(test_journo["otp_secret"]).now()
        response = app.post(
            url_for("api.get_token"),
            data=json.dumps(
                {
                    "username": test_journo["username"],
                    "passphrase": test_journo["password"],
                    "one_time_code": valid_token,
                }
            ),
            headers=get_api_headers(),
        )

        assert response.json["journalist_uuid"] == test_journo["uuid"]
        assert response.status_code == 200
        assert response.json["journalist_first_name"] == test_journo["first_name"]
        assert response.json["journalist_last_name"] == test_journo["last_name"]

        assert_valid_timestamp(response.json["expiration"])

        response = app.get(
            url_for("api.get_current_user"),
            headers=get_api_headers(response.json["token"]),
        )
        assert response.status_code == 200
        assert response.json["uuid"] == test_journo["uuid"]


def test_user_cannot_get_an_api_token_with_wrong_password(journalist_app, test_journo):
    with journalist_app.test_client() as app:
        valid_token = TOTP(test_journo["otp_secret"]).now()
        response = app.post(
            url_for("api.get_token"),
            data=json.dumps(
                {
                    "username": test_journo["username"],
                    "passphrase": "wrong password",
                    "one_time_code": valid_token,
                }
            ),
            headers=get_api_headers(),
        )

        assert response.status_code == 403
        assert response.json["error"] == "Forbidden"


def test_user_cannot_get_an_api_token_with_wrong_2fa_token(journalist_app, test_journo):
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api.get_token"),
            data=json.dumps(
                {
                    "username": test_journo["username"],
                    "passphrase": test_journo["password"],
                    "one_time_code": "123456",
                }
            ),
            headers=get_api_headers(),
        )

        assert response.status_code == 403
        assert response.json["error"] == "Forbidden"


def test_user_cannot_get_an_api_token_with_no_passphrase_field(journalist_app, test_journo):
    with journalist_app.test_client() as app:
        valid_token = TOTP(test_journo["otp_secret"]).now()
        response = app.post(
            url_for("api.get_token"),
            data=json.dumps({"username": test_journo["username"], "one_time_code": valid_token}),
            headers=get_api_headers(),
        )

        assert response.status_code == 400
        assert response.json["error"] == "Bad Request"
        assert response.json["message"] == "passphrase field is missing"


def test_user_cannot_get_an_api_token_with_no_username_field(journalist_app, test_journo):
    with journalist_app.test_client() as app:
        valid_token = TOTP(test_journo["otp_secret"]).now()
        response = app.post(
            url_for("api.get_token"),
            data=json.dumps({"passphrase": test_journo["password"], "one_time_code": valid_token}),
            headers=get_api_headers(),
        )

        assert response.status_code == 400
        assert response.json["error"] == "Bad Request"
        assert response.json["message"] == "username field is missing"


def test_user_cannot_get_an_api_token_with_no_otp_field(journalist_app, test_journo):
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api.get_token"),
            data=json.dumps(
                {
                    "username": test_journo["username"],
                    "passphrase": test_journo["password"],
                }
            ),
            headers=get_api_headers(),
        )

        assert response.status_code == 400
        assert response.json["error"] == "Bad Request"
        assert response.json["message"] == "one_time_code field is missing"


def test_authorized_user_gets_all_sources(journalist_app, test_submissions, journalist_api_token):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.get_all_sources"),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        # We expect to see our test source in the response
        assert (
            test_submissions["source"].journalist_designation
            == response.json["sources"][0]["journalist_designation"]
        )
        for source in response.json["sources"]:
            assert_valid_timestamp(source["last_updated"])


def test_user_without_token_cannot_get_protected_endpoints(journalist_app, test_files):
    with journalist_app.app_context():
        uuid = test_files["source"].uuid
        protected_routes = [
            url_for("api.get_all_sources"),
            url_for("api.single_source", source_uuid=uuid),
            url_for("api.all_source_submissions", source_uuid=uuid),
            url_for(
                "api.single_submission",
                source_uuid=uuid,
                submission_uuid=test_files["submissions"][0].uuid,
            ),
            url_for(
                "api.download_submission",
                source_uuid=uuid,
                submission_uuid=test_files["submissions"][0].uuid,
            ),
            url_for("api.get_all_submissions"),
            url_for("api.get_all_replies"),
            url_for(
                "api.single_reply",
                source_uuid=uuid,
                reply_uuid=test_files["replies"][0].uuid,
            ),
            url_for("api.all_source_replies", source_uuid=uuid),
            url_for("api.get_current_user"),
            url_for("api.get_all_users"),
        ]

    with journalist_app.test_client() as app:
        for protected_route in protected_routes:
            response = app.get(protected_route, headers=get_api_headers(""))

            assert response.status_code == 403


def test_user_without_token_cannot_del_protected_endpoints(journalist_app, test_submissions):
    with journalist_app.app_context():
        uuid = test_submissions["source"].uuid
        protected_routes = [
            url_for("api.single_source", source_uuid=uuid),
            url_for(
                "api.single_submission",
                source_uuid=uuid,
                submission_uuid=test_submissions["submissions"][0].uuid,
            ),
            url_for("api.remove_star", source_uuid=uuid),
            url_for("api.source_conversation", source_uuid=uuid),
        ]

    with journalist_app.test_client() as app:
        for protected_route in protected_routes:
            response = app.delete(protected_route, headers=get_api_headers(""))

            assert response.status_code == 403


def test_attacker_cannot_use_token_after_admin_deletes(
    journalist_app, test_source, journalist_api_token
):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid

        # In a scenario where an attacker compromises a journalist workstation
        # the admin should be able to delete the user and their token should
        # no longer be valid.
        attacker = app.get(
            url_for("api.get_current_user"),
            headers=get_api_headers(journalist_api_token),
        ).json

        attacker = Journalist.query.filter_by(uuid=attacker["uuid"]).first()

        db.session.delete(attacker)
        db.session.commit()

        # Now this token should not be valid.
        response = app.delete(
            url_for("api.single_source", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 403


def test_user_without_token_cannot_post_protected_endpoints(journalist_app, test_source):
    with journalist_app.app_context():
        uuid = test_source["source"].uuid
        protected_routes = [
            url_for("api.all_source_replies", source_uuid=uuid),
            url_for("api.add_star", source_uuid=uuid),
            url_for("api.flag", source_uuid=uuid),
        ]

    with journalist_app.test_client() as app:
        for protected_route in protected_routes:
            response = app.post(
                protected_route,
                headers=get_api_headers(""),
                data=json.dumps({"some": "stuff"}),
            )
            assert response.status_code == 403


def test_api_error_handlers_defined(journalist_app):
    """Ensure the expected error handler is defined in the API blueprint"""
    for status_code in [400, 401, 403, 404, 500]:
        result = journalist_app.error_handler_spec["api"][status_code]

        expected_error_handler = "_handle_api_http_exception"
        assert list(result.values())[0].__name__ == expected_error_handler


def test_api_error_handler_404(journalist_app, journalist_api_token):
    with journalist_app.test_client() as app:
        response = app.get("/api/v1/invalidendpoint", headers=get_api_headers(journalist_api_token))

        assert response.status_code == 404
        assert response.json["error"] == "Not Found"


def test_trailing_slash_cleanly_404s(journalist_app, test_source, journalist_api_token):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.get(
            url_for("api.single_source", source_uuid=uuid) + "/",
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 404
        assert response.json["error"] == "Not Found"


def test_authorized_user_gets_single_source(journalist_app, test_source, journalist_api_token):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.get(
            url_for("api.single_source", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        assert response.json["uuid"] == test_source["source"].uuid
        assert response.json["key"]["fingerprint"] == test_source["source"].fingerprint
        assert redwood.is_valid_public_key(response.json["key"]["public"])


def test_get_non_existant_source_404s(journalist_app, journalist_api_token):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.single_source", source_uuid=1),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 404


def test_authorized_user_can_star_a_source(journalist_app, test_source, journalist_api_token):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        source_id = test_source["source"].id
        response = app.post(
            url_for("api.add_star", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 201

        # Verify that the source was starred.
        assert SourceStar.query.filter(SourceStar.source_id == source_id).one().starred

        # API should also report is_starred is true
        response = app.get(
            url_for("api.single_source", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["is_starred"] is True


def test_authorized_user_can_unstar_a_source(journalist_app, test_source, journalist_api_token):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        source_id = test_source["source"].id
        response = app.post(
            url_for("api.add_star", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 201

        response = app.delete(
            url_for("api.remove_star", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200

        # Verify that the source is gone.
        assert SourceStar.query.filter(SourceStar.source_id == source_id).one().starred is False

        # API should also report is_starred is false
        response = app.get(
            url_for("api.single_source", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["is_starred"] is False


def test_disallowed_methods_produces_405(journalist_app, test_source, journalist_api_token):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.delete(
            url_for("api.add_star", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 405
        assert response.json["error"] == "Method Not Allowed"


def test_authorized_user_can_get_all_submissions(
    journalist_app, test_submissions, journalist_api_token
):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.get_all_submissions"),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200

        observed_submissions = [
            submission["filename"] for submission in response.json["submissions"]
        ]

        expected_submissions = [submission.filename for submission in Submission.query.all()]
        assert observed_submissions == expected_submissions


def test_authorized_user_get_all_submissions_with_disconnected_submissions(
    journalist_app, test_submissions, journalist_api_token
):
    with journalist_app.test_client() as app:
        db.session.execute(
            "DELETE FROM sources WHERE id = :id", {"id": test_submissions["source"].id}
        )
        response = app.get(
            url_for("api.get_all_submissions"),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200


def test_authorized_user_get_source_submissions(
    journalist_app, test_submissions, journalist_api_token
):
    with journalist_app.test_client() as app:
        uuid = test_submissions["source"].uuid
        response = app.get(
            url_for("api.all_source_submissions", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200

        observed_submissions = [
            submission["filename"] for submission in response.json["submissions"]
        ]

        expected_submissions = [
            submission.filename for submission in test_submissions["source"].submissions
        ]
        assert observed_submissions == expected_submissions


def test_authorized_user_can_get_single_submission(
    journalist_app, test_submissions, journalist_api_token
):
    with journalist_app.test_client() as app:
        submission_uuid = test_submissions["source"].submissions[0].uuid
        uuid = test_submissions["source"].uuid
        response = app.get(
            url_for(
                "api.single_submission",
                source_uuid=uuid,
                submission_uuid=submission_uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        assert response.json["uuid"] == submission_uuid
        assert response.json["is_read"] is False
        assert response.json["filename"] == test_submissions["source"].submissions[0].filename
        assert response.json["size"] == test_submissions["source"].submissions[0].size


def test_authorized_user_can_get_all_replies_with_disconnected_replies(
    journalist_app, test_files, journalist_api_token
):
    with journalist_app.test_client() as app:
        db.session.execute("DELETE FROM sources WHERE id = :id", {"id": test_files["source"].id})
        response = app.get(
            url_for("api.get_all_replies"),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200


def test_authorized_user_can_get_all_replies(journalist_app, test_files, journalist_api_token):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.get_all_replies"),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200

        observed_replies = [reply["filename"] for reply in response.json["replies"]]

        expected_replies = [reply.filename for reply in Reply.query.all()]
        assert observed_replies == expected_replies


def test_authorized_user_get_source_replies(journalist_app, test_files, journalist_api_token):
    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        response = app.get(
            url_for("api.all_source_replies", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200

        observed_replies = [reply["filename"] for reply in response.json["replies"]]

        expected_replies = [reply.filename for reply in test_files["source"].replies]
        assert observed_replies == expected_replies


def test_authorized_user_can_get_single_reply(journalist_app, test_files, journalist_api_token):
    with journalist_app.test_client() as app:
        reply_uuid = test_files["source"].replies[0].uuid
        uuid = test_files["source"].uuid
        response = app.get(
            url_for("api.single_reply", source_uuid=uuid, reply_uuid=reply_uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        reply = Reply.query.filter(Reply.uuid == reply_uuid).one()

        assert response.json["uuid"] == reply_uuid
        assert response.json["journalist_username"] == reply.journalist.username
        assert response.json["journalist_uuid"] == reply.journalist.uuid
        assert response.json["journalist_first_name"] == (reply.journalist.first_name or "")
        assert response.json["journalist_last_name"] == (reply.journalist.last_name or "")
        assert response.json["is_deleted_by_source"] is False
        assert response.json["filename"] == test_files["source"].replies[0].filename
        assert response.json["size"] == test_files["source"].replies[0].size


def test_reply_of_deleted_journalist(
    journalist_app, test_files_deleted_journalist, journalist_api_token
):
    with journalist_app.test_client() as app:
        reply_uuid = test_files_deleted_journalist["source"].replies[0].uuid
        uuid = test_files_deleted_journalist["source"].uuid
        response = app.get(
            url_for("api.single_reply", source_uuid=uuid, reply_uuid=reply_uuid),
            headers=get_api_headers(journalist_api_token),
        )
        deleted_uuid = Journalist.get_deleted().uuid
        assert response.status_code == 200

        assert response.json["uuid"] == reply_uuid
        assert response.json["journalist_username"] == "deleted"
        assert response.json["journalist_uuid"] == deleted_uuid
        assert response.json["journalist_first_name"] == ""
        assert response.json["journalist_last_name"] == ""
        assert response.json["is_deleted_by_source"] is False
        assert (
            response.json["filename"] == test_files_deleted_journalist["source"].replies[0].filename
        )
        assert response.json["size"] == test_files_deleted_journalist["source"].replies[0].size


def test_authorized_user_can_delete_single_submission(
    journalist_app, test_submissions, journalist_api_token
):
    with journalist_app.test_client() as app:
        submission_uuid = test_submissions["source"].submissions[0].uuid
        uuid = test_submissions["source"].uuid
        response = app.delete(
            url_for(
                "api.single_submission",
                source_uuid=uuid,
                submission_uuid=submission_uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        # Submission now should be gone.
        assert Submission.query.filter(Submission.uuid == submission_uuid).all() == []


def test_authorized_user_can_delete_single_reply(journalist_app, test_files, journalist_api_token):
    with journalist_app.test_client() as app:
        reply_uuid = test_files["source"].replies[0].uuid
        uuid = test_files["source"].uuid
        response = app.delete(
            url_for("api.single_reply", source_uuid=uuid, reply_uuid=reply_uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        # Reply should now be gone.
        assert Reply.query.filter(Reply.uuid == reply_uuid).all() == []


def test_authorized_user_can_delete_source_conversation(
    journalist_app, test_files, journalist_api_token
):
    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        source_id = test_files["source"].id

        # Submissions and Replies both exist
        assert Submission.query.filter(source_id == source_id).all() != []
        assert Reply.query.filter(source_id == source_id).all() != []

        response = app.delete(
            url_for("api.source_conversation", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        # Submissions and Replies do not exist
        assert Submission.query.filter(source_id == source_id).all() == []
        assert Reply.query.filter(source_id == source_id).all() == []

        # Source still exists
        assert Source.query.filter(uuid == uuid).all() != []


def test_source_conversation_does_not_support_get(
    journalist_app, test_source, journalist_api_token
):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.get(
            url_for("api.source_conversation", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 405


def test_authorized_user_can_delete_source_collection(
    journalist_app, test_source, journalist_api_token
):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.delete(
            url_for("api.single_source", source_uuid=uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        # Source does not exist
        assert Source.query.all() == []


def test_authorized_user_can_download_submission(
    journalist_app, test_submissions, journalist_api_token
):
    with journalist_app.test_client() as app:
        submission_uuid = test_submissions["source"].submissions[0].uuid
        uuid = test_submissions["source"].uuid

        response = app.get(
            url_for(
                "api.download_submission",
                source_uuid=uuid,
                submission_uuid=submission_uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        # Response should be a PGP encrypted download
        assert response.mimetype == "application/pgp-encrypted"

        # Response should have Etag field with hash
        assert response.headers["ETag"].startswith("sha256:")


def test_authorized_user_can_download_reply(journalist_app, test_files, journalist_api_token):
    with journalist_app.test_client() as app:
        reply_uuid = test_files["source"].replies[0].uuid
        uuid = test_files["source"].uuid

        response = app.get(
            url_for("api.download_reply", source_uuid=uuid, reply_uuid=reply_uuid),
            headers=get_api_headers(journalist_api_token),
        )

        assert response.status_code == 200

        # Response should be a PGP encrypted download
        assert response.mimetype == "application/pgp-encrypted"

        # Response should have Etag field with hash
        assert response.headers["ETag"].startswith("sha256:")


def test_authorized_user_can_get_current_user_endpoint(
    journalist_app, test_journo, journalist_api_token
):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.get_current_user"),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200

        assert response.json["is_admin"] is False
        assert response.json["username"] == test_journo["username"]
        assert response.json["uuid"] == test_journo["journalist"].uuid
        assert response.json["first_name"] == test_journo["journalist"].first_name
        assert response.json["last_name"] == test_journo["journalist"].last_name


def test_authorized_user_can_get_all_users(
    journalist_app, test_journo, test_admin, journalist_api_token
):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.get_all_users"), headers=get_api_headers(journalist_api_token)
        )

        assert response.status_code == 200

        # Ensure that all the users in the database are returned
        observed_users = [user["uuid"] for user in response.json["users"]]
        expected_users = [user.uuid for user in Journalist.query.all()]
        assert observed_users == expected_users

        # Ensure that no fields other than the expected ones are returned
        expected_fields = ["first_name", "last_name", "username", "uuid"]
        for user in response.json["users"]:
            assert sorted(user.keys()) == expected_fields


def test_request_with_missing_auth_header_triggers_403(journalist_app):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.get_current_user"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        assert response.status_code == 403


def test_request_with_auth_header_but_no_token_triggers_403(journalist_app):
    with journalist_app.test_client() as app:
        response = app.get(
            url_for("api.get_current_user"),
            headers={
                "Authorization": "",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 403


def test_unencrypted_replies_get_rejected(
    journalist_app, journalist_api_token, test_source, test_journo
):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        reply_content = "This is a plaintext reply"
        response = app.post(
            url_for("api.all_source_replies", source_uuid=uuid),
            data=json.dumps({"reply": reply_content}),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400


def test_authorized_user_can_add_reply(
    journalist_app, journalist_api_token, test_source, test_journo, app_storage, tmp_path
):
    with journalist_app.test_client() as app:
        source_id = test_source["source"].id
        uuid = test_source["source"].uuid

        # First we must encrypt the reply, or it will get rejected
        # by the server.
        reply_path = tmp_path / "message.gpg"
        # Use redwood directly, so we can generate an armored message.
        redwood.encrypt_message(
            recipients=[
                test_source["source"].public_key,
                EncryptionManager.get_default().get_journalist_public_key(),
            ],
            plaintext="This is an encrypted reply",
            destination=reply_path,
            armor=True,
        )
        reply_content = reply_path.read_text()

        response = app.post(
            url_for("api.all_source_replies", source_uuid=uuid),
            data=json.dumps({"reply": reply_content}),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 201

    # ensure the uuid is present and valid
    reply_uuid = UUID(response.json["uuid"])

    # check that the uuid has a matching db object
    reply = Reply.query.filter_by(uuid=str(reply_uuid)).one_or_none()
    assert reply is not None

    # check that the filename is present and correct (#4047)
    assert response.json["filename"] == reply.filename

    with journalist_app.app_context():  # Now verify everything was saved.
        assert reply.journalist_id == test_journo["id"]
        assert reply.source_id == source_id

        # regression test for #3918
        assert "/" not in reply.filename

        source = Source.query.get(source_id)

        expected_filename = f"{source.interaction_count}-{source.journalist_filename}-reply.gpg"

        expected_filepath = Path(app_storage.path(source.filesystem_id, expected_filename))

        saved_content = expected_filepath.read_text()

        assert reply_content == saved_content


def test_reply_without_content_400(journalist_app, journalist_api_token, test_source, test_journo):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.post(
            url_for("api.all_source_replies", source_uuid=uuid),
            data=json.dumps({"reply": ""}),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400


def test_reply_without_reply_field_400(
    journalist_app, journalist_api_token, test_source, test_journo
):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.post(
            url_for("api.all_source_replies", source_uuid=uuid),
            data=json.dumps({"other": "stuff"}),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400


def test_reply_without_json_400(journalist_app, journalist_api_token, test_source, test_journo):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.post(
            url_for("api.all_source_replies", source_uuid=uuid),
            data="invalid",
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400


def test_reply_with_valid_curly_json_400(
    journalist_app, journalist_api_token, test_source, test_journo
):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.post(
            url_for("api.all_source_replies", source_uuid=uuid),
            data="{}",
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400

        assert response.json["message"] == "reply not found in request body"


def test_reply_with_valid_square_json_400(
    journalist_app, journalist_api_token, test_source, test_journo
):
    with journalist_app.test_client() as app:
        uuid = test_source["source"].uuid
        response = app.post(
            url_for("api.all_source_replies", source_uuid=uuid),
            data="[]",
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400

        assert response.json["message"] == "reply not found in request body"


def test_malformed_json_400(journalist_app, journalist_api_token, test_journo, test_source):
    with journalist_app.app_context():
        uuid = test_source["source"].uuid
        protected_routes = [
            url_for("api.get_token"),
            url_for("api.all_source_replies", source_uuid=uuid),
            url_for("api.add_star", source_uuid=uuid),
            url_for("api.flag", source_uuid=uuid),
        ]
    with journalist_app.test_client() as app:
        for protected_route in protected_routes:
            response = app.post(
                protected_route,
                data="{this is invalid {json!",
                headers=get_api_headers(journalist_api_token),
            )

            assert response.status_code == 400
            assert response.json["error"] == "Bad Request"


def test_empty_json_400(journalist_app, journalist_api_token, test_journo, test_source):
    with journalist_app.app_context():
        uuid = test_source["source"].uuid
        protected_routes = [
            url_for("api.get_token"),
            url_for("api.all_source_replies", source_uuid=uuid),
        ]
    with journalist_app.test_client() as app:
        for protected_route in protected_routes:
            response = app.post(
                protected_route, data="", headers=get_api_headers(journalist_api_token)
            )

            assert response.status_code == 400
            assert response.json["error"] == "Bad Request"


def test_empty_json_20X(journalist_app, journalist_api_token, test_journo, test_source):
    with journalist_app.app_context():
        uuid = test_source["source"].uuid
        protected_routes = [
            url_for("api.add_star", source_uuid=uuid),
            url_for("api.flag", source_uuid=uuid),
        ]
    with journalist_app.test_client() as app:
        for protected_route in protected_routes:
            response = app.post(
                protected_route, data="", headers=get_api_headers(journalist_api_token)
            )

            assert response.status_code in (200, 201)


def test_set_reply_uuid(journalist_app, journalist_api_token, test_source):
    msg = "-----BEGIN PGP MESSAGE-----\nwat\n-----END PGP MESSAGE-----"
    reply_uuid = str(uuid4())
    req_data = {"uuid": reply_uuid, "reply": msg}

    with journalist_app.test_client() as app:
        # first check that we can set a valid UUID
        source_uuid = test_source["uuid"]
        resp = app.post(
            url_for("api.all_source_replies", source_uuid=source_uuid),
            data=json.dumps(req_data),
            headers=get_api_headers(journalist_api_token),
        )
        assert resp.status_code == 201
        assert resp.json["uuid"] == reply_uuid

        reply = Reply.query.filter_by(uuid=reply_uuid).one_or_none()
        assert reply is not None

        len_of_replies = len(Source.query.get(test_source["id"]).replies)

        # next check that requesting with the same UUID does not succeed
        source_uuid = test_source["uuid"]
        resp = app.post(
            url_for("api.all_source_replies", source_uuid=source_uuid),
            data=json.dumps(req_data),
            headers=get_api_headers(journalist_api_token),
        )
        assert resp.status_code == 409

        new_len_of_replies = len(Source.query.get(test_source["id"]).replies)

        assert new_len_of_replies == len_of_replies

        # check setting null for the uuid field doesn't break
        req_data["uuid"] = None
        source_uuid = test_source["uuid"]
        resp = app.post(
            url_for("api.all_source_replies", source_uuid=source_uuid),
            data=json.dumps(req_data),
            headers=get_api_headers(journalist_api_token),
        )
        assert resp.status_code == 201

        new_uuid = resp.json["uuid"]
        reply = Reply.query.filter_by(uuid=new_uuid).one_or_none()
        assert reply is not None

        # check setting invalid values for the uuid field doesn't break
        req_data["uuid"] = "not a uuid"
        source_uuid = test_source["uuid"]
        resp = app.post(
            url_for("api.all_source_replies", source_uuid=source_uuid),
            data=json.dumps(req_data),
            headers=get_api_headers(journalist_api_token),
        )
        assert resp.status_code == 400


def test_api_does_not_set_cookie_headers(journalist_app, test_journo):
    with journalist_app.test_client() as app:
        response = app.get(url_for("api.get_endpoints"))

        observed_headers = response.headers
        assert "Set-Cookie" not in list(observed_headers.keys())
        if "Vary" in list(observed_headers.keys()):
            assert "Cookie" not in observed_headers["Vary"]


# regression test for #4053
def test_malformed_auth_token(journalist_app, journalist_api_token):
    with journalist_app.app_context():
        # we know this endpoint requires an auth header
        url = url_for("api.get_all_sources")

    with journalist_app.test_client() as app:
        # precondition to ensure token is even valid
        resp = app.get(url, headers={"Authorization": f"Token {journalist_api_token}"})
        assert resp.status_code == 200

        resp = app.get(url, headers={"Authorization": f"not-token {journalist_api_token}"})
        assert resp.status_code == 403

        resp = app.get(url, headers={"Authorization": journalist_api_token})
        assert resp.status_code == 403

        resp = app.get(url, headers={"Authorization": f"too many {journalist_api_token}"})
        assert resp.status_code == 403


def test_submission_download_generates_checksum(
    journalist_app, journalist_api_token, test_source, test_submissions, mocker
):
    submission = test_submissions["submissions"][0]
    assert submission.checksum is None  # precondition

    with journalist_app.test_client() as app:
        response = app.get(
            url_for(
                "api.download_submission",
                source_uuid=test_source["uuid"],
                submission_uuid=submission.uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200
        assert response.headers["ETag"]

    # check that the submission checksum was added
    fetched_submission = Submission.query.get(submission.id)
    assert fetched_submission.checksum

    mock_add_checksum = mocker.patch("journalist_app.utils.add_checksum_for_file")
    with journalist_app.test_client() as app:
        response = app.get(
            url_for(
                "api.download_submission",
                source_uuid=test_source["uuid"],
                submission_uuid=submission.uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200
        assert response.headers["ETag"]

    fetched_submission = Submission.query.get(submission.id)
    assert fetched_submission.checksum
    # we don't want to recalculat this value
    assert not mock_add_checksum.called


def test_reply_download_generates_checksum(
    journalist_app, journalist_api_token, test_source, test_files, mocker
):
    reply = test_files["replies"][0]
    assert reply.checksum is None  # precondition

    with journalist_app.test_client() as app:
        response = app.get(
            url_for(
                "api.download_reply",
                source_uuid=test_source["uuid"],
                reply_uuid=reply.uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200
        assert response.headers["ETag"]

    # check that the reply checksum was added
    fetched_reply = Reply.query.get(reply.id)
    assert fetched_reply.checksum

    mock_add_checksum = mocker.patch("journalist_app.utils.add_checksum_for_file")
    with journalist_app.test_client() as app:
        response = app.get(
            url_for(
                "api.download_reply",
                source_uuid=test_source["uuid"],
                reply_uuid=reply.uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200
        assert response.headers["ETag"]

    fetched_reply = Reply.query.get(reply.id)
    assert fetched_reply.checksum
    # we don't want to recalculat this value
    assert not mock_add_checksum.called


def test_seen(journalist_app, journalist_api_token, test_files, test_journo, test_submissions):
    """
    Happy path for seen: marking things seen works.
    """
    with journalist_app.test_client() as app:
        replies_url = url_for("api.get_all_replies")
        seen_url = url_for("api.seen")
        submissions_url = url_for("api.get_all_submissions")
        headers = get_api_headers(journalist_api_token)

        # check that /submissions contains no seen items
        response = app.get(submissions_url, headers=headers)
        assert response.status_code == 200
        assert not any([s["seen_by"] for s in response.json["submissions"]])

        # check that /replies only contains seen items
        response = app.get(replies_url, headers=headers)
        assert response.status_code == 200
        assert all([r["seen_by"] for r in response.json["replies"]])

        # now mark one of each type of conversation item seen
        file_uuid = test_files["submissions"][0].uuid
        msg_uuid = test_submissions["submissions"][0].uuid
        reply_uuid = test_files["replies"][0].uuid
        data = {
            "files": [file_uuid],
            "messages": [msg_uuid],
            "replies": [reply_uuid],
        }
        response = app.post(seen_url, data=json.dumps(data), headers=headers)
        assert response.status_code == 200
        assert response.json["message"] == "resources marked seen"

        # check that /submissions now contains the seen items
        response = app.get(submissions_url, headers=headers)
        assert response.status_code == 200
        assert [
            s
            for s in response.json["submissions"]
            if s["is_file"] and s["uuid"] == file_uuid and test_journo["uuid"] in s["seen_by"]
        ]
        assert [
            s
            for s in response.json["submissions"]
            if s["is_message"] and s["uuid"] == msg_uuid and test_journo["uuid"] in s["seen_by"]
        ]

        # check that /replies still only contains one seen reply
        response = app.get(replies_url, headers=headers)
        assert response.status_code == 200
        assert len(response.json["replies"]) == 1
        assert all([r["seen_by"] for r in response.json["replies"]])

        # now mark the same things seen. this should be fine.
        response = app.post(seen_url, data=json.dumps(data), headers=headers)
        assert response.status_code == 200
        assert response.json["message"] == "resources marked seen"

        # check that /submissions still only has the test journalist
        # once in the seen_by list of the submissions we marked
        response = app.get(submissions_url, headers=headers)
        assert response.status_code == 200
        assert [
            s
            for s in response.json["submissions"]
            if s["uuid"] in [file_uuid, msg_uuid] and s["seen_by"] == [test_journo["uuid"]]
        ]

        # check that /replies still only contains one seen reply
        response = app.get(replies_url, headers=headers)
        assert response.status_code == 200
        assert len(response.json["replies"]) == 1
        assert all([r["seen_by"] for r in response.json["replies"]])


def test_seen_bad_requests(journalist_app, journalist_api_token):
    """
    Check that /seen rejects invalid requests.
    """
    with journalist_app.test_client() as app:
        seen_url = url_for("api.seen")
        headers = get_api_headers(journalist_api_token)

        # invalid JSON
        data = "not a mapping"
        response = app.post(seen_url, data=json.dumps(data), headers=headers)
        assert response.status_code == 400
        assert response.json["message"] == "Please send requests in valid JSON."

        # valid JSON, but with invalid content
        data = {"valid mapping": False}
        response = app.post(seen_url, data=json.dumps(data), headers=headers)
        assert response.status_code == 400
        assert response.json["message"] == "Please specify the resources to mark seen."

        # unsupported HTTP method
        response = app.head(seen_url, headers=headers)
        assert response.status_code == 405

        # nonexistent file
        data = {
            "files": ["not-a-file"],
        }
        response = app.post(seen_url, data=json.dumps(data), headers=headers)
        assert response.status_code == 404
        assert response.json["message"] == "file not found: not-a-file"

        # nonexistent message
        data = {
            "messages": ["not-a-message"],
        }
        response = app.post(seen_url, data=json.dumps(data), headers=headers)
        assert response.status_code == 404
        assert response.json["message"] == "message not found: not-a-message"

        # nonexistent reply
        data = {
            "replies": ["not-a-reply"],
        }
        response = app.post(seen_url, data=json.dumps(data), headers=headers)
        assert response.status_code == 404
        assert response.json["message"] == "reply not found: not-a-reply"


def test_download_submission_range(journalist_app, test_files, journalist_api_token):
    with journalist_app.test_client() as app:
        submission_uuid = test_files["submissions"][0].uuid
        uuid = test_files["source"].uuid

        # Download the full file
        full_response = app.get(
            url_for(
                "api.download_submission",
                source_uuid=uuid,
                submission_uuid=submission_uuid,
            ),
            headers=get_api_headers(journalist_api_token),
        )
        assert full_response.status_code == 200
        assert full_response.mimetype == "application/pgp-encrypted"

        # Verify the etag header is actually the sha256 hash
        hasher = hashlib.sha256()
        hasher.update(full_response.data)
        digest = binascii.hexlify(hasher.digest()).decode("utf-8")
        digest_str = "sha256:" + digest
        assert full_response.headers.get("ETag") == digest_str

        # Verify the Content-Length header matches the length of the content
        assert full_response.headers.get("Content-Length") == str(len(full_response.data))

        # Verify that range requests are accepted
        assert full_response.headers.get("Accept-Ranges") == "bytes"

        # Download the first 10 bytes of data
        headers = get_api_headers(journalist_api_token)
        headers["Range"] = "bytes=0-9"
        partial_response = app.get(
            url_for(
                "api.download_submission",
                source_uuid=uuid,
                submission_uuid=submission_uuid,
            ),
            headers=headers,
        )
        assert partial_response.status_code == 206  # HTTP/1.1 206 Partial Content
        assert partial_response.mimetype == "application/pgp-encrypted"
        assert partial_response.headers.get("Content-Length") == "10"
        assert len(partial_response.data) == 10
        assert full_response.data[0:10] == partial_response.data

        # Download the second half of the data
        range_start = int(len(full_response.data) / 2)
        range_end = len(full_response.data)
        headers = get_api_headers(journalist_api_token)
        headers["Range"] = f"bytes={range_start}-{range_end}"
        partial_response = app.get(
            url_for(
                "api.download_submission",
                source_uuid=uuid,
                submission_uuid=submission_uuid,
            ),
            headers=headers,
        )
        assert partial_response.status_code == 206  # HTTP/1.1 206 Partial Content
        assert partial_response.mimetype == "application/pgp-encrypted"
        assert partial_response.headers.get("Content-Length") == str(range_end - range_start)
        assert len(partial_response.data) == range_end - range_start
        assert full_response.data[range_start:] == partial_response.data
