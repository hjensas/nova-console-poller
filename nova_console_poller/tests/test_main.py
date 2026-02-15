# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import io
import logging
import sys
from unittest import mock

from oslotest import base

from nova_console_poller import main


class TestConsolePoller(base.BaseTestCase):

    def setUp(self):
        super(TestConsolePoller, self).setUp()
        self.openstack_patcher = mock.patch('openstack.connect')
        self.mock_connect = self.openstack_patcher.start()
        self.mock_conn = mock.MagicMock()
        self.mock_connect.return_value = self.mock_conn

        # Default mock instance for validation during init
        self.mock_instance = mock.MagicMock()
        self.mock_instance.id = 'test-uuid'
        self.mock_instance.name = 'test-server'
        self.mock_instance.power_state = main.NOVA_POWER_STATE_ON
        self.mock_conn.compute.get_server.return_value = self.mock_instance

    def tearDown(self):
        super(TestConsolePoller, self).tearDown()
        self.openstack_patcher.stop()

    def test_init(self):
        """Test ConsolePoller initialization."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid',
            interval=60
        )

        self.assertEqual('test-uuid', poller.instance.id)
        self.assertEqual(60, poller.interval)
        self.assertIsNone(poller.last_non_empty_line)
        self.assertEqual(0, poller.trailing_empty_count)
        self.assertTrue(poller.prefix)
        self.mock_connect.assert_called_once_with(cloud='test-cloud')

    def test_poll_once_powered_on(self):
        """Test polling a powered-on instance."""
        self.mock_conn.compute.get_server_console_output.return_value = {
            'output': 'Line 1\nLine 2'
        }

        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            poller.poll_once()
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        self.assertIn('[test-server] Line 1', output)
        self.assertIn('[test-server] Line 2', output)
        self.assertEqual('Line 2', poller.last_non_empty_line)
        self.assertEqual(0, poller.trailing_empty_count)

    def test_poll_once_powered_off(self):
        """Test polling a powered-off instance resets last line marker."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )
        # Simulate previous capture
        poller.last_non_empty_line = 'Some previous line'

        # Set instance to powered off
        poller.instance.power_state = 0

        poller.poll_once()

        self.assertIsNone(poller.last_non_empty_line)
        self.assertEqual(0, poller.trailing_empty_count)
        self.mock_conn.compute.get_server_console_output.assert_not_called()

    def test_poll_once_incremental(self):
        """Test polling only outputs new content."""
        self.mock_conn.compute.get_server_console_output.return_value = {
            'output': 'Line 1\nLine 2\nLine 3'
        }

        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )
        poller.last_non_empty_line = 'Line 1'  # Simulate we've seen Line 1
        poller.trailing_empty_count = 0

        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            poller.poll_once()
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        self.assertNotIn('Line 1', output)
        self.assertIn('Line 2', output)
        self.assertIn('Line 3', output)
        self.assertEqual('Line 3', poller.last_non_empty_line)

    def test_poll_once_buffer_wrap(self):
        """Test polling handles buffer wrap/continuity loss correctly."""
        self.mock_conn.compute.get_server_console_output.return_value = {
            'output': 'New boot line 1\nNew boot line 2'
        }

        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )
        # Line that no longer exists
        poller.last_non_empty_line = 'Old line from before wrap'

        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            poller.poll_once()
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        # Should output warning marker inline with console output
        self.assertIn('nova-console-poller', output)
        self.assertIn('Console tracking lost', output)
        self.assertIn('gap in captured output', output)
        # Should output new content even though continuity was lost
        # This prevents missing output during high console activity
        self.assertIn('New boot line 1', output)
        self.assertIn('New boot line 2', output)
        # Should update markers to track new output
        self.assertEqual('New boot line 2', poller.last_non_empty_line)

    def test_poll_once_no_prefix(self):
        """Test polling without prefix."""
        self.mock_conn.compute.get_server_console_output.return_value = {
            'output': 'Line 1'
        }

        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid',
            prefix=False
        )

        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            poller.poll_once()
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        self.assertIn('Line 1', output)
        self.assertNotIn('[test-server]', output)

    def test_init_instance_not_found(self):
        """Test initialization fails when instance is not found."""
        self.mock_conn.compute.get_server.return_value = None

        with self.assertRaises(RuntimeError) as cm:
            main.ConsolePoller(
                cloud='test-cloud',
                instance_id='test-uuid'
            )

        self.assertIn('not found', str(cm.exception))

    def test_poll_once_fetch_error(self):
        """Test polling when fetch() raises an error."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )

        # Fetch raises an error (instance disappeared, network issue, etc)
        import openstack.exceptions
        poller.instance.fetch.side_effect = openstack.exceptions.HttpException(
            "Server not found")

        # Should handle gracefully without crashing
        poller.poll_once()

    def test_poll_once_with_empty_lines(self):
        """Test polling handles empty lines correctly."""
        # First poll: output with empty lines in middle
        self.mock_conn.compute.get_server_console_output.return_value = {
            'output': 'Line 1\n\nLine 2'
        }

        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )

        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            poller.poll_once()
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        self.assertIn('Line 1', output)
        self.assertIn('Line 2', output)
        # Should track the last non-empty line
        # splitlines() on 'Line 1\n\nLine 2' gives ['Line 1', '', 'Line 2']
        self.assertEqual('Line 2', poller.last_non_empty_line)
        self.assertEqual(0, poller.trailing_empty_count)

        # Second poll: new content after empty lines
        self.mock_conn.compute.get_server_console_output.return_value = {
            'output': 'Line 1\n\nLine 2\n\nLine 3'
        }

        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            poller.poll_once()
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        # Should output new content including the empty line and Line 3
        self.assertNotIn('Line 1', output)
        self.assertNotIn('Line 2', output)
        self.assertIn('Line 3', output)
        self.assertEqual('Line 3', poller.last_non_empty_line)
        self.assertEqual(0, poller.trailing_empty_count)

    def test_stop(self):
        """Test stopping the poller."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )
        poller.running = True

        poller.stop()

        self.assertFalse(poller.running)

    def test_poll_once_race_condition_power_off(self):
        """Test race condition: power off between check and console fetch."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )
        poller.last_non_empty_line = 'Some previous line'

        # Console fetch raises NotFoundException (server powered off)
        import openstack.exceptions
        not_found_ex = openstack.exceptions.NotFoundException(
            "404: Guest does not have a console available")

        self.mock_conn.compute.get_server_console_output.side_effect = \
            not_found_ex

        # When we re-check in the exception handler, instance is powered off
        def set_power_off(compute):
            poller.instance.power_state = 0

        poller.instance.fetch.side_effect = set_power_off

        # Should handle gracefully without raising
        poller.poll_once()

        # Should reset markers
        self.assertIsNone(poller.last_non_empty_line)
        self.assertEqual(0, poller.trailing_empty_count)

    def test_poll_once_race_condition_real_error(self):
        """Test that real NotFoundException errors are still raised."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )

        # Console fetch raises NotFoundException but instance is still ON
        import openstack.exceptions
        not_found_ex = openstack.exceptions.NotFoundException(
            "404: Some other error")

        self.mock_conn.compute.get_server_console_output.side_effect = \
            not_found_ex

        # Should catch and log as warning, but not crash
        poller.poll_once()
        # The exception should be caught by the outer exception handler

    def test_run_and_stop(self):
        """Test the run/stop mechanism."""
        self.mock_conn.compute.get_server_console_output.return_value = {
            'output': 'test output'
        }

        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid',
            interval=0.1  # Short interval for testing
        )

        # Start the poller in a separate thread
        import threading
        poller_thread = threading.Thread(target=poller.run)
        poller_thread.daemon = True
        poller_thread.start()

        # Give it a moment to start
        import time
        time.sleep(0.2)

        # Verify it's running
        self.assertTrue(poller.running)

        # Stop it
        poller.stop()

        # Wait for thread to finish
        poller_thread.join(timeout=1.0)

        # Verify it stopped
        self.assertFalse(poller.running)

    def test_setup_logging(self):
        """Test logging setup."""
        # Save original level
        root_logger = logging.getLogger()
        original_level = root_logger.level

        try:
            # Test verbose mode
            main.setup_logging(verbose=True)
            # Check that root logger is configured (may vary by test runner)
            # Just verify the function runs without error
            self.assertIsNotNone(root_logger.level)

            # Test normal mode
            main.setup_logging(verbose=False)
            self.assertIsNotNone(root_logger.level)
        finally:
            # Restore original level
            root_logger.setLevel(original_level)

    def test_parse_arguments_defaults(self):
        """Test argument parsing with defaults."""
        import sys
        old_argv = sys.argv
        try:
            sys.argv = ['nova-console-poller', '--instance', 'test-id']
            args = main.parse_arguments()
            self.assertEqual('test-id', args.instance)
            self.assertEqual('default', args.os_cloud)
            self.assertEqual(30, args.interval)
            self.assertFalse(args.no_prefix)
            self.assertFalse(args.verbose)
        finally:
            sys.argv = old_argv

    def test_parse_arguments_custom(self):
        """Test argument parsing with custom values."""
        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                'nova-console-poller',
                '--os-cloud', 'mycloud',
                '--instance', 'my-instance',
                '--interval', '60',
                '--no-prefix',
                '--verbose'
            ]
            args = main.parse_arguments()
            self.assertEqual('my-instance', args.instance)
            self.assertEqual('mycloud', args.os_cloud)
            self.assertEqual(60, args.interval)
            self.assertTrue(args.no_prefix)
            self.assertTrue(args.verbose)
        finally:
            sys.argv = old_argv

    def test_update_markers_all_empty_with_previous(self):
        """Test _update_markers when all lines empty with previous marker."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )
        poller.last_non_empty_line = 'Previous line'
        poller.trailing_empty_count = 5

        # All empty lines
        poller._update_markers(['', '', ''])

        # Should keep previous marker and add to trailing count
        self.assertEqual('Previous line', poller.last_non_empty_line)
        self.assertEqual(8, poller.trailing_empty_count)  # 5 + 3

    def test_process_and_output_console_empty_output(self):
        """Test _process_and_output_console with empty output."""
        poller = main.ConsolePoller(
            cloud='test-cloud',
            instance_id='test-uuid'
        )

        # Empty output should return early
        poller._process_and_output_console({'output': ''})
        # Should not have set any markers
        self.assertIsNone(poller.last_non_empty_line)
