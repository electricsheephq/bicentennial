"""Service configuration accessors."""

from service.config import load


def settings():
    return load("config/settings.toml")


def flags():
    return load("config/flags.toml")


def routes():
    return load("service/routes.toml")


def flag(name):
    return flags()[name]
