#!/usr/bin/env python

from google.appengine.api import lib_config


class ConfigDefaults(object):
    """Configuration defaults for appengine_config.py.

    To override any of these config values, add the value to appengine_config.py
    prefixed by fileset_.

    For example, to change the name of the default branch from "master" to
    "prod", add the following line to appengine_config.py:

            fileset_DEFAULT_BRANCH = 'prod'
    """

    # List of email domains that are authorized to access Env.STAGING.
    AUTHORIZED_ORGS = frozenset()

    # List of emails that are authorized to access Env.STAGING.
    AUTHORIZED_USERS = frozenset()

    # If provided, any Env.PROD requests that do not match the CANONICAL_DOMAIN
    # will be redirected there with the path and query strings preserved. Useful
    # for redirecting "www" to the naked domain (or vice versa), for example.
    CANONICAL_DOMAIN = None

    # The name of the default branch to use if a branch isn't inferred from the
    # URL. Requests to Env.PROD will always read from the DEFAULT_BRANCH.
    DEFAULT_BRANCH = 'master'

    # A list of redirects, formatted as:
    #
    #     (code, source, dest)
    #
    # Where:
    #
    #     * `code` is either 301 or 302
    #     * `source` is the source path, which can accept `:placeholder`
    #       and `*wildcard` values
    #     * `dest` is the destination url, which can accept $param values
    REDIRECTS = tuple()

    # Whether to require authentication, even on Env.PROD.
    REQUIRE_AUTH = False

    # Whether to enforce https for all Env.PROD requests.
    REQUIRE_HTTPS = False

    # HTTP response headers to append to certain requests. Right now, only
    # supports headers for HTML files.
    RESPONSE_HEADERS = {
        'html': {
            'X-Frame-Options': 'deny',
        },
    }


config = lib_config.register('fileset', ConfigDefaults.__dict__)

AUTHORIZED_ORGS = config.AUTHORIZED_ORGS
AUTHORIZED_USERS = config.AUTHORIZED_USERS
CANONICAL_DOMAIN = config.CANONICAL_DOMAIN
DEFAULT_BRANCH = config.DEFAULT_BRANCH
REDIRECTS = config.REDIRECTS
REQUIRE_AUTH = config.REQUIRE_AUTH
REQUIRE_HTTPS = config.REQUIRE_HTTPS
RESPONSE_HEADERS = config.RESPONSE_HEADERS
