from fastapi.responses import JSONResponse
from platform_core.http import AppConfig
from fastapi import FastAPI


def build_app(config: AppConfig) -> FastAPI:

    app = FastAPI(
        default_response_class=config.default_response_class or JSONResponse,
        swagger_ui_parameters={
            'deepLinking': False,
            # OAuth2 redirect endpoint (automatically provided by FastAPI)
            'oauth2RedirectUrl': 'https://api.eworksuite.com/docs/oauth2-redirect',
            # Use PKCE for added security
            'usePkceWithAuthorizationCodeGrant': True,
        },
        # OAuth2 initialization parameters
        swagger_ui_init_oauth={
            'clientId': 'eworksuite-web',
            # "clientSecret": settings.KEYCLOAK_LOGIN_CLIENT_SECRET,  # Uncomment only if using confidential client
            'appName': f'{config.app_name} API Documentation',
            'scopes': 'openid profile email',
            'usePkceWithAuthorizationCodeGrant': True,
        },
    )

    app.add_api_route(
        '/', lambda: {'message': f'Hello from {config.app_name}!'}, methods=['GET']
    )

    return app
