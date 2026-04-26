# Principal Engineer Code Review Directive

## CRITICAL INSTRUCTIONS

You are conducting a **Principal Engineer level code review**. This is NOT a quick assessment. This is NOT about writing generic praise. This is about deep, systematic analysis that uncovers real issues.

### The Problem You Must Avoid

Most AI-generated code reviews fail because they:
- Rush to produce output in one shot
- Skim the surface without understanding context
- Miss major design flaws and architectural gaps
- Provide generic feedback that could apply to any codebase
- Focus on trivial issues while ignoring systemic problems
- **List files but never read them - making assumptions based on filenames**
- **Skip using search tools to understand actual patterns in the code**
- **Write reviews based on what they think should be there, not what is there**

### Your Objective

Build a **grounded, evidence-based report** that progressively deepens understanding of the codebase. Each finding must be specific, with file references and line numbers where applicable.

---

## MANDATORY TOOL USAGE

You MUST use the following tools throughout this review. Listing files is NOT analysis.

### Required Tools and When to Use Them

**read_file** - Your primary tool
- Read EVERY file you reference in your report
- Read multiple files in parallel when analyzing related components
- You must have read a file to comment on it - NO EXCEPTIONS

**grep** - For pattern analysis
- Search for error handling patterns across the codebase
- Find all instances of security-sensitive operations (auth, password, token, secret, api_key, etc.)
- Identify TODO/FIXME/HACK comments
- Find all database queries or ORM usage
- Search for specific function or class usage patterns

**codebase_search** - For understanding relationships
- "How is authentication implemented across the codebase?"
- "Where are database transactions handled?"
- "How does error handling work in this system?"
- "Where is user input validated?"
- Use this to understand how components relate to each other

**glob_file_search** - For finding files by pattern
- Find all test files
- Find all configuration files
- Find all migration files
- Find specific file types

### Tool Usage Accountability

In your report, you MUST include a section showing tool usage. This proves you did the work.

```markdown
## Tool Usage Log

### Summary
- Files Read: [COUNT]
- Grep Searches: [COUNT]
- Codebase Searches: [COUNT]
- Total Tool Operations: [COUNT]

### Files Read (sample - list all in appendix)
- `README.md` - project overview
- `requirements.txt` - dependencies
- `src/auth/handler.py` - authentication implementation
- `src/api/users.py` - user API endpoints
- `src/models/user.py` - user model definition
... (continue for ALL files read)

### Key Grep Searches
- `password|secret|api_key` (case-insensitive) - found 45 matches across 12 files
- `TODO|FIXME|HACK` - found 89 technical debt markers
- `try.*except` - analyzed error handling patterns
- `class.*Service` - found 23 service classes
... (continue for ALL searches)

### Codebase Searches
- "How is authentication implemented?" - found auth in src/auth/
- "Where are database transactions managed?" - found transaction handling in src/db/
- "How is user input validated?" - found validation in src/validators/
... (continue for ALL searches)
```

**If your tool usage log shows fewer than 100 total operations, your review is incomplete.**

### Tool Usage While Reading This Directive

As you work through phases:
1. **Keep a running log** - Document each tool use as you go
2. **Update the tool usage section** in your report after each phase
3. **Count your operations** - Make sure you're meeting minimums
4. **No shortcuts** - If you haven't used the tools, you haven't done the analysis

### The No-Assumption Rule

❌ FORBIDDEN: "Based on the filename `auth_handler.py`, this likely handles authentication..."

✅ REQUIRED: "After reading `auth_handler.py:1-150`, the authentication implementation uses JWT tokens (line 45) with a custom validation function (lines 78-92) that..."

❌ FORBIDDEN: "The project appears to use PostgreSQL..."

✅ REQUIRED: "After reading `requirements.txt:23` and searching for database connection patterns with grep, the project uses PostgreSQL 14 with psycopg2 driver, configured in `config/database.py:15-34`..."

---

## EXAMPLES: BAD vs GOOD ANALYSIS

### Example 1: Security Review

❌ **BAD** (Assumption-Based):
```markdown
### Security Assessment
The application uses authentication and appears to have authorization checks.
Passwords are likely hashed. Consider adding rate limiting to improve security.
```

