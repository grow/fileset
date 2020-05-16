# Fileset Server for App Engine

Fileset is a high-performance static file server for App Engine meant for high-traffic sites. Features include: preview branches backed by Google authentication, international fallbacks, atomic deployments, and timed deployments.

## Setup

1) Add fileset to `extensions.txt`

```
git+git://github.com/grow/fileset@HASH
```

Replace `HASH` with a git commit hash. Always pin to a specific hash to avoid
any breaking changes from future commits.

2) Run `grow install`

3) Add `app.yaml`

```yaml
runtime: python27
api_version: 1
threadsafe: true

includes:
- extensions/fileset/

handlers:
- url: /_ah/admin/interactive.*
  script: google.appengine.ext.admin.application
  login: admin

- url: /.*
  script: extensions.fileset.server.main.app

skip_files:
- ^(.*/)?#.*#
- ^(.*/)?.*/RCS/.*
- ^(.*/)?.*\.py[co]
- ^(.*/)?.*\.so$
- ^(.*/)?.*\_test.(html|js|py)$
- ^(.*/)?.*~
- ^(.*/)?\..*
- ^(.*/)?app\.yaml
- ^(.*/)?app\.yml
- ^(.*/)?index\.yaml
- ^(.*/)?index\.yml
- ^(.*/)?run_tests.py
- ^extensions/(?!(__init__.py|babel|cloudstorage|fileset)).*
- (?!(extensions|appengine_config\.py)).*
```

4) Add `appengine_config.py`

```python
import os
import sys
from google.appengine.ext import vendor

thirdparty_path = os.path.join(os.path.dirname(__file__), 'extensions')
vendor.add(thirdparty_path)

# List of emails that are authorized to access Env.STAGING.
fileset_AUTHORIZED_USERS = (
    'example@gmail.com',
)
fileset_AUTHORIZED_ORGS = (
    'example.com',
)

# Whether to enforce https for all Env.PROD requests.
fileset_REQUIRE_HTTPS = True
```

See `fileset/config.py` for full list of config options.

5) Update `podspec.yaml`

```yaml
ext:
- extensions.fileset.grow.ext.FilesetExtension

deployments:
  localhost:
    destination: fileset
    server: localhost:8088
    env:
      name: local
  staging:
    destination: fileset
    branch: auto  # Uses the git branch name.
    server: APPID.appspot.com
    env:
      name: staging
  prod:
    destination: fileset
    branch: master
    server: APPID.appspot.com
    env:
      name: prod
```

6) Deploy the server to App Engine.

```
gcloud app deploy --project=APPID --promote app.yaml
```

Optional: if you plan to use the timed deployments feature, you'll also need to
deploy a cron.yaml and index.yaml. A sample config files can be found in
`extensions/fileset/cron.yaml` and `extensions/fileset/index.yaml`

```
gcloud app deploy --project=APPID cron.yaml index.yaml
```

7) Generate an auth token

* Visit https://APPID.appspot.com/_fs/token
* Save the generated token to `.fileset.json` in your project folder

If `/_fs/token` is unimplemented, generate `.fileset.json` using:

```
import appengine_config
from fileset.server import auth

token = auth.create_auth_token('DESCRIPTION')
print '{"token": "%s"}' % token
```

8) Add to `.gitignore`

```
.fileset.json
objectcache.fileset.local.json
```


## Local development

Start an App Engine dev server.

```
dev_appserver.py --port=8088 .
```

Deploy files to the local server.

```
grow deploy -f localhost
```


## Deployment

Stage the changes to a branch.

```
grow deploy -f staging
```

Deploy the changes to prod.

```
grow deploy -f prod
```
