import contextlib
import io
import unittest
from hosted_app import BoundedServer


class PrivateLoggingTest(unittest.TestCase):
    def test_unexpected_socket_error_does_not_log_client_address(self):
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            BoundedServer.handle_error(object(), object(), ('198.51.100.9', 12345))
        self.assertEqual(stream.getvalue(), 'Playtest request failed; inspect private operational health.\n')
        self.assertNotIn('198.51.100.9', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
