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

import argparse
import logging
import os
import signal
import sys
import time

import openstack


LOG = logging.getLogger(__name__)

# Nova power state constant
NOVA_POWER_STATE_ON = 1

# Minimum recommended poll interval (seconds)
MIN_RECOMMENDED_INTERVAL = 10


class ConsolePoller:
    """Polls Nova instance console output and streams to stdout."""

    def __init__(self, cloud, instance_id, interval=30, prefix=True):
        """Initialize the console poller.

        :param cloud: OpenStack cloud name or connection
        :param instance_id: Nova instance UUID to poll
        :param interval: Poll interval in seconds (default 30)
        :param prefix: Whether to prefix lines with instance name
        :raises: RuntimeError if instance is not found at startup
        """
        self.interval = interval
        self.prefix = prefix
        self.last_non_empty_line = None
        self.trailing_empty_count = 0
        self.running = False

        LOG.info('Connecting to OpenStack cloud: %(cloud)s',
                 {'cloud': cloud})
        self.conn = openstack.connect(cloud=cloud)

        # Validate that the instance exists at startup and store it
        LOG.info('Validating instance: %(id)s', {'id': instance_id})
        self.instance = self.conn.compute.get_server(instance_id)
        if self.instance is None:
            raise RuntimeError(
                f'Instance {instance_id} not found. '
                'Please verify the instance UUID is correct.'
            )
        LOG.info('Successfully validated instance: %(name)s (%(id)s)',
                 {'name': self.instance.name, 'id': self.instance.id})

    def _get_console_output(self):
        """Get console output from the instance.

        Returns console output dict or None if console is unavailable
        due to instance power state.

        :raises: openstack.exceptions for errors other than power-off
        """
        try:
            return self.conn.compute.get_server_console_output(
                self.instance.id)
        except openstack.exceptions.NotFoundException:
            # Console not available - check if it's because instance is
            # powered off (race condition between power state check and
            # console fetch)
            self.instance.fetch(self.conn.compute)
            if self.instance.power_state != NOVA_POWER_STATE_ON:
                LOG.debug('Console unavailable for %(id)s - '
                          'instance not powered on (state=%(state)s)',
                          {'id': self.instance.id,
                           'state': self.instance.power_state})
                return None
            # If we get here, it's a real error (not power-related) - re-raise
            raise

    def _print_line(self, line):
        """Print a line to stdout with optional instance name prefix.

        :param line: The line to print
        """
        if self.prefix:
            print('[%s] %s' % (self.instance.name, line))
        else:
            print(line)

    def _process_and_output_console(self, console_output):
        """Process console output and print new content.

        :param console_output: Console output dict from OpenStack API
        """
        output_text = console_output.get('output', '')
        lines = output_text.splitlines()

        if not lines:
            # No output or only whitespace
            return

        # Determine what new content to output
        new_lines = self._get_new_lines(lines)

        if not new_lines:
            # No new content
            return

        # Print new content
        for line in new_lines:
            self._print_line(line)
        sys.stdout.flush()

        # Update markers for next poll
        self._update_markers(lines)

    def _get_new_lines(self, lines):
        """Determine which lines are new since last poll.

        :param lines: List of all console output lines from current poll
        :returns: List of new lines to output, or None if buffer wrapped
        """
        # If this is the first poll, output everything
        if self.last_non_empty_line is None:
            LOG.debug('First poll for %(id)s, outputting all content',
                      {'id': self.instance.id})
            return lines

        # Find where we left off by looking for the last non-empty line
        # Search backwards to find the most recent match
        for i in range(len(lines) - 1, -1, -1):
            if lines[i] == self.last_non_empty_line:
                # Found it! Skip past the marker and trailing empties
                continuation_index = i + self.trailing_empty_count + 1
                return lines[continuation_index:]
        else:
            # Last line not found - buffer wrapped or instance rebooted
            LOG.warning('Console buffer wrapped for instance %(id)s. '
                        'Previous output marker not found - some messages '
                        'may have been lost. Outputting all current buffer '
                        'content.',
                        {'id': self.instance.id})
            # Output warning marker to stdout so it appears in captured logs
            marker = ('*** nova-console-poller: Console tracking lost - '
                      'gap in captured output ***')
            self._print_line(marker)
            sys.stdout.flush()
            # Return all current content to avoid missing active console output
            return lines

    def _update_markers(self, lines):
        """Update tracking markers from lines.

        :param lines: List of console output lines (non-empty)
        """
        # Find the last non-empty line by searching backwards
        # range(start, stop, step): from last index down to 0, stepping by -1
        for i in range(len(lines) - 1, -1, -1):
            if lines[i]:  # Found a non-empty line
                self.last_non_empty_line = lines[i]
                self.trailing_empty_count = len(lines) - 1 - i
                break
        else:
            # All lines are empty (rare but possible)
            # Keep existing markers unchanged so next poll can continue
            if self.last_non_empty_line is not None:
                # We have a previous marker, add to trailing empty count
                self.trailing_empty_count += len(lines)
            # else: first poll with all empties - keep None/0 values

    def poll_once(self):
        """Poll console output once and print new content."""
        # Get instance info and console output (OpenStack API calls)
        try:
            # Fetch fresh state from Nova API to avoid race conditions
            # This ensures we have real-time power_state before checking it
            self.instance.fetch(self.conn.compute)

            if self.instance.power_state != NOVA_POWER_STATE_ON:
                LOG.debug('Instance %(id)s not powered on (state=%(state)s), '
                          'resetting last line marker',
                          {'id': self.instance.id,
                           'state': self.instance.power_state})
                self.last_non_empty_line = None
                self.trailing_empty_count = 0
                return

            console_output = self._get_console_output()

            # Console unavailable due to power state race condition
            if console_output is None:
                self.last_non_empty_line = None
                self.trailing_empty_count = 0
                return

        except openstack.exceptions.HttpException as ex:
            LOG.warning('HTTP error polling console for %(id)s: %(error)s',
                        {'id': self.instance.id, 'error': ex})
            return
        except Exception as ex:
            LOG.warning('Error polling console for %(id)s: %(error)s',
                        {'id': self.instance.id, 'error': ex})
            return

        # Process and output console content
        self._process_and_output_console(console_output)

    def run(self):
        """Run the polling loop."""
        self.running = True
        LOG.info('Starting console poller with %(interval)s second interval',
                 {'interval': self.interval})

        while self.running:
            self.poll_once()

            # Sleep in smaller chunks to be responsive to stop signals
            # This allows Ctrl+C to exit within 1 second instead of waiting
            # for the full interval
            sleep_remaining = self.interval
            while sleep_remaining > 0 and self.running:
                time.sleep(min(1, sleep_remaining))
                sleep_remaining -= 1

    def stop(self):
        """Stop the polling loop."""
        LOG.info('Stopping console poller')
        self.running = False


