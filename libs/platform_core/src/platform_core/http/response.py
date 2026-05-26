class Response:
    """
    Base HTTP response class, used as the basis for all other response classes.
    This class actually will wrap fastapi or litestar response, and provide a consistent interface for the rest of the codebase.
     - This will allow us to easily switch between different HTTP frameworks in the future if needed, without having to change the rest of the codebase.
     - And also, this will allow us to have a consistent way of handling responses across different HTTP frameworks.
    """
