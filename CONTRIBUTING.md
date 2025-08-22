# Contributing to ITGlue to SuperOps Migration Tool

We welcome contributions to improve this migration tool! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a virtual environment
4. Install dependencies
5. Create a new branch for your feature

## Development Setup

```bash
# Clone the repo
git clone https://github.com/yourusername/itglue-superops-migrator.git
cd itglue-superops-migrator

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest pytest-cov black flake8
```

## Code Style

- Follow PEP 8 Python style guidelines
- Use Black for code formatting
- Maximum line length: 100 characters
- Use type hints where appropriate
- Add docstrings to all functions and classes

## Making Changes

1. Create a new branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes
3. Add tests for new functionality
4. Run tests locally:
   ```bash
   pytest tests/
   ```

5. Format your code:
   ```bash
   black migrator/
   ```

6. Check for linting issues:
   ```bash
   flake8 migrator/
   ```

## Testing

- Write unit tests for new functions
- Ensure all tests pass before submitting PR
- Aim for at least 80% code coverage
- Include integration tests for API interactions

## Commit Guidelines

- Use clear, descriptive commit messages
- Follow conventional commits format:
  - `feat:` for new features
  - `fix:` for bug fixes
  - `docs:` for documentation changes
  - `test:` for test additions/changes
  - `refactor:` for code refactoring

Example:
```
feat: add retry logic for API rate limiting

- Implement exponential backoff
- Add configurable max retries
- Log retry attempts
```

## Pull Request Process

1. Update documentation for any new features
2. Update README.md if necessary
3. Ensure all tests pass
4. Update CHANGELOG.md with your changes
5. Submit PR with clear description of changes
6. Link any related issues

## Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] Tests added/updated
```

## Reporting Issues

When reporting issues, please include:

1. Python version
2. Operating system
3. Full error traceback
4. Steps to reproduce
5. Expected vs actual behavior
6. Sample data (if applicable)

## Security

If you discover a security vulnerability:
- Do NOT open a public issue
- Email security@wyre.technology
- Include detailed description and steps to reproduce

## Community Guidelines

- Be respectful and inclusive
- Welcome newcomers
- Provide constructive feedback
- Help others when possible
- Follow our Code of Conduct

## Questions?

- Open a discussion in GitHub Discussions
- Check existing issues and PRs
- Review documentation first

Thank you for contributing!