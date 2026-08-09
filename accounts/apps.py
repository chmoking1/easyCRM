"""Django application configuration for the accounts domain."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Register the accounts application with a human-readable default ID type."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
