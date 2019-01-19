# Fileset Server for App Engine

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
- (?!extensions\/fileset|appengine_config\.py)
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

# Whether to enforce https for all Env.PROD requests.
fileset_REQUIRE_HTTPS = True
```

See `fileset/config.py` for full list of config options.

5) Update `podspec.yaml`

```yaml
extensions:
  preprocessors:
  - extensions.fileset.grow.ext.FilesetPreprocessor

preprocessors:
- kind: fileset

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

7) Generate an auth token

Future:

* Visit https://APPID.appspot.com/_fs/admin
* Generate an auth token, and save the key to `.fileset.json`

The `/_fs/admin` URL isn't implemented yet, so for now you'll need to launch
the interactive console:

Add to `app.yaml`:

```yaml
handlers:
- url: /_ah/admin/interactive.*
  script: google.appengine.ext.admin.application
  login: admin
```

Go to https://APPID.appspot.com/_ah/admin/interactive and run the following:

```python
import appengine_config
from fileset.server import auth
print auth.create_auth_token('DESCRIPTION')
```

8) Add to `.gitignore`

```
.fileset.json
objectcache.fileset.local.json
```


## Local development

Start an App Engine dev server.

```
dev_appserver.py --port=8088
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
