import multiprocessing
import platform

from .facade.base import BaseService

if platform.system() == "Darwin":
    # On macOS, the default start method is "spawn",
    # which can lead to issues with certain libraries and frameworks that expect the "fork" behavior. Setting the start method to "fork" can help avoid these issues.
    multiprocessing.set_start_method("fork", force=True)

__all__: list[str] = ["BaseService"]
