"""Tests for _validate_ngfw_id() function."""

import sys

import pytest


class TestValidateNgfwId:
    """Tests for _validate_ngfw_id() internal validation function.

    Contract:
    - Inputs: ngfw_id (int)
    - Outputs: None (returns nothing on success)
    - Side effects: None
    - Errors: TypeError if ngfw_id is None or wrong type, ValueError if negative
    - Logging: None
    """

    # -------------------------------------------------------------------------
    # Happy path - valid inputs that should pass validation
    # -------------------------------------------------------------------------

    def test_accepts_zero(self):
        """Function accepts 0 as valid ngfw_id (boundary case)."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(0)

        assert result is None

    def test_accepts_one(self):
        """Function accepts 1 as valid ngfw_id."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(1)

        assert result is None

    def test_accepts_small_positive_integer(self):
        """Function accepts small positive integer."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(42)

        assert result is None

    def test_accepts_large_positive_integer(self):
        """Function accepts large positive integer."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(999999)

        assert result is None

    def test_accepts_very_large_positive_integer(self):
        """Function accepts very large positive integer."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(10**12)

        assert result is None

    def test_accepts_max_int(self):
        """Function accepts maximum integer value."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(sys.maxsize)

        assert result is None

    # -------------------------------------------------------------------------
    # Output validation - function returns None on success
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self):
        """Function returns None when validation passes."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(42)

        assert result is None

    def test_returns_none_not_truthy_value(self):
        """Function returns exactly None, not any other falsy value."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(1)

        assert result is None
        assert result != 0
        assert result is not False
        assert result != ""

    # -------------------------------------------------------------------------
    # Input validation - None
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_none(self):
        """Function raises TypeError when ngfw_id is None."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(None)

    def test_type_error_message_mentions_none(self):
        """TypeError message mentions None."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError) as exc_info:
            _validate_ngfw_id(None)

        assert "None" in str(exc_info.value) or "none" in str(exc_info.value).lower()

    def test_type_error_message_mentions_integer(self):
        """TypeError message mentions expected integer type."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError) as exc_info:
            _validate_ngfw_id(None)

        assert "integer" in str(exc_info.value).lower() or "int" in str(exc_info.value).lower()

    # -------------------------------------------------------------------------
    # Input validation - negative values
    # -------------------------------------------------------------------------

    def test_raises_value_error_when_negative_one(self):
        """Function raises ValueError when ngfw_id is -1."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(ValueError):
            _validate_ngfw_id(-1)

    def test_raises_value_error_when_negative_small(self):
        """Function raises ValueError when ngfw_id is small negative."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(ValueError):
            _validate_ngfw_id(-42)

    def test_raises_value_error_when_negative_large(self):
        """Function raises ValueError when ngfw_id is large negative."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(ValueError):
            _validate_ngfw_id(-999999)

    def test_raises_value_error_when_min_int(self):
        """Function raises ValueError when ngfw_id is minimum integer."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(ValueError):
            _validate_ngfw_id(-sys.maxsize - 1)

    def test_value_error_message_mentions_positive(self):
        """ValueError message mentions positive requirement."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(ValueError) as exc_info:
            _validate_ngfw_id(-1)

        error_msg = str(exc_info.value).lower()
        assert "positive" in error_msg or "non-negative" in error_msg or "negative" in error_msg

    # -------------------------------------------------------------------------
    # Input validation - wrong types (string)
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_string_numeric(self):
        """Function raises TypeError when ngfw_id is numeric string."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id("42")

    def test_raises_type_error_when_string_empty(self):
        """Function raises TypeError when ngfw_id is empty string."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id("")

    def test_raises_type_error_when_string_text(self):
        """Function raises TypeError when ngfw_id is text string."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id("abc")

    def test_raises_type_error_when_string_whitespace(self):
        """Function raises TypeError when ngfw_id is whitespace string."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id("   ")

    # -------------------------------------------------------------------------
    # Input validation - wrong types (float)
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_float_positive(self):
        """Function raises TypeError when ngfw_id is positive float."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(42.0)

    def test_raises_type_error_when_float_negative(self):
        """Function raises TypeError when ngfw_id is negative float."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(-42.0)

    def test_raises_type_error_when_float_zero(self):
        """Function raises TypeError when ngfw_id is 0.0."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(0.0)

    def test_raises_type_error_when_float_fractional(self):
        """Function raises TypeError when ngfw_id is fractional float."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(3.14)

    # -------------------------------------------------------------------------
    # Input validation - wrong types (collections)
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_list_empty(self):
        """Function raises TypeError when ngfw_id is empty list."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id([])

    def test_raises_type_error_when_list_with_int(self):
        """Function raises TypeError when ngfw_id is list with integer."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id([42])

    def test_raises_type_error_when_dict_empty(self):
        """Function raises TypeError when ngfw_id is empty dict."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id({})

    def test_raises_type_error_when_dict_with_value(self):
        """Function raises TypeError when ngfw_id is dict with value."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id({"id": 42})

    def test_raises_type_error_when_tuple_empty(self):
        """Function raises TypeError when ngfw_id is empty tuple."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(())

    def test_raises_type_error_when_tuple_with_int(self):
        """Function raises TypeError when ngfw_id is tuple with integer."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id((42,))

    def test_raises_type_error_when_set_empty(self):
        """Function raises TypeError when ngfw_id is empty set."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(set())

    def test_raises_type_error_when_set_with_int(self):
        """Function raises TypeError when ngfw_id is set with integer."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id({42})

    # -------------------------------------------------------------------------
    # Input validation - wrong types (other primitives)
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_bytes(self):
        """Function raises TypeError when ngfw_id is bytes."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(b"42")

    def test_raises_type_error_when_bytearray(self):
        """Function raises TypeError when ngfw_id is bytearray."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(bytearray(b"42"))

    def test_raises_type_error_when_bool_true(self):
        """Function raises TypeError when ngfw_id is True.

        Note: bool is subclass of int in Python, but semantically
        we should not accept booleans as database IDs.
        """
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(True)

    def test_raises_type_error_when_bool_false(self):
        """Function raises TypeError when ngfw_id is False.

        Note: bool is subclass of int in Python, but semantically
        we should not accept booleans as database IDs.
        """
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(False)

    # -------------------------------------------------------------------------
    # Input validation - wrong types (objects)
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_object(self):
        """Function raises TypeError when ngfw_id is object instance."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(object())

    def test_raises_type_error_when_class(self):
        """Function raises TypeError when ngfw_id is a class type."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(int)

    def test_raises_type_error_when_lambda(self):
        """Function raises TypeError when ngfw_id is lambda."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(TypeError):
            _validate_ngfw_id(lambda: 42)

    def test_raises_type_error_when_callable(self):
        """Function raises TypeError when ngfw_id is callable object."""
        from engine.ecs import _validate_ngfw_id

        class CallableId:
            def __call__(self):
                return 42

        with pytest.raises(TypeError):
            _validate_ngfw_id(CallableId())

    # -------------------------------------------------------------------------
    # Side effects - none expected
    # -------------------------------------------------------------------------

    def test_no_side_effects_on_valid_input(self):
        """Function has no side effects when input is valid."""
        from engine.ecs import _validate_ngfw_id

        ngfw_id = 42
        original_value = ngfw_id

        _validate_ngfw_id(ngfw_id)

        assert ngfw_id == original_value

    def test_no_side_effects_on_invalid_input(self):
        """Function has no side effects when raising exception."""
        from engine.ecs import _validate_ngfw_id

        ngfw_id = -1
        original_value = ngfw_id

        with pytest.raises(ValueError):
            _validate_ngfw_id(ngfw_id)

        assert ngfw_id == original_value

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    def test_boundary_zero_is_valid(self):
        """Zero is a valid boundary - accepted as valid ID."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(0)

        assert result is None

    def test_boundary_negative_one_is_invalid(self):
        """Negative one is invalid boundary - rejected."""
        from engine.ecs import _validate_ngfw_id

        with pytest.raises(ValueError):
            _validate_ngfw_id(-1)

    def test_boundary_one_is_valid(self):
        """One is a valid boundary - typical first ID."""
        from engine.ecs import _validate_ngfw_id

        result = _validate_ngfw_id(1)

        assert result is None

    # -------------------------------------------------------------------------
    # Special cases
    # -------------------------------------------------------------------------

    def test_multiple_calls_are_independent(self):
        """Multiple validation calls don't affect each other."""
        from engine.ecs import _validate_ngfw_id

        # First call with valid ID
        result1 = _validate_ngfw_id(1)
        assert result1 is None

        # Second call with different valid ID
        result2 = _validate_ngfw_id(100)
        assert result2 is None

        # Third call should fail, but not affect previous calls
        with pytest.raises(ValueError):
            _validate_ngfw_id(-1)

        # Fourth call should still work
        result4 = _validate_ngfw_id(42)
        assert result4 is None
