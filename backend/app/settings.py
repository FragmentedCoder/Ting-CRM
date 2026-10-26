from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment (see deploy/.env.example)."""

    model_config = SettingsConfigDict(env_prefix="TING_")

    data_dir: str = "/data"
    master_key_path: str = "/etc/ting/master.key"
    # The address people open Þing at. Passkeys are bound to its host name,
    # which must be a name, not an IP address.
    address: str = "https://localhost"
    # The volume the app shares with Caddy for its TLS settings, and Caddy's name.
    tls_dir: str = "/tls"
    caddy_host: str = "caddy"


settings = Settings()
