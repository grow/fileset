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
import sys
import threading
import time
import grow
import pytz
from concurrent import futures
from grow import extensions
from grow.common import utils
from grow.deployments import deployments
from grow.deployments.destinations import base as destinations
from grow.extensions import hooks
from grow.pods import env
from fileset.client import fileset
from protorpc import messages

__all__ = ('FilesetDestination', 'FilesetExtension', 'FilesetPreprocessor')

IS_PY3 = sys.version_info[0] >= 3

OBJECTCACHE_ID = 'fileset'
OBJECTCACHE_ID_LOCAL = 'fileset.local'

CONFIG_PATH = '/.fileset.json'


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
        # Prefix to append to the branch name when branch="auto" is used.
        branch_prefix = messages.StringField(4)
        timed_deploys = messages.MessageField(TimedDeployConfig, 5)
        debug = messages.BooleanField(6)

    def __init__(self, *args, **kwargs):
        super(FilesetDestination, self).__init__(*args, **kwargs)
        self._objectcache = None
        self.objectcache_lock = threading.RLock()

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

        if self.config.debug:
            self.pod.logger.info('environ: {}'.format(os.environ))

        if os.environ.get('FILESET_BRANCH_NAME'):
            branch = os.environ['FILESET_BRANCH_NAME']
        elif os.environ.get('BRANCH_NAME'):
            # Google Cloud Build uses "BRANCH_NAME" environ variable.
            # https://cloud.google.com/cloud-build/docs/configuring-builds/substitute-variable-values
            branch = os.environ['BRANCH_NAME']
        elif os.environ.get('CI_COMMIT_REF_NAME'):
            # Gitlab uses a detached git reference, so use the
            # "CI_COMMIT_REF_NAME" environ variable instead.
            branch = os.environ['CI_COMMIT_REF_NAME']
        else:
            repo = utils.get_git_repo(self.pod.root)
            branch = repo.active_branch.name

        if branch.startswith('feature/'):
            branch = branch[8:]
        branch = branch.replace('/', '-').lower()

        # Append branch prefix.
        branch_prefix = self.config.branch_prefix or ''
        return branch_prefix + branch

    def get_commit(self):
        if self.config.debug:
            self.pod.logger.info('environ: {}'.format(os.environ))

        if os.environ.get('FILESET_COMMIT_SHA'):
            sha = os.environ['FILESET_COMMIT_SHA']
            message = os.environ.get('FILESET_COMMIT_TITLE', '')
        elif os.environ.get('COMMIT_SHA'):
            # Google Cloud Build uses "BRANCH_NAME" environ variable.
            # https://cloud.google.com/cloud-build/docs/configuring-builds/substitute-variable-values
            sha = os.environ['COMMIT_SHA']
            message = ''
        elif os.environ.get('CI_COMMIT_SHA'):
            # Gitlab uses a detached git reference, so use the
            # "CI_COMMIT_SHA" environ variable instead.
            sha = os.environ['CI_COMMIT_SHA']
            message = os.environ.get('CI_COMMIT_TITLE', '')
        else:
            repo = utils.get_git_repo(self.pod.root)
            if repo and repo.active_branch:
                commit = repo.active_branch.commit
                sha = commit.hexsha
                message = commit.message.split('\n', 1)[0]
            else:
                sha = ''
                message = ''
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
        elif self.pod.file_exists(CONFIG_PATH):
            token = self.pod.read_json(CONFIG_PATH)['token']
        elif os.environ.get('FILESET_TOKEN'):
            token = os.environ['FILESET_TOKEN']
        else:
            logging.error('"token" is required in {}'.format(CONFIG_PATH))
            logging.error(
                'visit {}/_fs/token to generate a new token'.format(server))
            return

        api_host = server
        if branch != 'master':
            api_host = '{}-dot-{}'.format(branch, server)
        fs = fileset.FilesetClient(api_host, token)
        manifest = {
            'commit': self.get_commit(),
            'files': [],
        }

        # Warm the cache by fetching the current manifest.
        if not server.startswith('localhost'):
            self._warm_up_cache(fs, branch)

        with futures.ThreadPoolExecutor(max_workers=20) as executor:
            # Map of future => doc path.
            results = {}
            for rendered_doc in content_generator:
                future = executor.submit(self._upload_blob, fs, rendered_doc)
                results[future] = rendered_doc.path

            for future in futures.as_completed(results):
                try:
                    data = future.result()
                except Exception as e:
                    # If any upload fails, write the objectcache to file so we
                    # don't lose information about what was already uploaded.
                    self.pod.podcache.write()
                    doc_path = results.get(future)
                    logging.error('failed to upload: {}'.format(doc_path))
                    raise
                manifest['files'].append(data)

        self.pod.podcache.write()
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

    def _upload_blob(self, fs, rendered_doc, num_tries=0):
        sha = rendered_doc.hash
        path = rendered_doc.path
        blobkey = '{server}::blob::{sha}'.format(
            server=self.config.server, sha=sha)
        if not self.objectcache.get(blobkey) and not fs.blob_exists(sha):
            logging.info('uploading blob {} {}'.format(sha, path))
            try:
                fs.upload_blob(sha, path, rendered_doc.read())
            except Exception as e:
                logging.error('failed to upload {}'.format(path))
                if num_tries <= 2:
                    logging.error('retrying upload blob...')
                    return self._upload_blob(
                        fs, rendered_doc, num_tries=num_tries + 1)
                raise
            with self.objectcache_lock:
                self.objectcache.add(blobkey, 1)
        return {'sha': sha, 'path': path}

    def _get_timestamp(self, datetime_str, timezone):
        dt = datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        localized_dt = pytz.timezone(timezone).localize(dt)
        diff = localized_dt - datetime.datetime(1970, 1, 1, tzinfo=pytz.utc)
        ts = int(diff.total_seconds())
        return ts

    def _warm_up_cache(self, fs, branch):
        try:
            response = fs.get_branch_manifest(branch)
            manifest = response.get('manifest')
            if not manifest:
                return
            paths = manifest.get('paths') or {}
            for path, blobkey in paths.items():
                    self.objectcache.add(blobkey, 1)
            logging.info('warmed up fileset cache')
        except Exception as e:
            logging.error('failed to warm fileset cache')
            logging.error(e)
            pass


