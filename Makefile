# Build the micro:bit editor and publish it to the FUSE satellite CDN.
#
# Publishing IS the deploy. The assets land on [dev.]satellite.fusestudio.net
# and the Laravel app re-reads microbit/index.html from the bucket within its
# ~5 min cache, so a release goes live at my.fusestudio.net/microbit without a
# Laravel deploy. Laravel no longer syncs this build into its own public/ —
# see docs/adding-satellite-apps.md in the Laravel repo.

AWS_PROFILE            ?= terraform-dev
PROD_AWS_PROFILE       ?= terraform-prod
SATELLITE_BUCKET_PARAM ?= /laravel/satellite-apps-bucket

# S3 key prefix; matches the public route (/microbit), per the publisher
# conventions in fuse-laravel modules/satellite-cdn/README.md.
APP ?= microbit

DEV_CDN  ?= https://dev.satellite.fusestudio.net
PROD_CDN ?= https://satellite.fusestudio.net

# pxt's output is almost entirely unhashed — main.js, pxtapp.js and the rest
# keep the same filenames every build — so the version DIRECTORY is what makes
# a long cache lifetime safe, and what gives instant rollback by re-publishing
# an older index.html. A commit SHA alone is not enough: publishing twice from
# a dirty tree would reuse the path while browsers hold a year-long copy of the
# first build, so uncommitted builds get a timestamp too.
GIT_SHA   := $(shell git rev-parse --short HEAD)
GIT_DIRTY := $(shell git diff --quiet || echo -dirty-$(shell date -u +%Y%m%dT%H%M%SZ))
VERSION   ?= $(GIT_SHA)$(GIT_DIRTY)

# pxt can only bake a root-relative route into the build, so it is built
# against this placeholder and rewritten to an absolute CDN URL afterwards.
# See fuse-cdn-rewrite.py for why, and for the two other path families it fixes.
PLACEHOLDER = /__fuse-satellite__/

# pxt mirrors the route as a directory path under built/packaged, so the whole
# placeholder ends up in the output path — not just the app name.
BUILD_DIR = built/packaged$(PLACEHOLDER)$(APP)/$(VERSION)

.PHONY: help
help:
	@echo "make build          build the editor into $(BUILD_DIR)"
	@echo "make publish-dev    publish to $(DEV_CDN)/$(APP)/$(VERSION)"
	@echo "make publish-prod   publish to $(PROD_CDN)/$(APP)/$(VERSION)"

.PHONY: build
build:
	command -v pxt > /dev/null 2>&1 || npm install -g pxt
	# @types/ws 8.5+ uses generics incompatible with pxt-core's bundled TypeScript 4.2.3
	yarn install
	pxt staticpkg --route $(PLACEHOLDER)$(APP)/$(VERSION)/

# VERSION is passed down explicitly: GIT_DIRTY stamps the current time, so a
# sub-make left to compute VERSION itself would pick a different one, and the
# build would bake in a path that nothing was ever uploaded to.
.PHONY: publish-dev
publish-dev:
	$(MAKE) publish CDN=$(DEV_CDN) AWS_PROFILE=$(AWS_PROFILE) VERSION=$(VERSION)

.PHONY: publish-prod
publish-prod:
	$(MAKE) publish CDN=$(PROD_CDN) AWS_PROFILE=$(PROD_AWS_PROFILE) VERSION=$(VERSION)

# Assets go to a versioned, immutable prefix; index.html sits at the app root
# where Laravel reads it, and must never be cached — it is the pointer to the
# current version. Deliberately no --delete: a briefly-stale index.html has to
# keep finding the assets it references. No CloudFront invalidation either —
# every asset path is version-scoped, and index.html is blocked at the edge and
# read from S3 by Laravel.
.PHONY: publish
publish:
	@test -n "$(CDN)" || { echo "error: use publish-dev or publish-prod"; exit 1; }
	$(MAKE) build VERSION=$(VERSION)
	python3 fuse-cdn-rewrite.py $(BUILD_DIR) $(PLACEHOLDER) $(CDN) $(CDN)/$(APP)/$(VERSION)
	@BUCKET=$$(aws ssm get-parameter \
		--name $(SATELLITE_BUCKET_PARAM) \
		--query Parameter.Value \
		--output text \
		--profile $(AWS_PROFILE)); \
	echo "Publishing $(APP)/$(VERSION) to s3://$$BUCKET (profile: $(AWS_PROFILE))"; \
	aws s3 sync $(BUILD_DIR) s3://$$BUCKET/$(APP)/$(VERSION)/ \
		--exclude index.html \
		--cache-control "public, max-age=31536000, immutable" \
		--profile $(AWS_PROFILE); \
	aws s3 cp $(BUILD_DIR)/index.html s3://$$BUCKET/$(APP)/index.html \
		--cache-control "no-cache" \
		--content-type "text/html; charset=utf-8" \
		--profile $(AWS_PROFILE); \
	echo; \
	echo "Published. Laravel reads s3://$$BUCKET/$(APP)/index.html at request time,"; \
	echo "so no Laravel deploy is needed."
