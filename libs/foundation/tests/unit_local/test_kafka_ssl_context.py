"""Unit tests for the Kafka TLS trust-anchor resolution in ``MessagingConfig``.

Covers the CA-file path, the three accepted ``KAFKA_CA_DATA`` encodings, their
precedence, and the failure modes — no broker required.
"""

from __future__ import annotations

import base64
import datetime
import ssl

import pytest
from foundation.messaging.config.messaging_config import (
    MessagingConfig,
    normalize_ca_data,
)


def _self_signed_ca_pem() -> str:
    """
    Mint a throwaway self-signed CA, mirroring the Strimzi dev CA's shape:
    ``basicConstraints=CA:TRUE`` and *no* ``keyUsage`` extension (the case that
    Python 3.13+ strict verification rejects).
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, 'taas-unit-test-ca')]
    )
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode().strip()


CA_PEM = _self_signed_ca_pem()


def _config(**overrides) -> MessagingConfig:
    """A TLS-enabled config; strict verification is off unless overridden."""
    return MessagingConfig(
        **{
            'kafka_security_protocol': 'SASL_SSL',
            'kafka_ssl_strict_verify': False,
            **overrides,
        }
    )


class TestNormalizeCaData:
    def test_accepts_multiline_pem(self) -> None:
        assert normalize_ca_data(CA_PEM).startswith('-----BEGIN CERTIFICATE-----')

    def test_appends_trailing_newline(self) -> None:
        assert normalize_ca_data(CA_PEM).endswith('-----END CERTIFICATE-----\n')

    def test_expands_escaped_newlines(self) -> None:
        """CI secret stores commonly flatten the PEM to a single line."""
        flattened = CA_PEM.replace('\n', '\\n')
        assert normalize_ca_data(flattened) == normalize_ca_data(CA_PEM)

    def test_decodes_base64_pem(self) -> None:
        """A Kubernetes secret value is base64 of the whole PEM file."""
        encoded = base64.b64encode(CA_PEM.encode()).decode()
        assert normalize_ca_data(encoded) == normalize_ca_data(CA_PEM)

    def test_tolerates_surrounding_whitespace(self) -> None:
        assert normalize_ca_data(f'  \n{CA_PEM}\n  ') == normalize_ca_data(CA_PEM)

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match='neither PEM nor base64'):
            normalize_ca_data('not-a-certificate!!')

    def test_rejects_base64_of_non_pem(self) -> None:
        encoded = base64.b64encode(b'hello world').decode()
        with pytest.raises(ValueError, match='BEGIN CERTIFICATE'):
            normalize_ca_data(encoded)


class TestBuildKafkaSslContext:
    def test_none_for_plaintext(self) -> None:
        config = MessagingConfig(kafka_security_protocol='PLAINTEXT')
        assert config.build_kafka_ssl_context() is None

    def test_none_for_sasl_plaintext(self) -> None:
        config = MessagingConfig(kafka_security_protocol='SASL_PLAINTEXT')
        assert config.build_kafka_ssl_context() is None

    def test_loads_ca_from_file(self, tmp_path) -> None:
        ca_file = tmp_path / 'ca.crt'
        ca_file.write_text(CA_PEM + '\n')

        context = _config(kafka_ssl_ca_location=str(ca_file)).build_kafka_ssl_context()

        assert context is not None
        assert len(context.get_ca_certs()) == 1

    def test_loads_ca_from_inline_data(self) -> None:
        context = _config(kafka_ssl_ca_data=CA_PEM).build_kafka_ssl_context()

        assert context is not None
        assert len(context.get_ca_certs()) == 1

    def test_file_and_data_load_the_same_anchor(self, tmp_path) -> None:
        ca_file = tmp_path / 'ca.crt'
        ca_file.write_text(CA_PEM + '\n')

        from_file = _config(kafka_ssl_ca_location=str(ca_file)).build_kafka_ssl_context()
        from_data = _config(kafka_ssl_ca_data=CA_PEM).build_kafka_ssl_context()

        assert from_file and from_data
        assert from_file.get_ca_certs() == from_data.get_ca_certs()

    def test_ca_file_wins_over_ca_data(self, tmp_path) -> None:
        """Explicit path beats injected data so a mount can override a default."""
        ca_file = tmp_path / 'ca.crt'
        ca_file.write_text(CA_PEM + '\n')

        config = _config(
            kafka_ssl_ca_location=str(ca_file), kafka_ssl_ca_data='not-a-certificate!!'
        )

        # No ValueError => the invalid inline data was never parsed.
        assert config.build_kafka_ssl_context() is not None

    def test_missing_ca_file_raises(self, tmp_path) -> None:
        config = _config(kafka_ssl_ca_location=str(tmp_path / 'absent.crt'))
        with pytest.raises(FileNotFoundError, match='KAFKA_SSL_CA_LOCATION'):
            config.build_kafka_ssl_context()

    def test_falls_back_to_system_trust_store(self) -> None:
        context = _config().build_kafka_ssl_context()

        assert context is not None
        assert context.verify_mode == ssl.CERT_REQUIRED

    def test_strict_verify_flag_is_honoured(self) -> None:
        strict = _config(
            kafka_ssl_ca_data=CA_PEM, kafka_ssl_strict_verify=True
        ).build_kafka_ssl_context()
        relaxed = _config(kafka_ssl_ca_data=CA_PEM).build_kafka_ssl_context()

        assert strict and relaxed
        assert strict.verify_flags & ssl.VERIFY_X509_STRICT
        assert not relaxed.verify_flags & ssl.VERIFY_X509_STRICT

    def test_check_hostname_flag_is_honoured(self) -> None:
        config = _config(kafka_ssl_ca_data=CA_PEM, kafka_ssl_check_hostname=False)
        context = config.build_kafka_ssl_context()

        assert context is not None
        assert context.check_hostname is False


class TestTrustSourceDescription:
    def test_reports_file(self) -> None:
        assert _config(kafka_ssl_ca_location='/tmp/ca.crt').kafka_ssl_trust_source == (
            'file:/tmp/ca.crt'
        )

    def test_reports_inline_data_without_leaking_it(self) -> None:
        source = _config(kafka_ssl_ca_data=CA_PEM).kafka_ssl_trust_source
        assert 'KAFKA_CA_DATA' in source
        assert 'BEGIN CERTIFICATE' not in source

    def test_reports_system_default(self) -> None:
        assert _config().kafka_ssl_trust_source == 'system trust store'

    def test_ca_data_is_described_only_when_no_file(self) -> None:
        config = _config(kafka_ssl_ca_location='/tmp/ca.crt', kafka_ssl_ca_data=CA_PEM)
        assert config.kafka_ssl_trust_source == 'file:/tmp/ca.crt'
