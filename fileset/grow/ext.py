#!/usr/bin/env python

"""Fileset extensions for grow.

Sample podspec:

    extensions:
      preprocessors:
      - extensions.fileset.grow.FilesetPreprocessor

    preprocessors:
    - kind: fileset

    deployments:
      localhost:
        destination: fileset
        host: localhost:8088
        env:
          name: local
      staging:
        destination: fileset
        host: APPID.appspot.com
        env:
          name: staging
      prod:
        destination: fileset
        host: APPID.appspot.com
        env:
          name: prod
"""

import json
import logging
import grow
from grow.common import utils
from grow.deployments import deployments
from grow.deployments.destinations import base as destinations
from grow.pods import env
from fileset.client import fileset
from protorpc import messages

__all__ = ('FilesetDestination', 'FilesetPreprocessor')

OBJECTCACHE_ID = 'fileset'
OBJECTCACHE_ID_LOCAL = 'fileset.local'


class FilesetPreprocessor(grow.Preprocessor):
    """Preprocessor for grow that sets up the fileset deploy destination."""

    KIND = 'fileset'

    class Config(messages.Message):
        pass

    def __init__(self, *args, **kwargs):
        super(FilesetPreprocessor, self).__init__(*args, **kwargs)
        if deployments._destination_kinds_to_classes is None:
            deployments._destination_kinds_to_classes = {}
        if self.KIND not in deployments._destination_kinds_to_classes:
            deployments.register_destination(FilesetDestination)

    def run(self, build=True):
        # Intentionally empty. Since preprocessors are initialized before
        # deployment destinations, we use the preprocessor's constructor to
        # inject a custom destination into grow's list of registered
        # destinations.
        pass


class FilesetDestination(destinations.BaseDestination):
    """Grow deploy destination that deploys to a fileset server."""

    KIND = 'fileset'

    class Config(messages.Message):
        env = messages.MessageField(env.EnvConfig, 1)
        server = messages.StringField(2)
        branch = messages.StringField(3)

    def __init__(self, *args, **kwargs):
        super(FilesetDestination, self).__init__(*args, **kwargs)
        self._objectcache = None

    @property
    def objectcache(self):
        if self._objectcache is None:
            objectache_id = OBJECTCACHE_ID
            if self.config.server.startswith('localhost'):
                objectache_id = OBJECTCACHE_ID_LOCAL
            self._objectcache = self.pod.podcache.get_object_cache(
                objectache_id, write_to_file=True, separate_file=True)
        return self._objectcache

    def get_branch(self):
        if self.config.branch and not self.config.branch == 'auto':
            return self.config.branch

        # Always use "master" on localhost.
        if self.config.server.startswith('localhost'):
            return 'master'

        repo = utils.get_git_repo(self.pod.root)
        branch = repo.active_branch.name
        if branch.startswith('feature/'):
            branch = branch[8:]
        branch = branch.replace('/', '-').lower()
        return branch

    def get_commit(self):
        repo = utils.get_git_repo(self.pod.root)
        commit = repo.active_branch.commit
        sha = commit.hexsha
        message = commit.message.split('\n', 1)[0]
        return {
            'sha': sha,
            'message': message,
        }
        return commit

    def deploy(self, content_generator, stats=None, repo=None, dry_run=False,
               confirm=False, test=True, is_partial=False,
               require_translations=False):
        self._confirm = confirm
        if dry_run:
            return

        server = self.config.server
        branch = self.get_branch()
        if confirm:
            text = '\n'.join([
                '',
                'server: {}'.format(server),
                'branch: {}'.format(branch),
                'Proceed to deploy?',
            ])
            if not utils.interactive_confirm(text):
                logging.info('Aborted.')
                return

        fs = fileset.FilesetClient(server, 'token')
        manifest = {
            'commit': self.get_commit(),
            'files': [],
        }

        for rendered_doc in content_generator:
            sha = rendered_doc.hash
            path = rendered_doc.path
            blobkey = '{server}::blob::{sha}'.format(server=server, sha=sha)
            if not self.objectcache.get(blobkey) and not fs.blob_exists(sha):
                logging.info('uploading blob {} {}'.format(sha, path))
                fs.upload_blob(sha, path, rendered_doc.read())
                self.objectcache.add(blobkey, 1)
            manifest['files'].append({'sha': sha, 'path': path})

        response = fs.upload_manifest(manifest)
        manifest_id = response.json()['manifest_id']

        fs.set_branch_manifest(branch, manifest_id)
        lines = [
            '',
            'saved branch manifest:',
            '  branch: {}'.format(branch),
            '  manifest id: {}'.format(manifest_id),
            '',
            'url:',
        ]
        if server.startswith('localhost'):
            lines.append('  http://{}'.format(server))
        elif branch == 'master':
            lines.append('  https://{}'.format(server))
        else:
            lines.append('  https://{}-dot-{}'.format(server))
        logging.info('\n'.join(lines))
