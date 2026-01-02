---
name: test-driven-development
description: You must follow this skill for all development work, before writing implementation or refactoring or bug fix or any other code change. You must structure you TODO as this task describes.
---
# Test-Driven Development Skill

Expert guidance for writing comprehensive, focused tests in Python using pytest.

## Core Principle

**A test validates ONE responsibility of ONE component.** Tests must be comprehensive for that responsibility while ignoring everything else.

## The Testing Contract

Every function has a contract:
1. **Inputs** - What minimum data does it need?
2. **Outputs** - What does it return/produce?
3. **Side effects** - What does it change (DB, files, external systems)?
4. **Errors** - What can go wrong and how does it handle that?
5. **Logging** - What does it record about its behavior?

Your tests must verify ALL FIVE, and ONLY these five things.

## Test Organization Template
```python
class TestFunctionName:
    """Tests for module.function_name."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_returns_expected_output_for_valid_input(self):
        """Function returns correct result when inputs are valid."""
        # Mock external dependencies
        # Call function with valid inputs
        # Assert return value is correct

    def test_produces_expected_side_effects(self):
        """Function creates/modifies expected state."""
        # Mock external dependencies
        # Call function
        # Assert database/file/external system changed correctly

    # ---------------------------------------------------------------------
    # Input validation - minimum required data
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self):
        """Function works with bare minimum valid input."""
        # Call with only required parameters
        # Assert success

    def test_raises_error_when_required_input_missing(self):
        """Function raises appropriate error when required data absent."""
        # Call without required parameter/field
        # Assert raises specific exception with clear message

    def test_raises_error_when_input_invalid(self):
        """Function validates input format/type/constraints."""
        # Call with wrong type/format/out of bounds value
        # Assert raises specific exception with clear message

    # ---------------------------------------------------------------------
    # Error handling - what can go wrong
    # ---------------------------------------------------------------------

    def test_handles_dependency_failure_gracefully(self):
        """Function handles external dependency failures appropriately."""
        # Mock dependency to raise exception
        # Call function
        # Assert either: recovers gracefully OR propagates with context

    def test_propagates_critical_errors(self):
        """Function propagates errors it cannot handle."""
        # Mock dependency to raise exception
        # Assert function raises same/wrapped exception

    def test_logs_error_on_failure(self):
        """Function logs ERROR when operations fail."""
        # Mock dependency to fail
        # Capture logs at ERROR level
        # Call function (catching expected exception)
        # Assert error logged with relevant context

    # ---------------------------------------------------------------------
    # Logging - observability
    # ---------------------------------------------------------------------

    def test_logs_debug_on_success(self):
        """Function logs DEBUG when operation succeeds."""
        # Capture logs at DEBUG level
        # Call function successfully
        # Assert debug message contains key information

    def test_logs_info_for_significant_events(self):
        """Function logs INFO for business-relevant events."""
        # Only if function has INFO-worthy events
        # Capture logs at INFO level
        # Call function
        # Assert info logged appropriately

    # ---------------------------------------------------------------------
    # Boundary conditions
    # ---------------------------------------------------------------------

    def test_handles_empty_input_correctly(self):
        """Function behaves correctly with empty/null input."""
        # Call with empty list/string/None
        # Assert appropriate behavior (error, empty result, etc.)

    def test_handles_large_input_correctly(self):
        """Function handles edge cases in input size/scale."""
        # Call with maximum/large valid input
        # Assert success without performance degradation
```

## Critical Rules

### Rule 1: Mock Everything External

**Mock ANY dependency the function doesn't own:**
- Database queries
- External API calls
- File system operations
- Other service layer functions
- System time/randomness
```python
# CORRECT - mocking external dependency
def test_creates_user_profile(self):
    with patch("management.services.create_user_profile") as mock:
        user = User.objects.create_user(username="test@example.com")
    mock.assert_called_once_with(user)

# WRONG - testing the dependency's behavior
def test_creates_user_profile(self):
    user = User.objects.create_user(username="test@example.com")
    assert UserProfile.objects.filter(user=user).exists()  # This tests UserProfile creation, not the handler!
```

### Rule 2: Test Logging Explicitly

**Every test suite must verify logging:**
- DEBUG logs for normal operations
- ERROR logs for failures
- Include relevant context in log messages
```python
def test_logs_debug_on_success(self, caplog):
    """Service logs debug when operation succeeds."""
    with caplog.at_level(logging.DEBUG, logger="myapp.services"):
        result = my_function(arg="value")

    assert "operation succeeded" in caplog.text
    assert "value" in caplog.text  # Verify context included

def test_logs_error_on_failure(self, caplog):
    """Service logs error when dependency fails."""
    with (
        caplog.at_level(logging.ERROR, logger="myapp.services"),
        patch("myapp.services.external_call", side_effect=Exception("fail")),
        pytest.raises(Exception),
    ):
        my_function(arg="value")

    assert "operation failed" in caplog.text
    assert "value" in caplog.text  # Verify context included
```

### Rule 3: Test Exception Handling

**Test BOTH error propagation AND error handling:**
```python
# Test that critical errors propagate
def test_propagates_database_error(self):
    """Function propagates database errors to caller."""
    with (
        patch("myapp.models.Thing.objects.get", side_effect=DatabaseError("DB down")),
        pytest.raises(DatabaseError, match="DB down"),
    ):
        my_function(id=1)

# Test that recoverable errors are handled
def test_handles_missing_optional_data(self):
    """Function continues when optional dependency unavailable."""
    with patch("myapp.services.optional_service", side_effect=NotFoundError()):
        result = my_function(id=1)

    assert result is not None  # Function completed despite optional failure
```

