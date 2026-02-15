# nova-console-poller

A lightweight utility that polls OpenStack Nova instance console output and
streams new content to stdout. Designed to run as one process per instance,
making it easy to deploy as systemd units or Kubernetes pods.

## Why?

Nova supports real-time serial console streaming via
`openstack console url show --serial`, but this requires specific cloud
configuration (serial console proxy) that many clouds don't have enabled.
This tool provides a simple polling-based alternative that works with any
Nova deployment.

## How it works

- Polls `GET /servers/{id}/action (os-getConsoleOutput)` at a configurable
  interval
- Tracks the last non-empty line seen and only prints new content by searching
  for the continuation point in each poll
- If continuity is lost (buffer wrap or reboot), logs a warning and outputs
  all current buffer content (some output may be lost if buffer has wrapped)
- Prefixes each line with the instance name for easy filtering
- Outputs to stdout - let systemd journal or container runtime handle log
  collection
- Handles instance power state changes by resetting tracking when instances
  power off

## Installation

```bash
pip install nova-console-poller
```

Or install from source:

```bash
git clone https://github.com/hjensas/nova-console-poller.git
cd nova-console-poller
pip install .
```

## Usage

```bash
# Stream console for a single instance (uses 'default' cloud)
nova-console-poller --instance <uuid>

# Specify a cloud from clouds.yaml
nova-console-poller --os-cloud mycloud --instance <uuid>

# With custom interval (default 30s)
nova-console-poller --os-cloud mycloud --instance <uuid> --interval 60

# Without instance name prefix
nova-console-poller --os-cloud mycloud --instance <uuid> --no-prefix

# Verbose logging
nova-console-poller --os-cloud mycloud --instance <uuid> --verbose

# Using environment variables
export OS_CLOUD=mycloud
export INSTANCE_UUID=<uuid>
nova-console-poller
```

### Options

| Option | Environment Variable | Description |
|--------|---------------------|-------------|
| `--os-cloud` | `OS_CLOUD` | OpenStack cloud name from clouds.yaml (default: default) |
| `--instance` | `INSTANCE_UUID` | Nova instance UUID to poll (required unless env var set) |
| `--interval` | `POLL_INTERVAL` | Poll interval in seconds (default: 30) |
| `--no-prefix` | `NO_PREFIX` | Do not prefix output lines with instance name |
| `--verbose` | `VERBOSE` | Enable verbose (debug) logging |

**Note**: Command-line arguments take precedence over environment variables.

## Container Usage

### Building the container

```bash
podman build -t nova-console-poller:latest -f Containerfile .
```

### Running the container

```bash
podman run --rm \
  -v /path/to/clouds.yaml:/etc/openstack/clouds.yaml:ro \
  nova-console-poller:latest \
  --os-cloud mycloud --instance <instance-uuid>
```

**Note**: The tool requires a `clouds.yaml` file. If you need to keep credentials out of
your `clouds.yaml`, you can use environment variable references like `${OS_PASSWORD}` in
the YAML, then pass those variables with `-e` flags to the container.

## Deployment

### Systemd (one unit per instance)

Create a template unit file `/etc/systemd/system/nova-console-poller@.service`:

```ini
[Unit]
Description=Nova Console Poller for %i
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/nova-console-poller --os-cloud mycloud --instance %i
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then start and enable for each instance:

```bash
systemctl enable --now nova-console-poller@<instance-uuid>.service

# View logs
journalctl -u nova-console-poller@<instance-uuid> -f
```

### Kubernetes/OpenShift (one pod per instance)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nova-console-poller-myinstance
spec:
  containers:
  - name: poller
    image: your-registry/nova-console-poller:latest
    env:
    - name: OS_CLOUD
      value: mycloud
    - name: INSTANCE_UUID
      value: <instance-uuid>
    volumeMounts:
    - name: clouds-config
      mountPath: /etc/openstack
      readOnly: true
  volumes:
  - name: clouds-config
    secret:
      secretName: openstack-clouds
```

Create the secret from your `clouds.yaml` file:

```bash
kubectl create secret generic openstack-clouds --from-file=clouds.yaml=/path/to/clouds.yaml
```

Example `clouds.yaml` structure:

```yaml
clouds:
  mycloud:
    auth:
      auth_url: https://keystone.example.com:5000/v3
      username: admin
      password: secretpassword
      project_name: admin
      user_domain_name: Default
      project_domain_name: Default
    region_name: RegionOne
```

View logs:

```bash
kubectl logs -f nova-console-poller-myinstance
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and testing instructions.

## License

Apache License 2.0
