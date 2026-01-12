---
name: tdd
description: You must follow this skill for all development work, before writing implementation or refactoring or bug fix or any other code change. You must structure you TODO as this task describes.
---
# Test-Driven Development Skill

Expert guidance for writing tests that catch real bugs in Python using pytest.

## Core Principle

**Tests exist to catch bugs before production.** A test that can't fail when the code is wrong is worthless. Every test must verify actual logic, data transformations, or behavioral contracts.

## What Makes a Test Valuable

A valuable test will **fail** when:
- Business logic is wrong (calculations, decisions, transformations)
- Data contracts are violated (wrong fields, wrong types, wrong shapes)
- State transitions are incorrect (data mutated wrongly)
- Edge cases are mishandled (boundaries, empty inputs, nulls)

A **worthless** test only verifies:
- That a function was called (without checking what it did)
- That something is not None (without checking what it is)
- That no exception was raised (without checking the result)
- That a mock was invoked (without verifying behavior)

## The Logic-First Testing Approach

### Step 1: Identify the Logic Under Test

Before writing any test, answer: **"What decision or transformation does this code make?"**

- **Calculations**: `total = price * quantity * (1 - discount)`
- **Decisions**: `if user.is_premium and order.total > 100: apply_bonus()`
- **Transformations**: `Convert API response to domain model`
- **Filtering**: `Return only active users with verified emails`
- **Aggregations**: `Sum all transactions for the month`

If you can't identify logic, you might be testing glue code that just calls other things. Test those other things instead.

### Step 2: Define the Data Contract

For every function, explicitly define:

```python
# INPUT CONTRACT: What shape of data goes in?
# - user: User object with id, email, is_active fields
# - options: dict with optional 'include_deleted' bool

# OUTPUT CONTRACT: What shape of data comes out?
# - Returns: List[UserDTO] with id, email, display_name fields
# - Guarantees: All returned users have verified emails
# - Never returns: None (returns empty list instead)
```

### Step 3: Write Tests That Verify Contracts

```python
class TestGetActiveUsers:
    """Tests for get_active_users service function."""

    # -----------------------------------------------------------------
    # OUTPUT CONTRACT VERIFICATION
    # -----------------------------------------------------------------

    def test_returns_list_of_user_dtos_with_required_fields(self):
        """Output contains properly shaped UserDTO objects."""
        # Setup: Create real test data
        User.objects.create(email="test@example.com", is_active=True, verified=True)

        result = get_active_users()

        # VERIFY THE CONTRACT - check actual data shape
        assert len(result) == 1
        user_dto = result[0]
        assert hasattr(user_dto, 'id')
        assert hasattr(user_dto, 'email')
        assert hasattr(user_dto, 'display_name')
        assert user_dto.email == "test@example.com"

    def test_returns_empty_list_not_none_when_no_matches(self):
        """Output contract: never returns None."""
        result = get_active_users()

        assert result == []  # NOT `assert result is not None`

    # -----------------------------------------------------------------
    # FILTERING LOGIC VERIFICATION
    # -----------------------------------------------------------------

    def test_excludes_inactive_users(self):
        """Logic: is_active=False users are filtered out."""
        User.objects.create(email="active@test.com", is_active=True, verified=True)
        User.objects.create(email="inactive@test.com", is_active=False, verified=True)

        result = get_active_users()

        emails = [u.email for u in result]
        assert "active@test.com" in emails
        assert "inactive@test.com" not in emails

    def test_excludes_unverified_users(self):
        """Logic: verified=False users are filtered out."""
        User.objects.create(email="verified@test.com", is_active=True, verified=True)
        User.objects.create(email="unverified@test.com", is_active=True, verified=False)

        result = get_active_users()

        emails = [u.email for u in result]
        assert "verified@test.com" in emails
        assert "unverified@test.com" not in emails

    def test_combines_all_filter_conditions(self):
        """Logic: ALL conditions must be met (AND not OR)."""
        User.objects.create(email="both@test.com", is_active=True, verified=True)
        User.objects.create(email="active_only@test.com", is_active=True, verified=False)
        User.objects.create(email="verified_only@test.com", is_active=False, verified=True)

        result = get_active_users()

        assert len(result) == 1
        assert result[0].email == "both@test.com"
```

