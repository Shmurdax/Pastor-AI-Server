from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import IngestedDocument
from core.vimeo_titles import (
    DEFAULT_VIMEO_FOLDER_URL,
    TitleApplyResult,
    VimeoTitleError,
    apply_vimeo_titles,
    fetch_folder_titles,
    parse_vimeo_folder_url,
    resolve_ingest_title,
    titles_for_video_ids,
    vimeo_id_from_source_name,
)


class VimeoTitleHelperTests(TestCase):
    def test_parse_folder_url(self):
        user_id, folder_id = parse_vimeo_folder_url(
            "https://vimeo.com/user/21759939/folder/24205069?isPrivate=false"
        )
        self.assertEqual(user_id, "21759939")
        self.assertEqual(folder_id, "24205069")

    def test_parse_folder_url_rejects_unknown(self):
        with self.assertRaises(VimeoTitleError):
            parse_vimeo_folder_url("https://vimeo.com/461937715")

    def test_numeric_source_ids(self):
        self.assertEqual(vimeo_id_from_source_name("461937715.m4a"), "461937715")
        self.assertIsNone(vimeo_id_from_source_name("Faith That Moves.m4a"))

    def test_apply_mapping_updates_title(self):
        doc = IngestedDocument.objects.create(
            source_name="461937715.m4a",
            title="461937715",
            file_hash="a" * 64,
            original_extension=".m4a",
            source_kind="video",
        )
        result = apply_vimeo_titles(
            {"461937715": "Faith That Moves Mountains"},
            dry_run=False,
            update_qdrant=False,
            update_sidecars=False,
        )
        doc.refresh_from_db()
        self.assertEqual(result.updated, 1)
        self.assertEqual(doc.title, "Faith That Moves Mountains")

    def test_dry_run_does_not_write(self):
        doc = IngestedDocument.objects.create(
            source_name="382077209.m4a",
            title="382077209",
            file_hash="b" * 64,
            original_extension=".m4a",
            source_kind="video",
        )
        result = apply_vimeo_titles(
            {"382077209": "Sunday Talk"},
            dry_run=True,
            update_qdrant=False,
            update_sidecars=False,
        )
        doc.refresh_from_db()
        self.assertEqual(result.updated, 1)
        self.assertEqual(doc.title, "382077209")

    @patch("core.vimeo_titles._vimeo_request")
    def test_fetch_folder_titles(self, mock_request):
        mock_request.return_value = {
            "data": [
                {"uri": "/videos/461937715", "name": "Faith That Moves Mountains"},
            ],
            "paging": {"next": None},
        }
        titles = fetch_folder_titles(DEFAULT_VIMEO_FOLDER_URL, token="vimeo-token")
        self.assertEqual(titles["461937715"], "Faith That Moves Mountains")
        self.assertTrue(mock_request.call_args[0][0].startswith("/users/21759939/projects/24205069/"))

    @patch("core.vimeo_titles.fetch_video_title", return_value=None)
    @patch("core.vimeo_titles.fetch_folder_titles")
    def test_titles_for_ids_uses_folder_map(self, mock_folder, mock_one):
        mock_folder.return_value = {"461937715": "Faith That Moves Mountains"}
        mapping = titles_for_video_ids(
            ["461937715", "999"],
            token="vimeo-token",
            folder_url=DEFAULT_VIMEO_FOLDER_URL,
        )
        self.assertEqual(mapping["461937715"], "Faith That Moves Mountains")
        self.assertNotIn("999", mapping)
        mock_one.assert_called_once_with("999", "vimeo-token")

    @patch("core.vimeo_titles.titles_for_video_ids", return_value={"461937715": "Faith That Moves Mountains"})
    def test_resolve_ingest_title_uses_vimeo(self, _mock_titles):
        with patch.dict("os.environ", {"VIMEO_ACCESS_TOKEN": "vimeo-token"}, clear=False):
            title = resolve_ingest_title("461937715.m4a")
        self.assertEqual(title, "Faith That Moves Mountains")

    def test_resolve_ingest_title_without_token_keeps_stem(self):
        with patch.dict("os.environ", {"VIMEO_ACCESS_TOKEN": ""}, clear=False):
            self.assertEqual(resolve_ingest_title("461937715.m4a", token=""), "461937715")


class VimeoTitleAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)
        IngestedDocument.objects.create(
            source_name="461937715.m4a",
            title="461937715",
            file_hash="c" * 64,
            original_extension=".m4a",
            source_kind="video",
        )

    def test_ingested_videos_page_has_vimeo_form(self):
        from pathlib import Path

        template = Path(__file__).resolve().parent / "templates" / "admin" / "core" / "ingested_videos.html"
        body = template.read_text(encoding="utf-8")
        self.assertIn("Apply Vimeo folder titles", body)
        self.assertIn("vimeo_folder_url", body)
        self.assertIn("vimeo_access_token", body)

    @patch("core.admin.apply_titles_from_vimeo_folder")
    def test_admin_dry_run_does_not_require_qdrant(self, mock_apply):
        mock_apply.return_value = (
            {"461937715": "Faith That Moves Mountains"},
            TitleApplyResult(
                updated=1,
                sample_updates=[("461937715.m4a", "461937715", "Faith That Moves Mountains")],
            ),
        )
        response = self.client.post(
            reverse("admin:core_ingested_videos"),
            {
                "action": "apply_vimeo_titles",
                "vimeo_folder_url": DEFAULT_VIMEO_FOLDER_URL,
                "vimeo_access_token": "vimeo-token",
                "dry_run": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        mock_apply.assert_called_once()
        kwargs = mock_apply.call_args.kwargs
        self.assertTrue(kwargs["dry_run"])
        self.assertFalse(kwargs["update_qdrant"])
