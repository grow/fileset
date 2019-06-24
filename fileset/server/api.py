#!/usr/bin/env python

import hashlib
import json
import logging
import mimetypes
import os
import webapp2
from fileset.server import auth
from fileset.server import blobs
from fileset.server import manifests
from google.appengine.api import users
from google.appengine.ext import ndb


class RpcHandler(webapp2.RequestHandler):

    def post(self):
        if not self._is_authorized():
            return self.json({'success': False, 'error': 'unauthorized'}, status=403)

        try:
            self._handle()
        except Exception as e:
            logging.exception('request failed')
            return self.json({
                'success': False,
                'error': 'unknown server error'
            }, status=500)

    def get(self):
        if self.request.headers.get('X-Appengine-Cron', '').lower() == 'true':
            return self.post()
        return self.json({
            'success': False,
            'error': 'method not supported',
        }, status=405)

    def _is_authorized(self):
        if os.getenv('SERVER_SOFTWARE', '').startswith('Dev'):
            return True
        if self.request.headers.get('X-Appengine-Cron', '').lower() == 'true':
            return True
        token = self.request.headers.get('X-Fileset-Token')
        return token and auth.is_token_valid(token)

    def _handle(self):
        raise NotImplementedError('subclasses should implement')

    def json(self, data, status=200):
        """Writes JSON data to the response."""
        self.response.set_status(status)
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps(data))


class ManifestUploadHandler(RpcHandler):

    def _handle(self):
        content = self.request.body
        data = json.loads(content)

        paths = {}
        for file_data in data['files']:
            sha = file_data['sha']
            path = file_data['path']
            paths[path] = sha

        commit = data['commit']
        manifest_id = manifests.save(commit, paths)

        return self.json({
            'success': True,
            'manifest_id': manifest_id,
        })


class BlobUploadHandler(RpcHandler):

    def _handle(self):
        request_sha = self.request.get('sha')
        file_object = self.request.POST.multi.get('blob')
        if file_object is None:
            return self.json({
                'error': 'missing required file: "blob"',
                'success': False,
            }, status=400)

        filename = file_object.filename
        content_type, _ = mimetypes.guess_type(filename)
        content = file_object.file.read()

        try:
            blobs.write(request_sha, content, content_type)
            return self.json({'success': True, 'sha': request_sha})
        except blobs.Error as e:
            return self.json({
                'error': str(e),
                'success': False,
            }, status=400)


class BlobExistsHandler(RpcHandler):

    def _handle(self):
        request_sha = self.request.get('sha')
        exists = blobs.exists(request_sha)
        return self.json({
            'success': True,
            'sha': request_sha,
            'exists': exists,
        })


class BranchSetManifestHandler(RpcHandler):

    def _handle(self):
        content = self.request.body
        data = json.loads(content)

        branch = data['branch']
        manifest_id = data['manifest_id']
        deploy_timestamp = data.get('deploy_timestamp')
        manifests.set_branch_manifest(
            branch, manifest_id, deploy_timestamp=deploy_timestamp)

        return self.json({
            'success': True,
            'branch': branch,
            'manifest_id': manifest_id,
            'deploy_timestamp': deploy_timestamp,
        })


class CronTimedDeployHandler(RpcHandler):

    def _handle(self):
        deployments = manifests.handle_timed_deploys()
        if deployments:
            logging.info('deployed: %s', json.dumps(deployments, indent=2))
        return self.json({
            'success': True,
            'deployments': deployments,
        })


class TokenHandler(webapp2.RequestHandler):
    """Handler that generates an auth token for a user."""

    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'

        if not users.is_current_user_admin():
            self.response.set_status(401)
            self.response.out.write('unauthorized')
            return

        user = users.get_current_user()
        desc = user.email()
        token = auth.create_auth_token(desc)

        lines = [
            'save the following to .fileset.json:',
            '',
            '{"token": "%s"}' % token,
            '',
        ]
        payload = '\n'.join(lines)
        self.response.out.write(payload)


app = ndb.toplevel(webapp2.WSGIApplication([
    webapp2.Route('/_fs/api/blob.exists', handler=BlobExistsHandler),
    webapp2.Route('/_fs/api/blob.upload', handler=BlobUploadHandler),
    webapp2.Route('/_fs/api/branch.set_manifest', handler=BranchSetManifestHandler),
    webapp2.Route('/_fs/api/cron.timed_deploy', handler=CronTimedDeployHandler),
    webapp2.Route('/_fs/api/manifest.upload', handler=ManifestUploadHandler),
    webapp2.Route('/_fs/token', handler=TokenHandler),
]))
