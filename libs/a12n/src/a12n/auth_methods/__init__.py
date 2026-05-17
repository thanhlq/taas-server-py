from iam_oauth.auth_methods.magic_link import EmailSender, MagicLinkAuthenticator
from iam_oauth.auth_methods.passkey import PasskeyAuthenticator
from iam_oauth.auth_methods.password import PasswordAuthenticator, PasswordPolicyError

__all__ = [
    'PasswordAuthenticator',
    'PasswordPolicyError',
    'MagicLinkAuthenticator',
    'EmailSender',
    'PasskeyAuthenticator',
]
