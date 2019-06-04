#!/usr/bin/env python

import os
from fileset import config
from google.appengine.api import app_identity

AUTHORIZED_ORGS = config.AUTHORIZED_ORGS
AUTHORIZED_USERS = config.AUTHORIZED_USERS

STAGING_SUFFIX = 'appspot.com'
DEFAULT_BRANCH = config.DEFAULT_BRANCH


class Env(object):
    DEV = 0      # localhost
    STAGING = 1  # appspot.com
    PROD = 2     # all others


def get_env(request):
    if os.getenv('SERVER_SOFTWARE', '').startswith('Dev'):
        return Env.DEV
    domain = get_domain(request)
    if domain.endswith(STAGING_SUFFIX):
        return Env.STAGING
    return Env.PROD


def get_branch(request):
    env = get_env(request)
    if env != Env.STAGING:
        return DEFAULT_BRANCH

    domain = get_domain(request)
    app_id = app_identity.get_application_id()
    root_domain = '{}.{}'.format(app_id, STAGING_SUFFIX)

    version = domain[:-1 * len(root_domain)]
    if not version:
        return DEFAULT_BRANCH

    branch = version.split('-dot-', 1)[0]
    return branch


def is_authorized(email):
    if email in AUTHORIZED_USERS:
        return True
    org = email.split('@')[-1]
    return org in AUTHORIZED_ORGS


def get_domain(request):
    """Returns the domain portion of the host value."""
    domain = request.host
    if ':' in domain:
        domain = domain.split(':', 1)[0]
    return domain


def safe_join(base, *paths):
    result = base
    for path in paths:
        # Prevent directory traversal attacks by preventing intermediate paths
        # that start with a slash.
        if path.startswith('/'):
          raise ValueError(
                'Intermediate path cannot start with slash: {}'.format(path))

        if result == '' or result.endswith('/'):
            result += path
        else:
            result += '/' + path
    return result