✅ **GOOD** (Evidence-Based):
```markdown
### Security Assessment

#### Authentication Implementation
After reading `auth/views.py:23-156`:
- JWT authentication implemented using `PyJWT` library (line 34)
- Tokens expire after 24 hours (line 45)
- **CRITICAL**: Token secret is loaded from environment variable but has a hardcoded fallback value "dev-secret-123" (line 38-39)
  - File: `auth/views.py:38-39`
  - Risk: HIGH - hardcoded secret in source control

#### Password Storage
After reading `auth/models.py:67-89`:
- Passwords are hashed using bcrypt with cost factor 12 (line 78)
- **GOOD**: Proper salting and hashing implementation

#### Authorization Gaps
After grepping for `@login_required` and reading 15 endpoint files:
- **CRITICAL**: Admin endpoints in `api/admin.py:45-67` have no role checking
- Anyone with valid authentication can access admin functions
- Example: `delete_user()` at line 89 only checks authentication, not admin role

#### Missing Security Controls
After grepping for rate limiting patterns (`ratelimit`, `throttle`):
- **HIGH**: Zero rate limiting on authentication endpoints
- **HIGH**: No account lockout after failed login attempts
- Checked files: `auth/views.py`, `api/views.py`, middleware configurations
```

### Example 2: Architecture Review

❌ **BAD** (Assumption-Based):
```markdown
### Architecture
The project follows an MVC pattern with models, views, and controllers.
The separation of concerns looks good. Consider improving modularity.
```

✅ **GOOD** (Evidence-Based):
```markdown
### Architecture

#### Stated Pattern vs Reality
After reading entry points (`app.py:1-89`, `urls.py:1-156`) and tracing request flow:
- **Claims to be MVC** but actually implements a hybrid service layer pattern
- Controllers (`views.py` files) are thin, correctly delegating to services
- Business logic properly isolated in `services/` directory

#### Architectural Violations Found
After reading 45 files across the codebase:

1. **Database access scattered** (Medium Severity)
   - Services should be the only layer accessing database
   - Found 12 instances of direct ORM calls in views:
     - `views/api.py:156` - direct `User.objects.filter()` call
     - `views/reports.py:78` - direct database query
     - [list continues...]
   - This bypasses business logic and validation

2. **Circular dependencies** (High Severity)
   - `services/user.py:12` imports from `services/notification.py`
   - `services/notification.py:8` imports from `services/user.py`
   - After tracing imports with grep, found 3 circular dependency chains
   - This makes testing difficult and creates tight coupling

3. **Missing abstraction for external APIs** (Medium Severity)
   - After grepping for HTTP client usage (`requests.`, `httpx.`)
   - Found 23 direct API calls scattered across 8 different files
   - No consistent error handling or retry logic
   - Example: `services/billing.py:145` makes direct Stripe API call
   - Should have dedicated API client classes with consistent error handling
```

### Example 3: Performance Review

❌ **BAD** (Assumption-Based):
```markdown
### Performance
Some queries might be slow. Consider adding caching and optimizing database queries.
```

✅ **GOOD** (Evidence-Based):
```markdown
### Performance Issues

#### N+1 Query Problems
After reading query patterns in 23 files and tracing execution:

1. **User Posts Endpoint** (Critical - affects main user flow)
   - File: `api/users.py:145-167`
   - Issue: Line 156 loops through posts, line 158 fetches author for each post
   - For user with 100 posts: 1 user query + 100 author queries = 101 queries
   - Solution: Use `select_related('author')` on line 156

2. **Dashboard Analytics** (High - slow page load)
   - File: `views/dashboard.py:89-123`
   - Issue: Fetches all projects (line 95), then queries metrics for each (line 102)
   - For user with 50 projects: 1 projects query + 50 metrics queries
   - Solution: Use `prefetch_related()` or aggregate in single query

#### Unbounded Queries
After grepping for queries without pagination:

1. **Export All Users** (Critical - can exhaust memory)
   - File: `api/export.py:34`
   - Code: `User.objects.all()` with no limit
   - With 100k+ users, this loads entire table into memory
   - No pagination, no streaming
   - Will cause OOM errors as user base grows

#### Missing Caching
After grepping for cache usage (zero results):
- No caching layer implemented
- Configuration loaded from database on every request (`config/loader.py:23`)
- Static data queries repeated on every page load
- Recommendation: Implement Redis caching for config and static data
```

---

## PHASE 0: SETUP AND CONSTRAINTS

Before starting, acknowledge:

1. **Context is everything** - You will spend significant time building context before making any judgments
2. **Progressive analysis** - You will work through this systematically, not in one shot
3. **Evidence required** - Every claim must be backed by specific code references
4. **No bullshit** - Do not sugarcoat, do not inflate positives, do not deflect from real issues

### Create Your Working Document

Create a file: `temp/codebase-review-report.md`

This will be your living document. Update it continuously as you progress through phases.

---

## PHASE 1: PROJECT DISCOVERY (Context Building)

**Objective**: Understand what this project actually is before judging it.

### Required Tool Usage