class FilesetPreprocessor(grow.Preprocessor):
    """Preprocessor for grow that sets up the fileset deploy destination.

    Deprecated: Use `FilesetExtension` instead.
    """

    KIND = 'fileset'

    class Config(messages.Message):
        pass

    def __init__(self, *args, **kwargs):
        super(FilesetPreprocessor, self).__init__(*args, **kwargs)
        if IS_PY3:
            self.pod.logger.error('Update your fileset config to support grow 1.0.0')
            self.pod.logger.error('More info: https://github.com/grow/fileset/wiki/Migrate-to-grow-1.0.0')
        else:
            if deployments._destination_kinds_to_classes is None:
                deployments.register_builtins()
            if self.KIND not in deployments._destination_kinds_to_classes:
                deployments.register_destination(FilesetDestination)

    def run(self, build=True):
        # Intentionally empty. Since preprocessors are initialized before
        # deployment destinations, we use the preprocessor's constructor to
        # inject a custom destination into grow's list of registered
        # destinations.
        pass


class FilesetDeploymentRegisterHook(hooks.DeploymentRegisterHook):
    """Hook to register a FilesetDestination."""

    def trigger(self, previous_result, deployments, *_args, **_kwargs):
        deployments.register_destination(FilesetDestination)


class FilesetExtension(extensions.BaseExtension):
    """Extension for handling core deployment functionality."""

    @property
    def available_hooks(self):
        """Returns the available hook classes."""
        return [FilesetDeploymentRegisterHook]
