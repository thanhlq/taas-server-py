"""
A central place for providing actual implementations to the foundation library.
"""
from foundation.utils.singleton import singleton
from foundation.resiliant.types import ResiliantServiceFactoryT


@singleton
class FoundationFactory:
    """
    Factory for settings
    """

    _resiliant_factory: ResiliantServiceFactoryT | None = None

    def __new__(cls, *args, **kwargs):
        raise RuntimeError("UtilityClass cannot be instantiated")

    @staticmethod
    def use_resiliant(factory: ResiliantServiceFactoryT):
        """
        Set the resiliant service factory to be used by the application.
        """

        if FoundationFactory._resiliant_factory is not None:
            raise RuntimeError('Resiliant service factory has already been set.')

        from .resiliant import register_factory

        register_factory(factory)
        FoundationFactory._resiliant_factory = factory