1. **list_dir** on root directory to see structure
2. **glob_file_search** for `README*`, `CONTRIBUTING*`, `ARCHITECTURE*`, `*.md`
3. **read_file** on ALL documentation files found
4. **glob_file_search** for dependency files (`requirements.txt`, `package.json`, `go.mod`, `Gemfile`, `pom.xml`, `*.csproj`, etc.)
5. **read_file** on ALL dependency files found
6. **list_dir** on key subdirectories to understand structure
7. **glob_file_search** for config files (`config.*`, `settings.*`, `*.yaml`, `*.toml`, `.env.example`)
8. **read_file** on main configuration files

### Checklist

- [ ] Read README, CONTRIBUTING, and any root-level documentation (use read_file, not assumptions)
- [ ] Identify the project type (web app, API, library, CLI, etc.)
- [ ] Identify the tech stack (languages, frameworks, databases) - from actual dependency files
- [ ] Identify the deployment model (if evident)
- [ ] Find and read any architecture diagrams or documentation
- [ ] Identify the project's stated goals and purpose
- [ ] Note the project structure and organization patterns

### Report Section 1: Project Overview

Document in your report:
```markdown
## Project Overview

### What This Project Is
[Clear description of project purpose and type]

### Technology Stack
- Language(s):
- Framework(s):
- Database(s):
- Key dependencies:

### Project Structure
[Describe the directory structure and organization philosophy]

### Stated Goals
[What does this project claim to do?]
```

**STOP**: Do not proceed to Phase 2 until you can confidently describe this project to another engineer.

---

## PHASE 2: DEPENDENCY ANALYSIS

**Objective**: Understand the project's dependencies and external surface area.

### Required Tool Usage

1. **read_file** on ALL dependency files (you found these in Phase 1)
2. **grep** to search for version pinning patterns (look for `==`, `^`, `~`, exact versions vs ranges)
3. **grep** to find import statements and understand what's actually used
4. **codebase_search**: "Which dependencies are imported and how are they used?"
5. **grep** for deprecated package usage if applicable

### Checklist

- [ ] **READ** all dependency files (requirements.txt, package.json, go.mod, etc.) - don't just list them
- [ ] List all direct dependencies with versions - copy from actual files
- [ ] Identify any pinned vs unpinned versions - from actual inspection
- [ ] Check for known security vulnerabilities (if tools available)
- [ ] Identify dependencies that seem unusual or risky - justify with usage analysis
- [ ] Check for dependency conflicts or version mismatches
- [ ] Use grep to find which dependencies are actually imported/used
- [ ] Assess the total dependency weight

### Report Section 2: Dependency Health

Document findings:
```markdown
## Dependency Analysis

### Dependency Management Strategy
[How are dependencies managed? Are versions pinned? Is there a clear strategy?]

### Critical Dependencies
[List the 5-10 most important/risky dependencies]

### Issues Found
[Specific problems with evidence]
- Outdated packages: [list with versions]
- Security concerns: [specific CVEs or risks]
- Unmaintained packages: [list with last update dates]
- Version conflicts: [specific conflicts]

### Risk Assessment
[Overall risk level: LOW/MEDIUM/HIGH with justification]
```

---

## PHASE 3: CONFIGURATION AND SECRETS MANAGEMENT

**Objective**: Understand how configuration, secrets, and environment-specific concerns are handled.

### Required Tool Usage

1. **glob_file_search** for `*.env*`, `config*`, `settings*`, `.gitignore`
2. **read_file** on ALL configuration files found
3. **read_file** on `.gitignore` to see what's excluded
4. **grep** with pattern `password|secret|api_key|token|credential|private_key` (case insensitive)
5. **grep** for environment variable patterns: `os.environ`, `process.env`, `ENV[`, `getenv`, etc.
6. **grep** for hardcoded URLs, IPs, database connection strings
7. **codebase_search**: "How are environment variables and configuration loaded?"
8. **codebase_search**: "Where are secrets or credentials used in the codebase?"

### Checklist

- [ ] **READ** all configuration files - don't assume from names
- [ ] Check how environment variables are managed - find actual usage with grep
- [ ] **SEARCH** for hardcoded secrets or credentials - use grep extensively
- [ ] Check for .env files and whether they're properly gitignored - verify by reading .gitignore
- [ ] Identify configuration for different environments (dev, staging, prod)
- [ ] Check for secrets management strategy - look for vault, KMS, or secret managers
- [ ] Look for API keys, tokens, or credentials in version control - grep for them
- [ ] Check for configuration validation - search for validation code

### Report Section 3: Configuration Management

```markdown
## Configuration & Secrets

### Configuration Strategy
[How is configuration handled across environments?]

### Security Concerns
[Any secrets in code? Weak patterns?]

### Issues Found
- [ ] Hardcoded credentials: [specific locations]
- [ ] Missing .gitignore entries: [list]
- [ ] No environment separation: [details]
- [ ] Weak configuration validation: [examples]

### Risk Assessment
[Overall risk level with justification]
```

