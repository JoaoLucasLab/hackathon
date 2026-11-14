"""Importing the app registers the school (BYU-Idaho rules), as at startup.

Tests that call API functions directly (without a TestClient) need it too.
"""

import app.main  # noqa: F401
