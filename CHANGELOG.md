# Changelog

## [Unreleased]

## [0.0.1] - 2026-02-15

### Overview

nova-console-poller is a new lightweight utility that polls OpenStack Nova
instance console output and streams new content to stdout. It provides a
simple polling-based alternative to Nova's serial console proxy for clouds
that don't have real-time serial console streaming enabled. The tool is
designed to run as one process per instance, making it ideal for deployment
as systemd units or Kubernetes pods.

### Added

- Initial release of nova-console-poller with the following capabilities:
  - Polls Nova API `GET /servers/{id}/action (os-getConsoleOutput)` at
    configurable intervals (default 30 seconds)
  - Tracks previously seen output using an offset pointer and only streams
    new console lines to stdout
  - Optionally prefixes each line with the instance name for easy log
    filtering in multi-instance deployments
  - Handles console buffer wraps gracefully by detecting when output length
    decreases and automatically resetting the offset
  - Detects instance power state changes and resets offset when instances
    power off or reboot
  - Provides graceful shutdown via SIGTERM and SIGINT signal handlers
  - Supports standard OpenStack configuration via clouds.yaml files
  - Includes comprehensive unit tests with mock-based testing using oslotest

- Command-line interface with the following options:
  - `--os-cloud`: OpenStack cloud name from clouds.yaml (required)
  - `--instance`: Nova instance UUID to poll (required)
  - `--interval`: Poll interval in seconds (default: 30)
  - `--no-prefix`: Disable instance name prefix on output lines
  - `--verbose`: Enable debug logging

- Easy deployment patterns for both systemd and Kubernetes/OpenShift
  environments are documented in the README, with template configurations
  showing how to run one poller process per instance