## Testing Patterns for Common Logic Types

### Pattern 1: Testing Calculations

```python
class TestCalculateOrderTotal:
    """Tests for order total calculation logic."""

    def test_multiplies_price_by_quantity(self):
        """Basic calculation: total = price * quantity."""
        result = calculate_order_total(price=10.00, quantity=3)
        assert result == 30.00

    def test_applies_percentage_discount(self):
        """Discount logic: reduces total by percentage."""
        result = calculate_order_total(price=100.00, quantity=1, discount_pct=0.20)
        assert result == 80.00

    def test_discount_applied_after_quantity_multiplication(self):
        """Order of operations: (price * qty) * (1 - discount)."""
        result = calculate_order_total(price=50.00, quantity=2, discount_pct=0.10)
        # 50 * 2 = 100, then 100 * 0.90 = 90
        assert result == 90.00
        # NOT: 50 * 0.90 * 2 = 90 (same result, but test another case to prove order)

    def test_rounds_to_two_decimal_places(self):
        """Currency precision: always 2 decimal places."""
        result = calculate_order_total(price=33.33, quantity=3)
        # 33.33 * 3 = 99.99 (no rounding needed here, but test edge case)
        result = calculate_order_total(price=10.00, quantity=3, discount_pct=0.07)
        # 30 * 0.93 = 27.9 -> should be 27.90
        assert result == 27.90

    def test_zero_quantity_returns_zero(self):
        """Edge case: zero quantity means zero total."""
        result = calculate_order_total(price=100.00, quantity=0)
        assert result == 0.00

    def test_100_percent_discount_returns_zero(self):
        """Edge case: full discount means free."""
        result = calculate_order_total(price=100.00, quantity=1, discount_pct=1.0)
        assert result == 0.00
```

### Pattern 2: Testing Data Transformations

```python
class TestTransformApiResponseToUser:
    """Tests for API response -> domain model transformation."""

    def test_maps_all_required_fields(self):
        """Transformation maps API fields to domain fields."""
        api_response = {
            "user_id": "123",
            "email_address": "test@example.com",
            "first_name": "John",
            "last_name": "Doe",
            "account_status": "ACTIVE",
        }

        user = transform_api_response_to_user(api_response)

        # Verify field mapping (API names -> domain names)
        assert user.id == "123"  # user_id -> id
        assert user.email == "test@example.com"  # email_address -> email
        assert user.full_name == "John Doe"  # first + last -> full_name
        assert user.is_active is True  # "ACTIVE" -> True

    def test_handles_inactive_status(self):
        """Status transformation: non-ACTIVE -> is_active=False."""
        api_response = {"user_id": "1", "email_address": "x@y.com",
                       "first_name": "X", "last_name": "Y", "account_status": "SUSPENDED"}

        user = transform_api_response_to_user(api_response)

        assert user.is_active is False

    def test_handles_missing_optional_fields(self):
        """Transformation provides defaults for optional fields."""
        api_response = {
            "user_id": "123",
            "email_address": "test@example.com",
            # first_name and last_name missing
            "account_status": "ACTIVE",
        }

        user = transform_api_response_to_user(api_response)

        assert user.full_name == ""  # or whatever the default should be

    def test_raises_on_missing_required_field(self):
        """Contract: required fields must be present."""
        api_response = {"email_address": "test@example.com"}  # missing user_id

        with pytest.raises(ValueError, match="user_id"):
            transform_api_response_to_user(api_response)
```

### Pattern 3: Testing State Transitions