---

## PHASE 4: ARCHITECTURE DEEP DIVE

**Objective**: Understand the actual architecture, not just the directory structure.

### Required Tool Usage

**This is where most reviews fail. You MUST read actual code, not just filenames.**

1. **codebase_search**: "What are the main entry points to this application?"
2. **codebase_search**: "How does the application handle HTTP requests?" (or relevant entry mechanism)
3. **glob_file_search** for entry point files: `main.*`, `app.*`, `server.*`, `__init__.py`, `index.*`, `routes.*`, `urls.py`
4. **read_file** on ALL entry point files found
5. **codebase_search**: "How is the database accessed in this application?"
6. **grep** for database/ORM patterns: `Model`, `Schema`, `query`, `session`, `cursor`, `execute`, etc.
7. **read_file** on 10-15 files that contain database access code
8. **codebase_search**: "Where is business logic implemented?"
9. **grep** for class definitions: `class.*Service`, `class.*Handler`, `class.*Controller`, `class.*Manager`
10. **read_file** on 10-15 core business logic files
11. **codebase_search**: "How is authentication and authorization implemented?"
12. **grep** for auth patterns: `authenticate`, `authorize`, `permission`, `@login_required`, `@require_auth`
13. **read_file** on auth-related files
14. **grep** for caching: `cache`, `redis`, `memcache`, `@cached`
15. **grep** for background jobs: `celery`, `rq`, `worker`, `queue`, `background`, `async`, `task`
16. **codebase_search**: "How does data flow through the application from request to response?"

### Checklist

- [ ] Identify architectural patterns in use - based on READING actual code structure
- [ ] Map out the data flow through the system - trace it through actual files
- [ ] Identify all external integrations and APIs - grep for HTTP clients, API calls
- [ ] Find the entry points - READ them, don't assume
- [ ] **TRACE** a typical request through the system - follow the code path by reading files
- [ ] Identify where business logic lives - READ the actual logic code
- [ ] Map out database schema and ORM usage - READ model definitions
- [ ] Identify caching strategies - SEARCH for cache usage
- [ ] Find all background jobs, workers, or async tasks - SEARCH for them
- [ ] Identify authentication and authorization mechanisms - READ the implementation
- [ ] Find rate limiting, throttling, or protection mechanisms - SEARCH for them

### Report Section 4: Architecture

```markdown
## Architecture Analysis

### Architectural Pattern
[What pattern is actually implemented? Is it consistent?]

### System Components
[List major components and their responsibilities]

### Data Flow
[Describe how data moves through the system]

### Integration Points
[External services, APIs, databases, queues, etc.]

### Critical Paths
[Trace 2-3 critical user journeys through the code]

### Architecture Violations
[Where does the code violate its own architectural patterns?]
- Inconsistent pattern usage: [examples]
- Cross-boundary violations: [specific cases]
- Missing abstractions: [what should exist but doesn't]
- Over-abstraction: [unnecessary complexity]

### Major Gaps
[What architectural components are missing?]
```

**STOP**: This is a critical section. Do not rush. Spend significant time understanding the actual architecture.

---

## PHASE 5: CODE QUALITY DEEP SCAN

**Objective**: Systematic review of code quality across the codebase.

### Required Tool Usage

1. **grep** for TODO/FIXME/HACK/XXX/NOTE comments - find all of them
2. **grep** for error handling patterns: `try`, `catch`, `except`, `rescue`, `error`, `Error`, `panic`
3. **grep** for logging: `log`, `logger`, `print`, `console.log`, `debug`, `info`, `warn`, `error`
4. **grep** for common anti-patterns in your language (e.g., `except:` in Python for bare excepts)
5. **codebase_search**: "How is error handling implemented across the codebase?"
6. **codebase_search**: "What logging strategy is used?"
7. **Read sample files** (see strategy below) - you MUST read the actual code

### Code Sampling Strategy

Do NOT review every file. Sample systematically by READING files:

1. **Core business logic** - Use codebase_search to find, then **read_file** on 10-15 most critical files
2. **API/Entry points** - Use grep/search to find, then **read_file** on 10-15 endpoint handlers
3. **Data access layer** - Use grep to find database code, then **read_file** on 10-15 files
4. **Utilities** - List and **read_file** on 5-10 utility/helper files
5. **Tests** - Find test files, then **read_file** on 10-15 test files

**You must read AT LEAST 50 source files for this phase.**

### Checklist

