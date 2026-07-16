import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from util import push_util


class TelegramPushLoggingTest(unittest.TestCase):
    @patch("util.push_util.requests.post")
    def test_sensitive_telegram_values_are_not_logged(self, post):
        post.return_value = Mock(status_code=403)
        bot_token = "123456789:secret-token-value"
        chat_id = "987654321"
        content = "private account push content"

        output = io.StringIO()
        with redirect_stdout(output):
            push_util.push_telegram_bot(bot_token, chat_id, content)

        log_output = output.getvalue()
        self.assertNotIn(bot_token, log_output)
        self.assertNotIn(chat_id, log_output)
        self.assertNotIn(content, log_output)
        self.assertIn("telegram bot推送失败: 403", log_output)


if __name__ == "__main__":
    unittest.main()
