#!/usr/bin/env python

import hashlib
import os
import cloudstorage as gcs
from google.appengine.api import app_identity
from google.appengine.api import memcache


class Error(Exception):
    pass


def get_gcs_path(sha):
    bucket = app_identity.get_default_gcs_bucket_name()
    return os.path.join('/', bucket, 'blobs', sha)


def exists(sha):
    memcache_key = 'fs-blob-exists:{}'.format(sha)
    if memcache.get(memcache_key) == '1':
        return True

    gcs_path = get_gcs_path(sha)
    try:
        gcs.stat(gcs_path)
        exists = True
    except gcs.NotFoundError:
        exists = False
    return exists


def write(sha, content, content_type):
    file_sha = hashlib.sha1(content).hexdigest()
    if sha != file_sha:
        raise Error('sha does not match: "{}" != "{}"'.format(sha, file_sha))

    gcs_path = get_gcs_path(sha)
    with gcs.open(gcs_path, 'w', content_type=content_type) as fp:
        fp.write(content)

    memcache_key = 'fs-blob-exists:{}'.format(sha)
    memcache.set(memcache_key, '1')


def read(sha):
    gcs_path = get_gcs_path(sha)
    gcs_file = gcs.open(gcs_path)
    content = gcs_file.read()
    gcs_file.close()
    return content