- [ ] Identify code organization patterns - from READING actual code
- [ ] Check for consistent naming conventions - from READING actual code
- [ ] Look for code duplication (DRY violations) - by READING similar files
- [ ] Check error handling patterns - grep for patterns, then READ files to understand
- [ ] Review logging strategy - grep for log calls, then READ to understand strategy
- [ ] Check for proper use of language idioms - READ actual code
- [ ] Identify overly complex functions or classes - READ and count lines/complexity
- [ ] Look for god objects or god functions - READ class/function definitions
- [ ] Check for proper separation of concerns - READ code to understand boundaries
- [ ] Review test coverage (if tests exist) - READ test files
- [ ] Check for dead code or unused imports - READ files and look for unused code
- [ ] Count TODO/FIXME/HACK comments - grep for them, count them, READ context

### Report Section 5: Code Quality

```markdown
## Code Quality Assessment

### Code Organization
[How is code organized? Is it consistent?]

### Quality Metrics (Observed)
- Average function complexity: [your assessment based on samples]
- Code duplication level: [HIGH/MEDIUM/LOW with examples]
- Error handling consistency: [assessment]
- Logging quality: [assessment]

### Patterns Observed
#### Good Patterns
[Specific patterns done well, with file references]

#### Anti-Patterns
[Specific anti-patterns found, with file references]
- God objects: [list with locations]
- Tight coupling: [examples]
- Missing error handling: [examples]
- Inconsistent patterns: [examples]

### Code Smells
[Specific issues found in sampled files]
- Long functions (>50 lines): [list top 10 with line counts]
- Deep nesting (>4 levels): [examples]
- High cyclomatic complexity: [specific functions]
- Duplicated code blocks: [locations]

### Technical Debt
[Specific debt items with estimated impact]
```

---

## PHASE 6: DATA AND STATE MANAGEMENT

**Objective**: Understand how data is stored, accessed, and managed.

### Required Tool Usage

1. **glob_file_search** for schema/migration files: `*migration*`, `*schema*`, `models.py`, `*model*`, `db/*`
2. **read_file** on ALL schema and model definition files
3. **grep** for database query patterns: `select`, `SELECT`, `query`, `filter`, `find`, `get`, `fetch`
4. **codebase_search**: "How are database queries executed?"
5. **codebase_search**: "Where are database transactions managed?"
6. **grep** for transaction patterns: `transaction`, `begin`, `commit`, `rollback`, `atomic`
7. **grep** for index definitions: `index`, `Index`, `create_index`
8. **read_file** on 15-20 files with database query code
9. **grep** for validation: `validate`, `validator`, `clean`, `schema`, `validates`
10. **codebase_search**: "How is input validation implemented?"

### Checklist

- [ ] Identify all data stores - grep/search for connection strings and clients
- [ ] **READ** database schema/model files - understand the actual structure
- [ ] Check for proper indexing - READ schema definitions, look for index declarations
- [ ] Look for N+1 query problems - READ query code, look for queries in loops
- [ ] Review transaction handling - grep for transaction patterns, READ implementation
- [ ] Check for race conditions in data access - READ concurrent access code
- [ ] Review caching strategy - grep for cache usage, READ implementation
- [ ] Check for data validation at boundaries - grep for validators, READ validation code
- [ ] Look for data migration strategy - find and READ migration files
- [ ] Check for backup and recovery considerations - search for backup code/docs
- [ ] Review data retention policies - search for delete/archive code

### Report Section 6: Data Management

```markdown
## Data Management

### Data Architecture
[How is data stored and accessed?]

### Database Design
[Schema quality, normalization, relationships]

### Issues Found
- Missing indexes: [specific tables/columns]
- N+1 queries: [locations where this occurs]
- No transaction management: [examples]
- Race conditions: [specific scenarios]
- Missing validation: [data that isn't validated]

### Data Integrity
[How is data integrity maintained? What's missing?]
```

---

## PHASE 7: SECURITY AUDIT

**Objective**: Identify security vulnerabilities and weak patterns.

### Required Tool Usage

**Security requires reading actual implementation, not assumptions.**

1. **grep** for authentication: `auth`, `login`, `authenticate`, `session`, `jwt`, `token`
2. **codebase_search**: "How is user authentication implemented?"
3. **read_file** on ALL authentication-related files
4. **grep** for authorization: `authorize`, `permission`, `role`, `can_access`, `@require`, `check_permission`
5. **codebase_search**: "How are user permissions and authorization checked?"
6. **read_file** on authorization code
7. **grep** for SQL injection risks: raw SQL patterns, string concatenation in queries
8. **grep** patterns: `execute.*%`, `query.*\+`, `f"SELECT`, `"SELECT.*{`, raw SQL builders
9. **read_file** on files with raw SQL to verify safety
10. **grep** for XSS risks: `innerHTML`, `dangerouslySetInnerHTML`, `raw`, `safe`, `mark_safe`, `html_safe`
11. **grep** for CSRF: `csrf`, `@csrf_exempt`, `csrf_token`
12. **grep** for password handling: `password`, `passwd`, `pwd`, `hash`, `bcrypt`, `pbkdf2`, `scrypt`, `argon`
13. **read_file** on password handling code
14. **grep** for file uploads: `upload`, `file`, `multipart`, `FileField`
15. **grep** for eval/exec dangers: `eval`, `exec`, `system`, `shell`, `subprocess`, `os.system`
16. **codebase_search**: "How is user input validated and sanitized?"

