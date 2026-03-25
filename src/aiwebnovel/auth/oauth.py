"""OAuth2 provider stubs.

These are interface-only stubs for Google and GitHub OAuth2.
Full implementation is deferred to a later phase.
"""

from __future__ import annotations


class GoogleOAuthHandler:
    """Google OAuth2 handler (stub)."""

    def get_authorization_url(self) -> str:
        """Get the Google OAuth2 authorization URL.

        Raises:
            NotImplementedError: OAuth not yet implemented.
        """
        raise NotImplementedError("Google OAuth2 is not yet implemented")

    def handle_callback(self, code: str) -> dict:
        """Handle the Google OAuth2 callback.

        Args:
            code: Authorization code from Google.

        Raises:
            NotImplementedError: OAuth not yet implemented.
        """
        raise NotImplementedError("Google OAuth2 is not yet implemented")


class GitHubOAuthHandler:
    """GitHub OAuth2 handler (stub)."""

    def get_authorization_url(self) -> str:
        """Get the GitHub OAuth2 authorization URL.

        Raises:
            NotImplementedError: OAuth not yet implemented.
        """
        raise NotImplementedError("GitHub OAuth2 is not yet implemented")

    def handle_callback(self, code: str) -> dict:
        """Handle the GitHub OAuth2 callback.

        Args:
            code: Authorization code from GitHub.

        Raises:
            NotImplementedError: OAuth not yet implemented.
        """
        raise NotImplementedError("GitHub OAuth2 is not yet implemented")
