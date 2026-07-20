from lib.journal import format_quantity


def test_whole_number_has_no_decimals():
    assert format_quantity(10) == "10"


def test_crypto_precision_survives():
    assert format_quantity(0.00431) == "0.00431"


def test_trailing_zeros_stripped():
    assert format_quantity(2.50000000) == "2.5"


def test_eight_decimal_places_preserved():
    assert format_quantity(0.12345678) == "0.12345678"


def test_negative_quantity():
    assert format_quantity(-6) == "-6"
