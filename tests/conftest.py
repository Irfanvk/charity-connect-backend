import pytest


@pytest.fixture()
def staff_viewer():
    """Word "done by" labels as an admin sees them ("admin (A12)") for the test."""
    from app.utils.admin_codes import viewing_as

    with viewing_as(True):
        yield
