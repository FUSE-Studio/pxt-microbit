AWS_PROFILE ?= terraform-dev

.PHONY: fuse

fuse:
	command -v pxt > /dev/null 2>&1 || npm install -g pxt
	# @types/ws 8.5+ uses generics incompatible with pxt-core's bundled TypeScript 4.2.3
	# --route bakes /microbit/ into all absolute asset paths at build time (no <base> tag needed)
	yarn install && pxt staticpkg --route /microbit/
	# Resolve S3 bucket from SSM and sync
	@BUCKET=$$(aws ssm get-parameter \
		--name /laravel/satellite-apps-bucket \
		--query Parameter.Value \
		--output text \
		--profile $(AWS_PROFILE)); \
	echo "Syncing to s3://$$BUCKET/microbit/ (profile: $(AWS_PROFILE))..."; \
	aws s3 sync built/packaged/ s3://$$BUCKET/microbit/ --delete --profile $(AWS_PROFILE)
