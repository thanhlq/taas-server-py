from fastapi import FastAPI
from fastapi.responses import JSONResponse
from foundation.http import AppConfig

from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse


def create_app(config: AppConfig, **kwargs) -> FastAPI:
    # 1. Important
    config.default_response_class = MsgSpecJSONResponse

    # 2. Create FastAPI app with custom settings
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
            'appName': f'{config.name} API Documentation',
            'scopes': 'openid profile email',
            'usePkceWithAuthorizationCodeGrant': True,
        },
        **kwargs,
    )

    # 3. Tracing
    from foundation.observability.tracing_factory import TracingFactory

    ins_settings = config.get_instrumentation_settings()
    ins_settings.fastapi_app = app
    TracingFactory().init_instrumentation(ins_settings)

    # 4. Configure the app with our custom settings and middlewares
    from .configuration import configure_app

    configure_app(app, config, **kwargs)

    # 5. Return the application instance
    return app
