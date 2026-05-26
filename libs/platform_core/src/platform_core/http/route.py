

class Route:
    def __init__(self, path: str, *,
                 after_request: AfterRequestHookHandler | None = None):
        self.path = path
        self.handler = handler
        self.methods = methods or ["GET"]