```python
class TestOrderStateMachine:
    """Tests for order state transition logic."""

    def test_pending_order_can_be_confirmed(self):
        """State transition: PENDING -> CONFIRMED allowed."""
        order = Order(status=OrderStatus.PENDING)

        order.confirm()

        assert order.status == OrderStatus.CONFIRMED

    def test_pending_order_cannot_be_shipped(self):
        """State transition: PENDING -> SHIPPED not allowed."""
        order = Order(status=OrderStatus.PENDING)

        with pytest.raises(InvalidStateTransition):
            order.ship()

    def test_confirmed_order_can_be_shipped(self):
        """State transition: CONFIRMED -> SHIPPED allowed."""
        order = Order(status=OrderStatus.CONFIRMED)

        order.ship()

        assert order.status == OrderStatus.SHIPPED

    def test_shipped_order_cannot_be_cancelled(self):
        """State transition: SHIPPED -> CANCELLED not allowed."""
        order = Order(status=OrderStatus.SHIPPED)

        with pytest.raises(InvalidStateTransition, match="cannot cancel shipped"):
            order.cancel()

    def test_confirmation_sets_confirmed_at_timestamp(self):
        """Side effect: confirmation records timestamp."""
        order = Order(status=OrderStatus.PENDING)

        order.confirm()

        assert order.confirmed_at is not None
        assert order.confirmed_at <= timezone.now()
```

### Pattern 4: Testing Conditional Logic

```python
class TestApplyUserDiscount:
    """Tests for user discount eligibility logic."""

    def test_premium_user_gets_premium_discount(self):
        """Logic: premium tier -> 20% discount."""
        user = User(tier="premium")

        discount = calculate_user_discount(user)

        assert discount == 0.20

    def test_standard_user_gets_standard_discount(self):
        """Logic: standard tier -> 10% discount."""
        user = User(tier="standard")

        discount = calculate_user_discount(user)

        assert discount == 0.10

    def test_new_user_gets_welcome_discount(self):
        """Logic: account < 30 days -> extra 5%."""
        user = User(tier="standard", created_at=timezone.now() - timedelta(days=15))

        discount = calculate_user_discount(user)

        assert discount == 0.15  # 10% standard + 5% welcome

    def test_premium_new_user_gets_combined_discount(self):
        """Logic: discounts stack (premium + welcome)."""
        user = User(tier="premium", created_at=timezone.now() - timedelta(days=15))

        discount = calculate_user_discount(user)

        assert discount == 0.25  # 20% premium + 5% welcome

    def test_old_user_does_not_get_welcome_discount(self):
        """Logic: account >= 30 days -> no welcome discount."""
        user = User(tier="standard", created_at=timezone.now() - timedelta(days=45))

        discount = calculate_user_discount(user)

        assert discount == 0.10  # standard only, no welcome
```

## When to Use Mocks

**Mock ONLY when you must isolate from:**
- Network calls (HTTP, database connections to external systems)
- File system in tests that don't need it
- Time-dependent logic (use `freezegun` or time mocks)
- Expensive operations you've already tested elsewhere

**Do NOT mock:**
- Your own code that has logic to test
- Django ORM for database tests (use the test database)
- Simple data structures or value objects

```python
# WRONG: Mocking away the logic you should test
def test_get_user_orders(self):
    with patch("orders.services.Order.objects.filter") as mock:
        mock.return_value = [Mock(total=100)]
        result = get_user_orders(user_id=1)
    mock.assert_called_once()  # WORTHLESS - doesn't test anything real

# CORRECT: Test with real data, mock only external calls
def test_get_user_orders(self):
    user = User.objects.create(email="test@test.com")
    Order.objects.create(user=user, total=100, status="completed")
    Order.objects.create(user=user, total=50, status="cancelled")

    result = get_user_orders(user_id=user.id)

    # Test the actual filtering logic
    assert len(result) == 1
    assert result[0].total == 100  # Only completed orders

# CORRECT: Mock external HTTP calls
def test_fetches_user_from_external_api(self):
    with patch("services.requests.get") as mock_get:
        mock_get.return_value.json.return_value = {
            "id": "123", "name": "Test User"
        }
        mock_get.return_value.status_code = 200

        result = fetch_external_user(external_id="123")

        # Verify we called the right URL
        mock_get.assert_called_with("https://api.external.com/users/123")
        # AND verify we processed the response correctly
        assert result.id == "123"
        assert result.name == "Test User"
```

