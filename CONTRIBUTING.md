# Contributing to nova-console-poller

Thank you for your interest in contributing to nova-console-poller!

## Development Setup

Clone the repository and install in development mode:

```bash
git clone https://github.com/hjensas/nova-console-poller.git
cd nova-console-poller
pip install -e .
```

## Running Tests

We use tox for testing across different Python versions:

```bash
# Install tox
pip install tox

# Run all tests
tox

# Run only unit tests
tox -e py3

# Run pep8/linting
tox -e pep8
```

## Running Locally for Development

You can run the tool locally using the tox virtual environment without installing it:

```bash
# Create a fresh venv and activate it
tox -e venv && cd .tox/venv/ && . bin/activate

# Run the tool
nova-console-poller --os-cloud mycloud --instance <instance-uuid>

# Or run it directly with python
python -m nova_console_poller.main --os-cloud mycloud --instance <instance-uuid>

# When done, deactivate
deactivate
```

Alternatively, run directly from the tox environment without activating:

```bash
.tox/py3/bin/nova-console-poller --os-cloud mycloud --instance <instance-uuid>
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests to ensure everything passes
5. Commit your changes with clear commit messages
6. Push to your fork and submit a pull request

## Code Style

This project follows Python PEP 8 style guidelines. Please ensure your code passes the linting tests before submitting.

## License

By contributing to this project, you agree that your contributions will be licensed under the Apache License 2.0.
