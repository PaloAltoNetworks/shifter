# Engineering Principles

How we build Shifter.

## Core Philosophy

1. **Keep it simple** - Prefer boring, proven solutions over clever ones
2. **Don't reinvent the wheel** - Use existing tools and patterns
3. **Explicit over implicit** - No magic, no hidden behavior
4. **Fail loudly** - Errors should be obvious, not silent

## No Defaults Policy

**Never provide default values that hide configuration problems.**

Bad:
```python
# Silent failure - uses empty string if missing
db_host = os.getenv("DB_HOST", "")
```

Good:
```python
# Fails immediately if not configured
db_host = os.environ["DB_HOST"]
```

This applies everywhere:
- Environment variables
- Terraform variables
- Function parameters
- API responses

If something is required, make it fail when missing.

## Git Discipline

### Branching
- `main` is production - always deployable
- `dev` is integration - deploy to dev environment
- `feature/*` for development work

### Commits
- Atomic commits (one logical change per commit)
- Descriptive messages (what and why, not how)
- Sign your commits (GPG or SSH)

### Pull Requests
- Small, focused PRs are easier to review
- Include context in description
- Link to relevant issues
- Wait for CI to pass before requesting review

### Never
- Force push to main or dev
- Commit directly to protected branches
- Merge your own PR without review (for significant changes)

## Code Style

### Python
- Format with `ruff format`
- Lint with `ruff check`
- Type hints where helpful (not mandatory everywhere)
- Docstrings for public functions

### Terraform
- Format with `terraform fmt`
- One resource per logical unit
- Meaningful resource names
- Comments for non-obvious configurations

### General
- Prefer readability over cleverness
- Delete dead code, don't comment it out
- Keep functions focused (single responsibility)

## Error Handling

### Do
- Catch specific exceptions
- Log with context (what failed, why, how to fix)
- Return meaningful error messages to users
- Fail fast on unrecoverable errors

### Don't
- Catch and ignore exceptions
- Use bare `except:` clauses
- Swallow errors to make tests pass
- Return generic "something went wrong" messages

## Testing

- Tests are not optional for business logic
- Integration tests for critical paths
- Don't mock what you don't own
- Fast tests run on every commit

## Security

- Secrets never in code or logs
- Validate all user input
- Principle of least privilege for IAM
- HTTPS everywhere, no exceptions

## Documentation

- Document the why, not the what
- Keep docs next to code
- Update docs when behavior changes
- Delete outdated documentation

## Infrastructure as Code

### Terraform
- All infrastructure in Terraform
- No manual changes in console
- State in S3 with locking
- Modules for reusable patterns

### Changes
- Plan before apply
- Review plans in PR
- One environment at a time (dev → prod)

## Dependencies

- Pin versions explicitly
- Update regularly (security patches)
- Minimize dependencies
- Prefer standard library when reasonable

## Monitoring

- Log structured data (JSON)
- Include correlation IDs
- Alert on actionable conditions
- Dashboard for key metrics

## When In Doubt

1. Ask - don't guess at requirements
2. Simplify - complex solutions have complex bugs
3. Document - if you had to figure it out, write it down
4. Review - another pair of eyes catches mistakes
