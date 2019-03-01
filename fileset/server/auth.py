#!/usr/bin/env python

import datetime
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import ndb
from fileset.thirdparty import secrets


class Error(Exception):
    pass


class FilesetAuthToken(ndb.Model):
    description = ndb.StringProperty()
    created_by = ndb.StringProperty()
    created = ndb.DateTimeProperty(auto_now_add=True)
    last_used = ndb.DateTimeProperty()


def create_auth_token(description):
    if not users.is_current_user_admin():
        raise Error('only admins can create auth tokens')

    user = users.get_current_user()
    token = _generate_token()

    ent = FilesetAuthToken(id=token)
    ent.description = description
    ent.created_by = user.email()
    ent.put()

    return token


def is_token_valid(token):
    memcache_key = 'fs-token-valid:{}'.format(token)
    if memcache.get(memcache_key) == '1':
        return True

    ent = FilesetAuthToken.get_by_id(token)
    is_valid = bool(ent)

    # TODO(stevenle): prevent datastore write contention.
    # if is_valid:
    #     # Assume that whenever the token is checked for validity, it is being
    #     # used for some operation.
    #     ent.last_used = datetime.datetime.now()
    #     ent.put_async()

    if is_valid:
        memcache.set(memcache_key, '1')
    return is_valid


def delete_token(token):
    memcache_key = 'fs-token-valid:{}'.format(token)
    memcache.delete(memcache_key)

    key = ndb.Key(FilesetAuthToken, token)
    key.delete()


def _generate_token():
    return secrets.token_hex(32)
