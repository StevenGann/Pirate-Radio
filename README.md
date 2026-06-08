# Pirate Radio

A Raspberry Pi + Python project. The design document is pending; this repository
currently contains project infrastructure only.

## Status

🚧 **Infrastructure setup.** No application code yet — awaiting the design doc.

## Development

Requires Python 3.11+ (matches Raspberry Pi OS Bookworm's system Python).

```bash
# Create a virtual environment and install dev tooling
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the quality gate locally (mirrors CI)
ruff check .
ruff format --check .
mypy
pytest -m "not hardware"
```

### Testing philosophy

We follow a TDD workflow. Tests run on every push and PR via GitHub Actions
(`.github/workflows/ci.yml`) against Python 3.11 and 3.12, with an enforced
**80% coverage floor**.

Because CI has no Raspberry Pi hardware, hardware-dependent tests are marked
`@pytest.mark.hardware` and excluded from the CI run. All hardware access must
sit behind an abstraction layer so the bulk of the code is testable on any
machine. See `docs/agents/qa-engineer.md`.

## Project governance

Development decisions are reviewed by a standing panel of specialist review
agents coordinated through a structured brief → distill → vote workflow. See
[`docs/agents/README.md`](docs/agents/README.md).