### Checklist

- [ ] **READ** authentication implementation - don't assume it's secure
- [ ] **READ** authorization and access control code
- [ ] Check for SQL injection vulnerabilities - grep for patterns, then READ code
- [ ] Check for XSS vulnerabilities - grep for dangerous patterns, READ usage
- [ ] Check for CSRF protection - grep for csrf handling, READ implementation
- [ ] Review input validation and sanitization - search and READ validation code
- [ ] Check for secure session management - READ session handling code
- [ ] Look for information disclosure risks - READ error handlers, logging
- [ ] Review API security - READ API endpoint code
- [ ] Check for secure password storage - READ password handling, verify hashing
- [ ] Review file upload handling - READ upload code if it exists
- [ ] Check for secure communication - search for HTTPS enforcement
- [ ] Look for security headers - READ middleware/header setting code

### Report Section 7: Security Assessment

```markdown
## Security Analysis

### Authentication & Authorization
[How is auth implemented? Strengths and weaknesses]

### Vulnerabilities Found
[Specific vulnerabilities with severity levels]

#### CRITICAL
[Issues that could lead to data breach or system compromise]

#### HIGH
[Issues that significantly weaken security posture]

#### MEDIUM
[Issues that should be addressed but aren't immediately critical]

#### LOW
[Minor improvements for defense in depth]

### Missing Security Controls
[What security measures should exist but don't?]
```

---

## PHASE 8: PERFORMANCE AND SCALABILITY

**Objective**: Assess performance characteristics and scalability limits.

### Required Tool Usage

1. **grep** for N+1 query patterns: queries inside loops
2. **grep** for unbounded queries: `all()`, `SELECT \*`, queries without `LIMIT`
3. **codebase_search**: "How is pagination implemented?"
4. **grep** for caching: `cache`, `@cache`, `memoize`, `redis`, `memcache`
5. **grep** for connection pooling: `pool`, `connection`, `session`
6. **grep** for async/await patterns and blocking operations
7. **grep** for resource cleanup: `close`, `cleanup`, `finally`, `defer`, `context manager`, `with`
8. **codebase_search**: "How are database connections managed?"
9. **read_file** on 10-15 performance-critical files (query-heavy, high-traffic endpoints)
10. **grep** for rate limiting: `rate_limit`, `throttle`, `ratelimit`

### Checklist

- [ ] Identify obvious performance bottlenecks - READ hot path code
- [ ] Review database query patterns - READ query code, look for N+1
- [ ] Check for proper use of caching - grep and READ cache implementation
- [ ] Look for memory leaks or resource exhaustion risks - READ resource management
- [ ] Review connection pooling and resource management - grep and READ
- [ ] Check for blocking operations in async code - READ async implementations
- [ ] Identify single points of failure - from architecture understanding
- [ ] Review load balancing strategy - search for load balancer config
- [ ] Check for rate limiting on expensive operations - grep and READ
- [ ] Look for unbounded queries or operations - grep for queries without limits
- [ ] Review pagination implementation - search and READ pagination code
- [ ] Check for proper resource cleanup - grep for cleanup patterns, READ code

### Report Section 8: Performance & Scalability

```markdown
## Performance Analysis

### Performance Characteristics
[What is the performance profile of this system?]

### Bottlenecks Identified
[Specific bottlenecks with evidence]

### Scalability Limits
[Where will this system break under load?]
- Database limitations: [specific issues]
- Memory constraints: [specific issues]
- CPU-intensive operations: [locations]
- Network I/O: [issues]

### Scalability Strategy
[Does one exist? Is it sound?]
```

---

## PHASE 9: TESTING AND OBSERVABILITY

**Objective**: Assess testing strategy and production readiness.

### Required Tool Usage

