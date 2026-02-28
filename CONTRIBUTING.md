# Contributing to D-MemFS

Thank you for your interest in contributing! This document explains how to get involved.

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/D-MemFS.git
   cd D-MemFS
   ```
3. **Install dependencies** using [uv](https://github.com/astral-sh/uv):
   ```bash
   uv pip compile requirements.in -o requirements.txt
   ```
4. **Run the test suite** to confirm everything passes:
   ```bash
   uvx --with-requirements requirements.txt --with-editable . pytest tests/ -v --timeout=30
   ```

## Development Workflow

- Create a **feature branch**: `git checkout -b feat/my-feature`
- Write tests **before** or **alongside** code changes.
- All tests must pass before submitting a PR.
- Keep commits focused and use descriptive commit messages.

## Code Style

- Follow existing patterns — no additional linting tools are required.
- Public APIs must have type annotations.
- New public methods must be documented in the docstring and, if applicable, reflected in `README.md` / `README_ja.md`.

## Submitting a Pull Request

1. Push your branch to your fork.
2. Open a Pull Request against the `main` branch.
3. Describe **what** you changed and **why**.
4. Link any related issues.

## Reporting Bugs

Please open a GitHub Issue with:
- A minimal reproducible example
- Python version and OS
- Expected vs. actual behaviour

## Design Principles

Before proposing new features, please review the [Non-Goals](README.md) section.
MFS intentionally avoids `os.PathLike` compatibility and does not aim to replace `os` or `pathlib`.
