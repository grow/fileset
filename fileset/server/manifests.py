#!/usr/bin/env python

import datetime
import logging
import time
from google.appengine.ext import ndb


class FilesetManifest(ndb.Model):
    commit = ndb.JsonProperty()
    paths = ndb.JsonProperty()
    created = ndb.DateTimeProperty(auto_now_add=True)

    @property
    def id(self):
        if not self.key:
            return None
        return self.key.id()

    def json(self):
        return {
            'paths': self.paths,
        }


class FilesetBranchManifest(ndb.Model):
    # Keyed by the name of the branch.
    manifest = ndb.KeyProperty(kind='FilesetManifest', required=True)


class FilesetTimedDeploy(ndb.Model):
    deploy_timestamp = ndb.IntegerProperty(required=True)
    branch = ndb.StringProperty(required=True)
    manifest = ndb.KeyProperty(kind='FilesetManifest', required=True)
    created_at = ndb.DateTimeProperty(auto_now_add=True)
    deployed = ndb.DateTimeProperty()


def get(manifest_id):
    return FilesetManifest.get_by_id(manifest_id)


def save(commit, paths):
    manifest = FilesetManifest()
    manifest.commit = commit
    manifest.paths = paths
    manifest.put()
    return manifest.id


def set_branch_manifest(branch, manifest_id, deploy_timestamp=None):
    timestamp = int(time.time())
    if deploy_timestamp and deploy_timestamp > timestamp:
        _create_timed_deploy(branch, manifest_id, deploy_timestamp)
    else:
        _set_branch_manifest(branch, manifest_id)


def _set_branch_manifest(branch, manifest_id):
    manifest_key = ndb.Key('FilesetManifest', manifest_id)
    branch_manifest = FilesetBranchManifest(id=branch)
    branch_manifest.manifest = manifest_key
    branch_manifest.put()
    logging.info(
        'saved branch manifest: branch=%s, manifest=%s',
        branch, manifest_id)


def _create_timed_deploy(branch, manifest_id, deploy_timestamp):
    manifest_key = ndb.Key('FilesetManifest', manifest_id)

    # Key the timed deploy by the branch name so that only one timed deploy for
    # a branch can exist at any time. Subsequent timed deploys would overwrite
    # the existing one.
    ndb_key = branch
    timed_deploy = FilesetTimedDeploy(id=ndb_key)
    timed_deploy.deploy_timestamp = deploy_timestamp
    timed_deploy.branch = branch
    timed_deploy.manifest = manifest_key
    timed_deploy.deployed = None
    timed_deploy.put()
    logging.info(
        'saved timed deploy: branch=%s, manifest=%s, deploy_timstamp=%s',
        branch, manifest_id, deploy_timestamp)


def get_branch_manifest(branch):
    branch_manifest = FilesetBranchManifest.get_by_id(branch)
    if not branch_manifest:
        return None
    return branch_manifest.manifest.get()


def handle_timed_deploys():
    deployments = []
    timestamp = int(time.time()) + 1
    query = FilesetTimedDeploy.gql(
        'WHERE deploy_timestamp < :1 AND deployed = NULL ORDER BY deploy_timestamp',
        timestamp)
    results = query.fetch()
    for timed_deploy in results:
        _set_branch_manifest(timed_deploy.branch, timed_deploy.manifest.id())
        timed_deploy.deployed = datetime.datetime.now()
        timed_deploy.put()
        deployments.append({
            'branch': timed_deploy.branch,
            'manifest_id': timed_deploy.manifest.id(),
        })
    return deployments
