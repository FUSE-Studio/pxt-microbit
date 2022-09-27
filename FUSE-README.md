# Build and deploy steps for microbit.fusestudio.net

$ pxt staticpkg
$ cp -r built/packaged/docs/static built/packaged
$ aws s3 sync built/packaged s3://microbit.fusestudio.net
$ aws cloudfront create-invalidation --distribution-id {} --paths "/*"