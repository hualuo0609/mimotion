import unittest
from unittest.mock import Mock, patch

from util import zepp_helper


class ZeppPostDateTest(unittest.TestCase):
    @patch("util.zepp_helper.requests.post")
    def test_post_uses_explicit_beijing_date(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"message": "success"}

        ok, _ = zepp_helper.post_fake_brand_data(
            "12345", "app-token", "user-id", data_date="2026-07-20"
        )

        self.assertTrue(ok)
        sent_data = post.call_args.kwargs["data"]
        self.assertIn("date%22%3A%222026-07-20%22", sent_data)

    @patch("util.zepp_helper.requests.post")
    def test_non_200_response_is_ambiguous_not_definitive_failure(self, post):
        post.return_value = Mock(status_code=503)

        with self.assertRaises(zepp_helper.AmbiguousPostError):
            zepp_helper.post_fake_brand_data(
                "12345", "app-token", "user-id", data_date="2026-07-20"
            )


if __name__ == "__main__":
    unittest.main()
