"""Tests for settings encryption."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_encrypt_decrypt_roundtrip():
    """Encrypted value decrypts back to original."""
    # Set a test key
    from cryptography.fernet import Fernet
    os.environ["SETTINGS_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

    # Reset cached fernet
    import api.crypto as crypto
    crypto._fernet = None

    plaintext = "sk-ant-api03-secret-key-here"
    encrypted = crypto.encrypt_value(plaintext)

    assert encrypted != plaintext
    assert encrypted.startswith("enc::")
    assert crypto.is_encrypted(encrypted)
    assert not crypto.is_encrypted(plaintext)

    decrypted = crypto.decrypt_value(encrypted)
    assert decrypted == plaintext


def test_encrypt_empty_noop():
    """Empty string returns as-is."""
    from api.crypto import encrypt_value, decrypt_value
    assert encrypt_value("") == ""
    assert decrypt_value("") == ""


def test_decrypt_non_encrypted_passthrough():
    """Non-prefixed values pass through unchanged."""
    from api.crypto import decrypt_value
    assert decrypt_value("plain-text-value") == "plain-text-value"


def test_wrong_key_returns_empty():
    """Decryption with wrong key returns empty string."""
    from cryptography.fernet import Fernet
    import api.crypto as crypto

    # Encrypt with one key
    os.environ["SETTINGS_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    crypto._fernet = None
    encrypted = crypto.encrypt_value("secret")

    # Try to decrypt with different key
    os.environ["SETTINGS_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    crypto._fernet = None
    result = crypto.decrypt_value(encrypted)
    assert result == ""


def test_settings_manager_sensitive_keys():
    """Sensitive keys list includes expected entries."""
    from api.settings_manager import SENSITIVE_KEYS
    assert "lmStudioApiKey" in SENSITIVE_KEYS
    assert "externalApiKey" in SENSITIVE_KEYS
    assert "ghcrToken" in SENSITIVE_KEYS
    assert "proxmoxTokenSecret" in SENSITIVE_KEYS
    # Non-sensitive keys should NOT be in the set
    assert "lmStudioUrl" not in SENSITIVE_KEYS
    assert "dockerHost" not in SENSITIVE_KEYS
