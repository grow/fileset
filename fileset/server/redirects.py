#!/usr/bin/env python

import logging
import os
import urllib
import urlparse
import webob
from fileset import config
from fileset.server import routetrie
from fileset.server import utils
from google.appengine.api import users

CANONICAL_DOMAIN = config.CANONICAL_DOMAIN
REDIRECTS = config.REDIRECTS
REQUIRE_AUTH = config.REQUIRE_AUTH
REQUIRE_HTTPS = config.REQUIRE_HTTPS


class RedirectMiddleware(object):
    """WSGI middleware for handling server-side redirects.

    Redirects should be defined in the appengine_config.py file under the
    `fileset_REDIRECTS` variable.

    For example:

        fileset_REDIRECTS = (
            (302, '/foo/', '/bar/'),
            (302, '/bar/:var', 'https://example.com/bar/$var/'),
            (302, '/baz/*wild', '/qux/$wild/'),
        )

    When combined with variable, pattern-based paths, a specific path can be
    prevented from redirecting by using `'no-redirect'` in place of the status
    code, e.g.:

        fileset_REDIRECTS = (
            (302, '/foo/:bar/', '/new/path/$bar/'),
            ('no-redirect', '/foo/baz/', None),
        )

    In the example above, `/foo/hello/` would redirect to `/new/path/hello/`,
    but `/foo/baz/` would not redirect and would serve the path as normal.
    """

    def __init__(self, app):
        self.app = app
        self.redirects = routetrie.RouteTrie()
        self.init_redirects()

    def __call__(self, environ, start_response):
        request = webob.Request(environ)
        try:
            response = self.handle_request(request)
        except Exception:
            logging.exception('middleware exception:')
            response = self.handle_error()
        return response(environ, start_response)

    def handle_request(self, request):
        # Seeing a lot of requests for /%FF for some reason, which errors when
        # webob.Request tries to decode it. Redirect /%FF to /.
        path_info = urllib.quote(os.environ.get('PATH_INFO', ''))
        if path_info.lower() == r'/%ff':
            return self.redirect('/')

        domain = utils.get_domain(request)
        env = utils.get_env(request)

        # Redirect to CANONICAL_DOMAIN.
        if CANONICAL_DOMAIN:
            if env == utils.Env.PROD and domain != CANONICAL_DOMAIN:
                redirect_uri = '{}://{}{}'.format(
                    request.scheme, CANONICAL_DOMAIN, request.path_qs)
                logging.info('redirecting: 302 {} => {}'.format(
                    request.url, redirect_uri))
                return self.redirect(redirect_uri, code=302)

        # Check for https (except on devappserver).
        upgrade_requests = request.headers.get('Upgrade-Insecure-Requests')
        if REQUIRE_HTTPS or upgrade_requests == '1':
            if env != utils.Env.DEV and request.scheme != 'https':
                redirect_uri = 'https://{}{}'.format(
                    domain, request.path_qs)
                logging.info('redirecting: 302 {} => {}'.format(
                    request.url, redirect_uri))
                return self.redirect(redirect_uri, code=302)

        # Require authorized login on Env.STAGING.
        if REQUIRE_AUTH or env == utils.Env.STAGING:
            user = users.get_current_user()
            if not user:
                login_url = users.create_login_url(request.path_qs)
                return self.redirect(login_url)
            if not utils.is_authorized(user.email()):
                logging.info('{} is not authorized to access {}'.format(
                    user.email(), request.url))
                return self.handle_forbidden()

        # Check for redirects file.
        redirect_code, redirect_uri = self.get_redirect_url(request.path)
        if redirect_uri:
            # Preserve query string for relative paths.
            if redirect_uri.startswith('/') and request.query_string:
                if '?' in redirect_uri:
                    parts = urlparse.urlparse(redirect_uri)
                    params = urlparse.parse_qs(parts.query)
                    params.update(urlparse.parse_qs(request.query_string))
                    qsl = []
                    for key, vals in params.iteritems():
                        for val in vals:
                            qsl.append((key, val))
                    redirect_uri = '{}?{}'.format(
                        parts.path, urllib.urlencode(qsl))
                else:
                    redirect_uri = '{}?{}'.format(
                        redirect_uri, request.query_string)

            logging.info(
                'redirecting: {} {} => {}'.format(
                    redirect_code, request.path_qs, redirect_uri))
            return self.redirect(redirect_uri, code=redirect_code)

        # Render the WSGI response.
        return request.get_response(self.app)

    def handle_error(self):
        response = webob.Response()
        response.status = 500
        response.content_type = 'text/plain'
        response.body = 'An unexpected error has occurred.'
        return response

    def handle_forbidden(self):
        response = webob.Response()
        response.status = 403
        response.content_type = 'text/plain'
        response.body = '403 Forbidden'
        return response

    def redirect(self, redirect_uri, code=302):
        """Returns a redirect response."""
        response = webob.Response()
        response.status = code
        response.location = redirect_uri
        response.headers['Cache-Control'] = 'no-cache'
        return response

    def init_redirects(self):
        """Initializes the redirects trie."""
        for code, path, url in REDIRECTS:
            self.redirects.add(path, (code, url))

    def get_redirect_url(self, path):
        """Looks up a redirect URL from the redirects trie."""
        result, params = self.redirects.get(path.lower())
        if not result:
            return None, None

        code, url = result[0], result[1]
        if code == 'no-redirect':
            return None, None

        # Replace `$variable` placeholders in the URL.
        if '$' in url:
            for key, value in params.iteritems():
                if key.startswith(':') or key.startswith('*'):
                    url = url.replace('$' + key[1:], value)

        return code, url
