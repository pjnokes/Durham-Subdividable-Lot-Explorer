"""Shared fixtures and CLI options for the test suite."""


def pytest_addoption(parser):
    parser.addoption("--prod", action="store_true", help="Run against production")
    parser.addoption("--local", action="store_true", help="Run against local (default)")
    parser.addoption("--base-url", default=None, help="Custom base URL")
