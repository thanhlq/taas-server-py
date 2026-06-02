from platform_core.http import BaseController, get, post


class UserController(BaseController):
    """User Account Controller."""

    path = '/api/v1/users'
    tags = ['Users']

    # Define your endpoints here, for example:
    @get('/')
    def list_users(self):
        """List all users."""
        pass

    @post('/')
    def create_user(self):
        """Create a new user."""
        pass