## Error Testing: Test the Error LOGIC

Don't just test that errors are raised. Test the **error logic**:

```python
class TestCreateUser:
    """Tests for user creation error handling."""

    def test_rejects_duplicate_email(self):
        """Logic: email uniqueness enforced."""
        User.objects.create(email="taken@test.com")

        with pytest.raises(DuplicateEmailError) as exc_info:
            create_user(email="taken@test.com")

        # Verify error contains useful information
        assert "taken@test.com" in str(exc_info.value)

    def test_rejects_invalid_email_format(self):
        """Logic: email format validation."""
        with pytest.raises(ValidationError) as exc_info:
            create_user(email="not-an-email")

        assert "email" in str(exc_info.value).lower()

    def test_retries_on_transient_database_error(self):
        """Logic: transient errors trigger retry."""
        call_count = 0
        def flaky_save(self):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise DatabaseError("Connection lost")
            return original_save(self)

        with patch.object(User, 'save', flaky_save):
            user = create_user(email="test@test.com")

        assert user is not None
        assert call_count == 3  # Retried twice before success

    def test_gives_up_after_max_retries(self):
        """Logic: retry limit enforced."""
        with patch.object(User, 'save', side_effect=DatabaseError("Down")):
            with pytest.raises(DatabaseError):
                create_user(email="test@test.com")
```

## Test Naming: Describe the Logic Being Tested

```python
# GOOD: Names describe what logic is being verified
def test_excludes_users_without_verified_email():
def test_applies_bulk_discount_when_quantity_exceeds_10():
def test_combines_shipping_and_tax_into_final_total():
def test_rejects_order_when_item_out_of_stock():

# BAD: Names describe test mechanics, not logic
def test_happy_path():
def test_with_mock():
def test_returns_correct_value():
def test_error_handling():
```

## Checklist Before Submitting Tests

For each test, verify:

1. **Logic Tested**: Does this test verify actual business logic?
2. **Would Fail If Wrong**: If I broke the logic, would this test catch it?
3. **Data Contract**: Do I verify the shape/content of outputs?
4. **Meaningful Assertions**: Am I checking specific values, not just existence?
5. **Edge Cases**: Have I tested boundaries and special cases?
6. **Error Logic**: Do error tests verify the error behavior, not just that errors occur?

## Anti-Patterns to Avoid

```python
# ANTI-PATTERN 1: Testing that code runs without asserting results
def test_process_order(self):
    process_order(order_id=1)  # No assertions!

# ANTI-PATTERN 2: Asserting only existence
def test_get_user(self):
    result = get_user(id=1)
    assert result is not None  # What IS it though?

# ANTI-PATTERN 3: Mock everything, test nothing
def test_create_order(self):
    with patch("services.validate") as m1, \
         patch("services.calculate") as m2, \
         patch("services.save") as m3:
        create_order(data={})
    m1.assert_called_once()  # So what?

# ANTI-PATTERN 4: Testing framework behavior
def test_model_saves(self):
    obj = MyModel(name="test")
    obj.save()
    assert MyModel.objects.filter(name="test").exists()  # Testing Django

# ANTI-PATTERN 5: One trivial assertion per test
def test_has_id(self):
    assert result.id is not None
def test_has_name(self):
    assert result.name is not None
def test_has_email(self):
    assert result.email is not None
# Should be ONE test verifying the complete data contract
```

## Remember

- **Test Logic, Not Glue**: Focus on decisions, calculations, transformations
- **Verify Data Contracts**: Check actual values and shapes, not just existence
- **Make Tests That Can Fail**: If breaking the code won't fail the test, it's worthless
- **Use Real Data When Possible**: Django test DB is there for a reason
- **Mock Only Boundaries**: External APIs, not your own logic
- **Name Tests After Logic**: `test_applies_discount_for_premium_users` not `test_discount`
