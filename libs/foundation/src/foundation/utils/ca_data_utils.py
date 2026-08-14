import base64
import binascii

PEM_CERT_MARKER = '-----BEGIN CERTIFICATE-----'


def normalize_ca_data(raw: str) -> str:
    """
    Turn an env-var-carried CA bundle into PEM text OpenSSL accepts.

    Handles the three shapes a CA realistically arrives in when it is injected
    as a variable rather than mounted as a file:

    * plain multi-line PEM (dotenv quoted value, Docker/K8s multi-line env),
    * single-line PEM with literal ``\\n`` escapes (CI/CD secret stores),
    * base64-encoded PEM (e.g. a Kubernetes secret's raw ``ca.crt`` value).

    Raises ``ValueError`` when the result still isn't a certificate, so a
    mangled secret fails at startup instead of at the first TLS handshake.
    """
    data = raw.strip()

    if PEM_CERT_MARKER not in data:
        # Not PEM as-is — the only other sane encoding is base64-wrapped PEM.
        try:
            compact = ''.join(data.split())
            data = base64.b64decode(compact, validate=True).decode('ascii').strip()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(
                'KAFKA_CA_DATA is neither PEM nor base64-encoded PEM'
            ) from exc

    # Secret stores commonly flatten newlines into the two-character escape.
    data = data.replace('\\n', '\n').strip()

    if PEM_CERT_MARKER not in data:
        raise ValueError(f'KAFKA_CA_DATA does not contain a {PEM_CERT_MARKER!r} block')

    # OpenSSL requires the PEM to end with a newline.
    return data + '\n'