### Rule 4: Test Input Validation

**Verify the function validates its contract:**
```python
def test_requires_user_id(self):
    """Function raises ValueError when user_id is None."""
    with pytest.raises(ValueError, match="user_id is required"):
        my_function(user_id=None)

def test_requires_positive_amount(self):
    """Function raises ValueError when amount is negative."""
    with pytest.raises(ValueError, match="amount must be positive"):
        my_function(amount=-10)

def test_succeeds_with_minimum_input(self):
    """Function works with only required fields provided."""
    result = my_function(user_id=1)  # No optional params
    assert result.status == "success"
```

### Rule 5: Don't Test Dependencies

**If it's not YOUR code, don't test it:**
```python
# WRONG - testing Django's behavior
def test_user_save_creates_record(self):
    user = User(username="test")
    user.save()
    assert User.objects.filter(username="test").exists()  # Testing Django ORM

# WRONG - testing external library
def test_requests_makes_http_call(self):
    response = requests.get("http://example.com")
    assert response.status_code == 200  # Testing requests library

# CORRECT - testing YOUR code that uses dependencies
def test_fetch_user_data_calls_api_correctly(self):
    with patch("myapp.services.requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"id": 1}

        result = fetch_user_data(user_id=1)

        mock_get.assert_called_once_with("https://api.example.com/users/1")
        assert result == {"id": 1}
```

## Common Mistakes to Avoid

### Mistake 1: Testing Implementation Instead of Behavior
```python
# WRONG - testing how it works
def test_uses_correct_query(self):
    with patch("myapp.models.User.objects.filter") as mock_filter:
        get_active_users()
        mock_filter.assert_called_with(is_active=True)

# CORRECT - testing what it produces
def test_returns_only_active_users(self):
    User.objects.create(username="active", is_active=True)
    User.objects.create(username="inactive", is_active=False)

    result = get_active_users()

    assert len(result) == 1
    assert result[0].username == "active"
```

### Mistake 2: Surface-Level Assertions
```python
# WRONG - only testing it doesn't crash
def test_process_payment(self):
    result = process_payment(amount=100, user_id=1)
    assert result is not None  # Useless test

# CORRECT - testing actual behavior
def test_process_payment_creates_transaction(self):
    result = process_payment(amount=100, user_id=1)

    assert result.status == "completed"
    assert result.amount == 100
    assert Transaction.objects.filter(user_id=1, amount=100).exists()
```

### Mistake 3: Missing Error Cases
```python
# INCOMPLETE - only testing success
def test_create_user(self):
    user = create_user(email="test@example.com")
    assert user.email == "test@example.com"

# COMPLETE - testing failure modes too
def test_create_user_requires_email(self):
    with pytest.raises(ValueError, match="email is required"):
        create_user(email=None)

def test_create_user_rejects_invalid_email(self):
    with pytest.raises(ValueError, match="invalid email format"):
        create_user(email="not-an-email")

def test_create_user_logs_error_on_database_failure(self, caplog):
    with (
        caplog.at_level(logging.ERROR),
        patch("myapp.models.User.objects.create", side_effect=DatabaseError()),
        pytest.raises(DatabaseError),
    ):
        create_user(email="test@example.com")

    assert "Failed to create user" in caplog.text
```

## Test Naming Convention

Test names should complete the sentence: "It ______"
```python
# GOOD names
def test_returns_empty_list_when_no_results():
def test_raises_value_error_when_amount_negative():
def test_logs_error_when_api_call_fails():
def test_propagates_database_error_to_caller():

# BAD names
def test_happy_path():  # What does success mean?
def test_error_handling():  # Which error?
def test_edge_case():  # Which edge?
```

## Pytest Fixtures and Mocking
```python
# Good fixture for common test data
@pytest.fixture
def valid_user():
    """Return valid user data for testing."""
    return {
        "email": "test@example.com",
        "username": "testuser",
        "is_active": True,
    }

# Good use of patch as context manager
def test_sends_email_on_signup(self):
    with patch("myapp.services.send_email") as mock_send:
        signup_user(email="test@example.com")

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        assert kwargs["to"] == "test@example.com"
        assert "Welcome" in kwargs["subject"]
```

## The Test-First Workflow

1. **Read the function signature** - What inputs does it take?
2. **Read the function docstring** - What should it do?
3. **Identify the contract** - Inputs, outputs, side effects, errors, logging
4. **Write test structure** - Organize into sections as shown above
5. **Implement tests** - One section at a time
6. **Run tests** - They should fail (function doesn't exist yet or is incomplete)
7. **Implement function** - Make tests pass
8. **Refactor** - Improve code while tests stay green

## Remember

- **Comprehensive > Minimal** - Test all five parts of the contract
- **Focused > Broad** - One responsibility per test
- **Explicit > Implicit** - Mock dependencies, verify logging, check errors
- **Behavior > Implementation** - Test what it does, not how
- **Clear > Clever** - Simple assertions, obvious test names

If a test feels hard to write, the code might have unclear responsibilities or too many dependencies. That's valuable feedback.
