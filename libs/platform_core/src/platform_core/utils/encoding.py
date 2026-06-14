def to_base64(s: str) -> str:
    import base64

    string_bytes = s.encode('utf-8')

    # 2. Base64 encode the bytes
    base64_bytes = base64.b64encode(string_bytes)

    # 3. Decode the Base64 bytes back to a string for display (optional)
    base64_string = base64_bytes.decode('ascii')
    return base64_string


def from_base64(b64_string: str) -> str:
    import base64

    # 1. Encode the string to bytes
    base64_bytes = b64_string.encode('ascii')

    # 2. Base64 decode the bytes
    string_bytes = base64.b64decode(base64_bytes)

    # 3. Decode the bytes back to a string
    original_string = string_bytes.decode('utf-8')
    return original_string
