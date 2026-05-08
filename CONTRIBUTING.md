# Contributing to Metriplex

Thank you for your interest in contributing.

## Areas where help is most needed

- **Rust rewrite** of `core/dynamics.py` and `core/verifier.py` (100x performance target)
- **Dashboard** (`caf-dashboard/`) — currently a React scaffold, needs real API integration
- **Tests** — expand `tests/` with adversarial criterion tests and chain simulation tests
- **Documentation** — translate whitepaper, improve API docs

## How to contribute

1. Fork the repository
2. Create a branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run tests: `pytest tests/`
5. Submit a pull request with a clear description

## Code style

- Python: follow PEP 8, use type hints where practical
- Solidity: follow the existing NatSpec comment style
- Commit messages: `module: brief description` (e.g., `core: fix Rc calculation`)

## Security issues

Please do **not** open public issues for security vulnerabilities.  
Contact: ntellezm@gmail.com
