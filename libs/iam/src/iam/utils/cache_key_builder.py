from iam.iam_constants import IamConstants


class IamCacheKeyBuilder:

    # prevent instantiation
    def __new__(cls):
        raise NotImplementedError("This class cannot be instantiated.")

    @staticmethod
    def build_signup_otp_key(email: str) -> str:
        return f'{IamConstants.CACHE_SIGNUP_OTP_PREFIX}{email}'