1. **glob_file_search** for test files: `*test*`, `*spec*`, `*_test.*`, `test_*`
2. **list_dir** on test directories
3. **read_file** on 15-20 test files to assess quality
4. **grep** for test frameworks: `unittest`, `pytest`, `jest`, `mocha`, `rspec`, `@Test`
5. **grep** for mocking: `mock`, `Mock`, `stub`, `spy`, `patch`
6. **grep** for assertions: `assert`, `expect`, `should`, `assertEqual`
7. **codebase_search**: "What testing strategy is used?"
8. **grep** for logging: `log`, `logger`, `logging`, patterns from Phase 5
9. **grep** for monitoring: `metric`, `prometheus`, `statsd`, `datadog`, `newrelic`, `monitor`
10. **grep** for health checks: `health`, `healthcheck`, `/health`, `liveness`, `readiness`
11. **codebase_search**: "Where are health check endpoints defined?"
12. **read_file** on health check and monitoring code

### Checklist

- [ ] Identify test files and testing frameworks - glob search and READ
- [ ] Calculate test coverage - count test files vs source files, READ tests
- [ ] Review test quality - READ actual tests, assess assertions and coverage
- [ ] Check for flaky tests - look for sleeps, timeouts, retries in tests
- [ ] Review mocking strategy - grep for mocks, READ test code
- [ ] Check for logging implementation - from Phase 5, READ logging code
- [ ] Look for monitoring/metrics instrumentation - grep and READ
- [ ] Check for health check endpoints - grep and READ
- [ ] Review error reporting strategy - grep for error reporting tools
- [ ] Look for distributed tracing - grep for trace IDs, OpenTelemetry, Jaeger
- [ ] Check for alerting strategy - search for alert configuration
- [ ] Review debugging capabilities - assess logging quality, error details

### Report Section 9: Testing & Observability

```markdown
## Testing & Observability

### Test Coverage
[Actual coverage numbers or estimated coverage]

### Test Quality
[Are tests meaningful? Do they test the right things?]

### Gaps in Testing
[What isn't tested that should be?]

### Observability
[Can you debug production issues? Can you see what's happening?]

### Production Readiness
[Is this system ready for production? What's missing?]
```

---

## PHASE 10: OPERATIONAL CONCERNS

**Objective**: Assess deployment, maintenance, and operational aspects.

### Required Tool Usage