def setup_logging(verbose=False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def parse_arguments():
    """Parse command-line arguments.

    :returns: Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description='Poll OpenStack Nova instance console output and stream '
                    'to stdout. Designed to run as one process per instance.'
    )
    parser.add_argument(
        '--os-cloud',
        default=os.environ.get('OS_CLOUD', 'default'),
        help='OpenStack cloud name from clouds.yaml '
             '(env: OS_CLOUD, default: default)'
    )
    parser.add_argument(
        '--instance',
        default=os.environ.get('INSTANCE_UUID'),
        required=not os.environ.get('INSTANCE_UUID'),
        help='Nova instance UUID to poll (env: INSTANCE_UUID)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=int(os.environ.get('POLL_INTERVAL', '30')),
        help='Poll interval in seconds (env: POLL_INTERVAL, default: 30)'
    )
    parser.add_argument(
        '--no-prefix',
        action='store_true',
        default=os.environ.get('NO_PREFIX', '').lower() in (
            'true', '1', 'yes'),
        help='Do not prefix output lines with instance name (env: NO_PREFIX)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        default=os.environ.get('VERBOSE', '').lower() in (
            'true', '1', 'yes'),
        help='Enable verbose (debug) logging (env: VERBOSE)'
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()

    setup_logging(verbose=args.verbose)

    if args.interval < MIN_RECOMMENDED_INTERVAL:
        LOG.warning('Poll interval %(interval)s is below recommended minimum '
                    'of %(min)s seconds, this may cause excessive API load',
                    {'interval': args.interval,
                     'min': MIN_RECOMMENDED_INTERVAL})

    poller = ConsolePoller(
        cloud=args.os_cloud,
        instance_id=args.instance,
        interval=args.interval,
        prefix=not args.no_prefix
    )

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        LOG.info('Received signal %(signal)s, shutting down',
                 {'signal': signum})
        poller.stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        poller.run()
    except KeyboardInterrupt:
        poller.stop()

    return 0


if __name__ == '__main__':
    sys.exit(main())
