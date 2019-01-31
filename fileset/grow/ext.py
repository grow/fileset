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
        timed_deploys:
          env_name: FILESET_TIMED_DEPLOY_PROD  # YYYY-MM-DD HH:MM
          timezone: America/Los_Angeles
        env:
          name: prod
"""

import datetime
import json
import logging
import os
import time
import grow
import pytz
from grow.common import utils
from grow.deployments import deployments
from grow.deployments.destinations import base as destinations
from grow.pods import env
from fileset.client import fileset
from protorpc import messages

__all__ = ('FilesetDestination', 'FilesetPreprocessor')

OBJECTCACHE_ID = 'fileset'
OBJECTCACHE_ID_LOCAL = 'fileset.local'

CONFIG_PATH = '/.fileset.json'


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


class TimedDeployConfig(messages.Message):
    env_name = messages.StringField(1)
    timezone = messages.StringField(2)


class FilesetDestination(destinations.BaseDestination):
    """Grow deploy destination that deploys to a fileset server."""

    KIND = 'fileset'

    class Config(messages.Message):
        env = messages.MessageField(env.EnvConfig, 1)
        server = messages.StringField(2)
        branch = messages.StringField(3)
        timed_deploys = messages.MessageField(TimedDeployConfig, 4)

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

    def get_timed_deploy(self):
        if not self.config.timed_deploys:
            return None
        env_name = self.config.timed_deploys.env_name
        if not env_name:
            return None
        datetime_str = os.environ.get(env_name)
        if not datetime_str:
            return None

        timezone = self.config.timed_deploys.timezone or 'Americas/Los_Angeles'
        timestamp = self._get_timestamp(datetime_str, timezone)
        now = int(time.time())
        if timestamp <= now:
            return None

        return {
            'datetime': datetime_str,
            'timezone': timezone,
            'timestamp': timestamp,
        }

    def deploy(self, content_generator, stats=None, repo=None, dry_run=False,
               confirm=False, test=True, is_partial=False,
               require_translations=False):
        self._confirm = confirm
        if dry_run:
            return

        server = self.config.server
        branch = self.get_branch()
        timed_deploy = self.get_timed_deploy()

        if confirm:
            lines = [
                '',
                'server: {}'.format(server),
                'branch: {}'.format(branch),
            ]
            if timed_deploy:
                lines.append('timed deploy: {} ({})'.format(
                    timed_deploy['datetime'], timed_deploy['timezone']))
            lines.append('Proceed to deploy?')
            text = '\n'.join(lines)
            if not utils.interactive_confirm(text):
                logging.info('Aborted.')
                return

        if server.startswith('localhost'):
            # Localhost doens't require an auth token.
            token = ''
        if self.pod.file_exists(CONFIG_PATH):
            token = self.pod.read_json(CONFIG_PATH)['token']
        else:
            # TODO(stevenle): print instructions on how to create an auth token.
            logging.error('"token" is required in {}'.format(CONFIG_PATH))
            return

        fs = fileset.FilesetClient(server, token)
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

        deploy_timestamp = None
        if timed_deploy:
            deploy_timestamp = timed_deploy['timestamp']

        fs.set_branch_manifest(
            branch, manifest_id, deploy_timestamp=deploy_timestamp)
        lines = [
            '',
            'saved branch manifest:',
            '  branch: {}'.format(branch),
            '  manifest id: {}'.format(manifest_id),
        ]
        if timed_deploy:
            lines.append('  timed deploy: {} ({})'.format(
                timed_deploy['datetime'], timed_deploy['timezone']))

        lines.extend([
            '',
            'url:',
        ])
        if server.startswith('localhost'):
            lines.append('  http://{}'.format(server))
        elif deploy_timestamp:
            lines.append(
                '  https://manifest-{}-dot-{}'.format(manifest_id, server))
        elif branch == 'master':
            lines.append('  https://{}'.format(server))
        else:
            lines.append('  https://{}-dot-{}'.format(branch, server))

        logging.info('\n'.join(lines))

    def _get_timestamp(self, datetime_str, timezone):
        dt = datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        localized_dt = pytz.timezone(timezone).localize(dt)
        diff = localized_dt - datetime.datetime(1970, 1, 1, tzinfo=pytz.utc)
        ts = int(diff.total_seconds())
        return ts
