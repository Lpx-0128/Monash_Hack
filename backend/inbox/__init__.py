"""Inbox connectors package for external email ingestion."""

from .gmail import GmailConfig, GmailConnector

__all__ = ["GmailConfig", "GmailConnector"]
