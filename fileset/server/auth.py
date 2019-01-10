#!/usr/bin/env python

import datetime
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
    ent = FilesetAuthToken.get_by_id(token)
    if ent:
        # Assume that if the token whenever the token is checked for validity,
        # it is being used for some operation.
        ent.last_used = datetime.datetime.now()
        ent.put_async()
    return bool(ent)


def delete_token(token):
    key = ndb.Key(FilesetAuthToken, token)
    key.delete()


def _generate_token():
    return secrets.token_hex(32)