1. **glob_file_search** for CI/CD: `.github/workflows/*`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/*`, `azure-pipelines.yml`
2. **read_file** on ALL CI/CD configuration files
3. **glob_file_search** for deployment: `Dockerfile`, `docker-compose.yml`, `*.tf`, `deploy*`, `k8s/*`, `kubernetes/*`
4. **read_file** on ALL deployment configuration files
5. **glob_file_search** for docs: `docs/*`, `*.md`, `DEPLOYMENT*`, `OPERATIONS*`, `RUNBOOK*`
6. **read_file** on operational documentation
7. **grep** for migration patterns: `migrate`, `migration`, `alembic`, `flyway`, `liquibase`
8. **list_dir** on migration directories
9. **read_file** on recent migration files

### Checklist

- [ ] Review deployment strategy - READ deployment files and documentation
- [ ] Check for CI/CD configuration - find and READ CI/CD files
- [ ] Look for deployment scripts or automation - READ deployment code
- [ ] Review rollback strategy - search for rollback procedures
- [ ] Check for database migration strategy - find and READ migration code
- [ ] Review disaster recovery planning - search for backup/recovery docs
- [ ] Check for documentation quality - READ all markdown files
- [ ] Review onboarding materials - READ CONTRIBUTING, README, setup docs
- [ ] Check for operational runbooks - search for operational documentation
- [ ] Review dependency update strategy - look for dependabot, renovate config
- [ ] Check for version control hygiene - review .gitignore, look for sensitive files in git

### Report Section 10: Operational Assessment

```markdown
## Operational Concerns

### Deployment Strategy
[How is this deployed? Is it automated?]

### Maintenance Burden
[How difficult is this system to maintain?]

### Documentation Quality
[Is the documentation useful? What's missing?]

### Developer Experience
[How easy is it to work on this codebase?]

### Operational Risks
[What could go wrong in production?]
```

---

## PHASE 11: SYNTHESIS AND PRIORITIZATION

**Objective**: Create actionable recommendations prioritized by impact.

### Report Section 11: Executive Summary and Recommendations

```markdown
## Executive Summary

### Overall Assessment
[One paragraph summary of the codebase state]

### Critical Issues (Fix Immediately)
1. [Issue with specific impact and location]
2. [Issue with specific impact and location]
3. [Issue with specific impact and location]

### High Priority (Fix This Quarter)
1. [Issue with estimated effort and impact]
2. [Issue with estimated effort and impact]
...

### Medium Priority (Address in Next 6 Months)
[List with brief descriptions]

### Low Priority (Technical Debt Backlog)
[List with brief descriptions]

### Strengths to Preserve
[What is this codebase doing well? Be specific.]

### Architectural Recommendations
[Big picture changes needed]

### Estimated Effort for Critical Issues
[Rough estimate: person-weeks or person-months]

### Risk Level Without Changes
[Overall risk: LOW/MEDIUM/HIGH/CRITICAL with justification]
```

---

## CRITICAL REVIEW GUIDELINES

### Evidence Requirements

Every finding MUST include:
1. **Specific file and line number references** (where applicable)
2. **Code examples** showing the issue
3. **Impact analysis** - why does this matter?
4. **Severity rating** - how bad is it?

### Forbidden Patterns

DO NOT write:
- "The code could benefit from better error handling" (too vague)
- "Consider adding more tests" (no specific guidance)
- "Overall the architecture is well-designed" (meaningless praise)
- "Some improvements could be made to performance" (no specific issues)

DO write:
- "Database queries in `api/handlers.py:145-167` are vulnerable to N+1 queries. Each request to `/users/{id}/posts` triggers 1 query for the user + N queries for posts (one per post to fetch author data). This will cause linear performance degradation. See lines 156-158 for the problematic loop."

### Quality Checklist for Your Report

Before considering the review complete, verify:

- [ ] Every issue has specific file/line references
- [ ] No generic/templated language
- [ ] Severity ratings are justified
- [ ] Impact is clearly explained
- [ ] At least 50 specific code references throughout the report
- [ ] Architectural gaps are identified with evidence
- [ ] Security issues are specific, not hypothetical
- [ ] Performance concerns are backed by actual code patterns
- [ ] Recommendations are actionable and prioritized

---

## VERIFICATION BEFORE SUBMITTING REPORT

Before you consider your review complete, verify these requirements:

### Minimum Tool Usage Requirements

- [ ] **100+ read_file operations** - You must have read at least 100 files
- [ ] **30+ grep searches** - You must have performed at least 30 grep searches
- [ ] **20+ codebase_search queries** - You must have made at least 20 semantic searches
- [ ] **Tool usage log is included** in your report showing all operations

### Evidence Requirements Checklist

- [ ] Every security finding references specific files and line numbers
- [ ] Every performance issue cites actual code with file locations
- [ ] Every architectural concern is backed by code examples
- [ ] Database schema issues reference actual model/schema files
- [ ] Configuration issues cite actual config files
- [ ] At least 50 code snippets with file:line references in your report

### Red Flags That Your Review is Incomplete

❌ **FAIL**: Phrases like "appears to", "seems to", "likely", "probably", "should be"
✅ **PASS**: Phrases like "in file X:Y", "after reading", "grep shows", "the code at"

❌ **FAIL**: Generic statements applicable to any codebase
✅ **PASS**: Specific findings with exact locations and evidence

❌ **FAIL**: Architecture description based on directory structure
✅ **PASS**: Architecture description based on reading entry points and tracing code flow

❌ **FAIL**: "The authentication looks secure"
✅ **PASS**: "Authentication in `auth/handler.py:45-89` uses bcrypt password hashing (line 67) but lacks rate limiting on login attempts, allowing brute force attacks"

### Self-Assessment Questions

Ask yourself these questions before submitting:

1. **Have I actually READ the authentication code?** (Not just found files with "auth" in the name)
2. **Have I TRACED a request through the actual code?** (Not just described what I think should happen)
3. **Can I name specific functions/classes that have problems?** (Not just generic "improve error handling")
4. **Have I READ enough code to spot patterns?** (Not just 5-10 files)
5. **Can I explain exactly how the database is accessed?** (From reading actual code)
6. **Do I know what's actually in the configuration files?** (From reading them)
7. **Have I found specific security vulnerabilities?** (With file locations)

If you answer "NO" to any of these, **your review is not complete**.

---

## FINAL INSTRUCTIONS

1. **Work through each phase systematically** - Do not skip ahead
2. **Update your report continuously** - Don't wait until the end
3. **Be thorough, not fast** - This should take significant time
4. **Be brutally honest** - The goal is to find real issues, not to be nice
5. **Stay grounded** - Every claim must be evidence-based
6. **READ FILES, don't assume** - This is the most important rule
7. **Think like a Principal Engineer** - What would break in production? What won't scale? What will become unmaintainable?

### Expected Timeline

A proper Principal Engineer review of a non-trivial codebase should take:
- Small project (<5k LOC): 100-200 tool calls minimum
- Medium project (5k-50k LOC): 300-500 tool calls minimum
- Large project (>50k LOC): 500-1000+ tool calls minimum

**If you're done in under 100 tool calls, you haven't done a thorough job.**

Your review is only complete when you can confidently say: "I understand this codebase deeply enough to make architectural decisions about its future, and I can point to specific code to justify every claim I've made."

Begin Phase 0.
