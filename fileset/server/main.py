#!/usr/bin/env python

import appengine_config

import logging
import os
from fileset import config
from fileset.server import blobs
from fileset.server import manifests
from fileset.server import redirects
from fileset.server import utils
from google.appengine.ext.blobstore import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from webob import acceptparse
import webapp2


ES_419_COUNTRIES = frozenset([
    'AR',
    'BO',
    'CL',
    'CO',
    'CR',
    'DO',
    'EC',
    'FK',
    'GF',
    'GT',
    'GY',
    'HN',
    'MX',
    'NI',
    'PA',
    'PE',
    'PR',
    'PY',
    'SR',
    'SV',
    'UY',
    'VE',
])


class MainHandler(blobstore_handlers.BlobstoreDownloadHandler):

    def head(self, *args, **kwargs):
        self.get(*args, **kwargs)

    def get(self, *args, **kwargs):
        path = self.request.path
        self.serve_path(path)

    def serve_path(self, path):
        _, ext = os.path.splitext(path)
        if not ext:
            path = utils.safe_join(path, 'index.html')

        if path.endswith('.html'):
            # Use case-insensitive paths.
            path = path.lower()

            # Set custom HTML response headers from appengine_config.
            html_headers = config.RESPONSE_HEADERS.get('html')
            if html_headers:
                for key, value in html_headers.iteritems():
                    self.response.headers[key] = value

        manifest = self.get_manifest()
        if not manifest:
            return self.serve_error(404)

        # Get the SHA of the file to serve from the manifest.
        sha = None
        if path.endswith('.html'):
            # Check intl fallbacks based on user's country and preferred langs.
            for intl_path in self.generate_intl_paths(path):
                sha = manifest.paths.get(intl_path)
                if sha:
                    break
        else:
            sha = manifest.paths.get(path)

        if not sha:
            return self.serve_error(404, manifest=manifest)

        etag = '"{sha}"'.format(sha=sha)
        request_etag = self.request.headers.get('If-None-Match')
        if etag == request_etag:
            self.response.status = 304
            return
        self.response.headers['ETag'] = etag

        if self.request.method != 'HEAD':
            gcs_path = blobs.get_gcs_path(sha)
            blob_key = blobstore.create_gs_key('/gs' + gcs_path)
            self.send_blob(blob_key)

    def serve_error(self, error_code, manifest=None):
        self.response.status = error_code
        _, ext = os.path.splitext(self.request.path)
        if not ext or ext == '.html':
            html_path = '/{}.html'.format(error_code)
            if not manifest:
                manifest = manifests.get_branch_manifest(utils.DEFAULT_BRANCH)
            if manifest and html_path in manifest.paths:
                self.response.headers['Content-Type'] = 'text/html'
                if self.request.method != 'HEAD':
                    # The blobstore download handler raises an error whenever
                    # the status code is anything other than 200, so write the
                    # contents of the {code}.html file directly to response.
                    sha = manifest.paths[html_path]
                    content = blobs.read(sha)
                    self.response.out.write(content)
                return

        self.response.headers['Content-Type'] = 'text/plain'
        if self.request.method != 'HEAD':
            self.response.out.write(str(error_code) + '\n')

    def get_manifest(self):
        """Returns the manifest for the given request."""
        branch = utils.get_branch(self.request)
        if branch.startswith('manifest-') and branch[9:].isdigit():
            manifest_id = int(branch[9:])
            manifest = manifests.get(manifest_id)
        else:
            manifest = manifests.get_branch_manifest(branch)
        return manifest

    def generate_intl_paths(self, path):
        """Generates a list of paths based on user's country & preferred langs.

        For example, if a user is based in Canada and their browser's language
        settings are:
            - fr
            - en

        Then requests for /foo/ would yield the following paths:
            - /intl/fr_ca/foo/
            - /intl/en_ca/foo/
            - /intl/fr/foo/
            - /intl/en/foo/
            - /foo/

        If ?hl= query param is in the URL, the hl value will be prioritized
        above other paths. For example, for /foo/?hl=de-DE:
            - /intl/de-de_ca/foo/
            - /intl/de_ca/foo/
            - /intl/fr_ca/foo/
            - /intl/en_ca/foo/
            - /intl/de-de/foo/
            - /intl/de/foo/
            - /intl/fr/foo/
            - /intl/en/foo/
            - /foo/
        """
        hl = self.request.get('hl', '').lower()
        country = (self.request.headers.get('X-AppEngine-Country') or 'US').lower()

        accept_lang_value = self.request.headers.get('Accept-Language')
        accept_langs = []
        if accept_lang_value:
            for value, _ in acceptparse.Accept.parse(accept_lang_value):
                lang = value.lower()
                accept_langs.append(lang)

        # Yield `/intl/<lang>_<country>/` paths.
        if hl:
            locale = '{lang}_{country}'.format(lang=hl, country=country)
            yield config.INTL_PATH_FORMAT.format(locale=locale, path=path)
            if '-' in hl:
                lang = hl.split('-', 1)[0]
                locale = '{lang}_{country}'.format(lang=lang, country=country)
                yield config.INTL_PATH_FORMAT.format(locale=locale, path=path)
        for lang in accept_langs:
            locale = '{lang}_{country}'.format(lang=lang, country=country)
            yield config.INTL_PATH_FORMAT.format(locale=locale, path=path)

        # Yield special paths for es-419 countries.
        if country.upper() in ES_419_COUNTRIES and 'es' in accept_langs:
            yield config.INTL_PATH_FORMAT.format(locale='es_419', path=path)
            yield config.INTL_PATH_FORMAT.format(locale='es-419', path=path)

        # Yield paths for `/intl/<lang>/` (no country).
        if hl:
            yield config.INTL_PATH_FORMAT.format(locale=hl, path=path)
            if '-' in hl:
                lang = hl.split('-', 1)[0]
                yield config.INTL_PATH_FORMAT.format(locale=lang, path=path)
        for lang in accept_langs:
            yield config.INTL_PATH_FORMAT.format(locale=lang, path=path)

        yield path


app = redirects.RedirectMiddleware(webapp2.WSGIApplication([
    webapp2.Route('/<path:.*>', handler=MainHandler, name='main'),
]))
