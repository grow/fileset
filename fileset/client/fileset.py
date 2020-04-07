#!/usr/bin/env python

import json
import mimetypes
import os
import requests


class Error(Exception):
    pass


class FilesetClient(object):

    def __init__(self, host, token):
        self.host = self._clean_host(host)
        self.token = token

    def _clean_host(self, host):
        if not host.startswith('http'):
            if host.startswith('localhost:8088'):
                host = 'http://' + host
            else:
                host = 'https://' + host
        return host

    def upload_manifest(self, manifest):
        payload = json.dumps(manifest)
        url = '{host}/_fs/api/manifest.upload'.format(host=self.host)
        response = requests.post(url, data=payload, headers={
            'Content-Type': 'application/json',
            'X-Fileset-Token': self.token,
        })
        if response.status_code != 200:
            raise Error('manifest.upload failed: {}\n{}'.format(
                response.status_code, response.text))
        return response

    def blob_exists(self, sha):
        data = {
            'sha': sha,
        }
        payload = json.dumps(data)
        url = '{host}/_fs/api/blob.exists'.format(host=self.host)
        response = requests.post(url, data=payload, headers={
            'Content-Type': 'application/json',
            'X-Fileset-Token': self.token,
        })
        if response.status_code != 200:
            text = response.text
            if isinstance(text, unicode):
                text = text.encode('utf-8')
            raise Error('blob.exists failed: {}\n{}'.format(
                response.status_code, text))
        return response.json()['exists']

    def upload_blob(self, sha, filepath, content):
        url = '{host}/_fs/api/blob.upload?sha={sha}'.format(
            host=self.host, sha=sha)
        filename = os.path.basename(filepath)
        mimetype = mimetypes.guess_type(filename)
        files = [
            ('blob', (filename, content, mimetype)),
        ]
        response = requests.post(url, files=files, headers={
            'X-Fileset-Token': self.token,
        })
        if response.status_code != 200:
            text = response.text
            if isinstance(text, unicode):
                text = text.encode('utf-8')
            raise Error('blob.upload failed: {}\n{}'.format(
                response.status_code, text))
        return response

    def get_branch_manifest(self, branch):
        data = {
            'branch': branch,
        }
        payload = json.dumps(data)
        url = '{host}/_fs/api/branch.get_manifest'.format(host=self.host)
        response = requests.post(url, data=payload, headers={
            'Content-Type': 'application/json',
            'X-Fileset-Token': self.token,
        })
        if response.status_code != 200:
            raise Error('branch.get_manifest failed: {}\n{}'.format(
                response.status_code, response.text))
        return response

    def set_branch_manifest(self, branch, manifest_id, deploy_timestamp=None):
        data = {
            'branch': branch,
            'manifest_id': manifest_id,
        }
        if deploy_timestamp:
            data['deploy_timestamp'] = deploy_timestamp
        payload = json.dumps(data)
        url = '{host}/_fs/api/branch.set_manifest'.format(host=self.host)
        response = requests.post(url, data=payload, headers={
            'Content-Type': 'application/json',
            'X-Fileset-Token': self.token,
        })
        if response.status_code != 200:
            raise Error('branch.set_manifest failed: {}\n{}'.format(
                response.status_code, response.text))
        return response
