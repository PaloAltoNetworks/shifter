# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

PRs do **not** edit this file directly. [release-please](https://github.com/googleapis/release-please)
maintains it from the Conventional Commit history on `main`; release sections
are generated at release time via its release PR, not hand-edited in PRs. See
[`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md) for the release
model. The history below is preserved as-is across the towncrier to
release-please transition (#1776).

## [4.1.1](https://github.com/Brad-Edwards/shifter/compare/v4.1.0...v4.1.1) (2026-10-14)


### Bug Fixes

* **bootstrap:** use concise digit class in GCP region rule ([79be371](https://github.com/Brad-Edwards/shifter/commit/79be371f76ef83756543f09f62796227bf766855))
* resolve SonarCloud findings from the v4.1.0 back-merge ([8ddcd88](https://github.com/Brad-Edwards/shifter/commit/8ddcd88edb073ac91fd1874a6b87fa72d22f872f))
* resolve SonarCloud findings from the v4.1.0 back-merge ([4fdd9d7](https://github.com/Brad-Edwards/shifter/commit/4fdd9d7c3fbd041901e25f42af49a97261d2afd8))

## [4.1.0](https://github.com/Brad-Edwards/shifter/compare/v4.0.0...v4.1.0) (2026-10-13)


### Features

* acquire scenario-declared feature artifacts and stream them to guests ([835f8eb](https://github.com/Brad-Edwards/shifter/commit/835f8eb50e49793fb0c183e33e99a6279bed7dd9))
* **acquisition:** make the acquisition Job provider-neutral ([f1a9b0d](https://github.com/Brad-Edwards/shifter/commit/f1a9b0d28ba8500ea4ddb91328348e98bb7b8cec)), closes [#2479](https://github.com/Brad-Edwards/shifter/issues/2479)
* **chart,eks:** isolated namespace, admission and identity for acquisition Jobs ([a65dd2f](https://github.com/Brad-Edwards/shifter/commit/a65dd2ffef8bc0b64c641c9f1bf190b422deeef7)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **cms:** acquire declared feature artifacts before any range needs them ([141b5eb](https://github.com/Brad-Edwards/shifter/commit/141b5ebd799351f3d1a0298b23e57b4c22b48fab)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **cms:** acquired feature-artifact inventory, npm recipe and single-flight service ([91f1cf1](https://github.com/Brad-Edwards/shifter/commit/91f1cf1ca65c9b15784b824072ed3dca6b1ba0cc)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **cms:** resolve unprojected feature sources to acquired artifacts at launch ([176299f](https://github.com/Brad-Edwards/shifter/commit/176299f1ce8e783f5bc988558b05d6200556d3fb)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **cms:** stream pack content promotion with no payload size cap ([21687aa](https://github.com/Brad-Edwards/shifter/commit/21687aa3552b3c6e11e312cfffdad32ee14efac3)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **ctf:** store static flags as plaintext and accept FLAG{v}, {v}, or v ([9ce5d45](https://github.com/Brad-Edwards/shifter/commit/9ce5d45d39076f18c78a72bf3b976e20559360c9))
* **ctf:** store static flags as plaintext and accept FLAG{v}, {v}, or v ([621d377](https://github.com/Brad-Edwards/shifter/commit/621d37785cba9c230de5e3631fd0091334577851))
* **ec2:** preconfigured-host and prepromoted-DC image contracts on native EC2 ([aead9d2](https://github.com/Brad-Edwards/shifter/commit/aead9d2518cd5417f0713ab17d3de3b02ecb7bea))
* **ec2:** preconfigured-host and prepromoted-DC image contracts on native EC2 ([9270006](https://github.com/Brad-Edwards/shifter/commit/92700064816d989830439de0377c028b41921b5d)), closes [#2527](https://github.com/Brad-Edwards/shifter/issues/2527) [#2528](https://github.com/Brad-Edwards/shifter/issues/2528)
* **eks:** enable feature-artifact acquisition from the acquirer identity ([5d3a008](https://github.com/Brad-Edwards/shifter/commit/5d3a0085a0a62db36969b1cefe184c9ae47cbebc)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **eks:** run the runtime-plugin sandbox pool on EKS ([2c2ab84](https://github.com/Brad-Edwards/shifter/commit/2c2ab84c21202fbc12abe38364487b5520660ccf))
* **eks:** trusted node labeler so the runtime-plugin pool can run on EKS ([0cace34](https://github.com/Brad-Edwards/shifter/commit/0cace341d049aaff5f50ce9df600f7955cb23e6c)), closes [#2526](https://github.com/Brad-Edwards/shifter/issues/2526)
* **eks:** working AWS EKS deploy and range-provisioning path ([dfaa453](https://github.com/Brad-Edwards/shifter/commit/dfaa45316cefdef97aec0c62da64ece4120081c5))
* **engine:** launcher-driven acquisition Jobs for feature artifacts ([c08e56e](https://github.com/Brad-Edwards/shifter/commit/c08e56ea0b6435b9e41db9551a4bb64b94d4b8ac)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **gcp:** acquire scenario-declared feature artifacts on GKE ([8aec520](https://github.com/Brad-Edwards/shifter/commit/8aec52081642d37b57729c4295cecce24ba66292))
* **gcp:** add capacity tiers above 100 participants and apply them on CI deploys ([ecd51c2](https://github.com/Brad-Edwards/shifter/commit/ecd51c24d3d8d960b45c851f29f6c03e8001d591))
* **gcp:** add p200, p300, and p500 shared-service capacity tiers ([bf6cf38](https://github.com/Brad-Edwards/shifter/commit/bf6cf3839b0739081ce1337c7dbc71d7d638dec2)), closes [#2502](https://github.com/Brad-Edwards/shifter/issues/2502)
* **gcp:** default-enable range flow, NAT, and Vertex Data Access logs ([4f22727](https://github.com/Brad-Edwards/shifter/commit/4f22727314b3792cfb77e8d2c5dcb51514004f49))
* **gcp:** default-enable range flow, NAT, and Vertex Data Access logs ([9e300d9](https://github.com/Brad-Edwards/shifter/commit/9e300d97a58409b5fdbfc759ea166ad42a2cf9ab))
* **gcp:** enable feature-artifact acquisition on GKE ([17e727d](https://github.com/Brad-Edwards/shifter/commit/17e727d74389e0fb7ccc48f8773d801557f970ed)), closes [#2479](https://github.com/Brad-Edwards/shifter/issues/2479)
* **identity:** complete prepared account administration ([fab2088](https://github.com/Brad-Edwards/shifter/commit/fab20884af4bf817f1f74e01983461203d2ed4b0))
* **identity:** complete prepared account administration ([3c7700f](https://github.com/Brad-Edwards/shifter/commit/3c7700ff416547e3a40d11f00d7a485795b4073c))
* **infra:** deploy the shared OpenVPN pool on GCP ([6f8309a](https://github.com/Brad-Edwards/shifter/commit/6f8309acf4d0f867b42a27dd6518f5d3904f6242)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **packer:** build the AWS Kali image from the official Debian 12 AMI ([2870de1](https://github.com/Brad-Edwards/shifter/commit/2870de18d4816b29425dc2e7ea0e0db4d8363015))
* **packer:** build the AWS Kali image from the official Debian 12 AMI ([14614b6](https://github.com/Brad-Edwards/shifter/commit/14614b6349abd15356fbc8f7f8bfb21a5bc0ac04)), closes [#2459](https://github.com/Brad-Edwards/shifter/issues/2459)
* **packer:** optional AD content seed for the AWS pre-promoted DC bake ([03a799d](https://github.com/Brad-Edwards/shifter/commit/03a799d538c38bacf5931f43e37fdfc35e20f505))
* **packer:** optional AD content seed for the AWS pre-promoted DC bake ([d27d05d](https://github.com/Brad-Edwards/shifter/commit/d27d05d83408c70bff8510ca4382243e7c2d3c3a))
* **packer:** stop baking the Claude Code binary into AWS images ([f80a277](https://github.com/Brad-Edwards/shifter/commit/f80a2772b162b8578ee47542da8a9945100bc455))
* **packer:** stop baking the Claude Code binary into AWS images ([d70e488](https://github.com/Brad-Edwards/shifter/commit/d70e488265a54a147ec93dd1b7666cddc9c538a7)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **packer:** stop baking the Claude Code binary into GCE images ([ab17dc3](https://github.com/Brad-Edwards/shifter/commit/ab17dc3d702046f9dc02d6d82beb5dc00fc04193)), closes [#2479](https://github.com/Brad-Edwards/shifter/issues/2479)
* **provisioner:** stream delivered payloads to guests with no size cap ([3da797a](https://github.com/Brad-Edwards/shifter/commit/3da797ae7ee0e8a2809fed6c4e1dc0619164adb6)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **range:** add the shared OpenVPN pool server ([8c95832](https://github.com/Brad-Edwards/shifter/commit/8c9583211ecc43a61eb2ec79e009bffe390d5cf5)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **range:** authorize OpenVPN pool sessions and retire per-range gateways ([0926888](https://github.com/Brad-Edwards/shifter/commit/092688853fc14e36d97cb2d647c9cf6f407e88a5)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **range:** participant OpenVPN access to the Kali target on the RAES GCE path ([418e3fc](https://github.com/Brad-Edwards/shifter/commit/418e3fc651cd8a325589551ba93f210b36265c38))
* **range:** participant OpenVPN access to the Kali target on the RAES GCE path ([af30704](https://github.com/Brad-Edwards/shifter/commit/af30704312965b5741639cbf0d1004341c913230)), closes [#2030](https://github.com/Brad-Edwards/shifter/issues/2030)
* **range:** shared participant OpenVPN server pool on GCP ([f8d55f8](https://github.com/Brad-Edwards/shifter/commit/f8d55f8ed47d3df1a5d6c3be90ede646ebea4821))
* **shared:** isolated feature-artifact acquisition Job body ([0be8fd7](https://github.com/Brad-Edwards/shifter/commit/0be8fd7a536ae760492c2b1ac572a1aaec523235)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **shared:** pinnable task container command; acquisition Job exit protocol ([04f3d92](https://github.com/Brad-Edwards/shifter/commit/04f3d92667891b225e015a3f90703b04e9b91615)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **smoke:** declare Claude Code on the smoke-linux attacker ([90bbf85](https://github.com/Brad-Edwards/shifter/commit/90bbf855e13eee062dadb2d84b088c596553d79d)), closes [#2479](https://github.com/Brad-Edwards/shifter/issues/2479)
* **smoke:** declare Claude Code on the smoke-linux-aws attacker ([48f0d3a](https://github.com/Brad-Edwards/shifter/commit/48f0d3a175a66971874bb42e780ee196fb5d6f93)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **uat:** run the strict event gate at any catalog tier ([dadbe3e](https://github.com/Brad-Edwards/shifter/commit/dadbe3e059dffea96e8cc4fa96de148660b8ddf5)), closes [#2502](https://github.com/Brad-Edwards/shifter/issues/2502)
* user-chosen CTF participant username as single login + display identity ([4856d9c](https://github.com/Brad-Edwards/shifter/commit/4856d9c6a98597ce388e1214255b797b58f61043))
* user-chosen CTF participant username as single login + display identity ([77e409b](https://github.com/Brad-Edwards/shifter/commit/77e409b721e5be330344f3e2fc0977ca53128cc8))


### Bug Fixes

* actionable error when a pack's org differs from the launch workspace ([93652fc](https://github.com/Brad-Edwards/shifter/commit/93652fc70fadf31bf26d01b5ca8f899bca3969de))
* actionable error when a pack's org differs from the launch workspace ([f8436d7](https://github.com/Brad-Edwards/shifter/commit/f8436d7d0fead7c244f618ab8ea622bd605d2b99))
* **bootstrap:** allow provisioner Job egress to range guests on EKS ([aca53fe](https://github.com/Brad-Edwards/shifter/commit/aca53fe7dbd59943fb70c694df4dabd9ca1aded1))
* **chart:** admit raes-range activate in the provisioner Job admission policy ([1a74dfd](https://github.com/Brad-Edwards/shifter/commit/1a74dfda884cbfe0c5bdea8c38e32fc8e475c794))
* **chart:** admit raes-range activate in the provisioner Job admission policy ([47e7fdf](https://github.com/Brad-Edwards/shifter/commit/47e7fdfd5d6311a1eefa1af4ab0ae0e4bd66b242)), closes [#2467](https://github.com/Brad-Edwards/shifter/issues/2467)
* **ci:** pass the exported GCE disk object, not its secret-bearing URI ([f393fc4](https://github.com/Brad-Edwards/shifter/commit/f393fc468fb83612593357a4de5be6782f4af877))
* **ci:** pass the exported GCE disk object, not its secret-bearing URI ([d2351cb](https://github.com/Brad-Edwards/shifter/commit/d2351cb47314e7aaa46b82711d2af116f5d7bf9f))
* **ci:** push the exported GCE disk to GHCR by relative path ([6f700e3](https://github.com/Brad-Edwards/shifter/commit/6f700e334b6d340170ee945ae92379bc87c06cc0))
* **ci:** push the exported GCE disk to GHCR by relative path ([d162e80](https://github.com/Brad-Edwards/shifter/commit/d162e8069add8cd7ac720b4cb2022b4bc711d375))
* **ci:** run packer cleanup only after AWS credentials succeeded ([360365d](https://github.com/Brad-Edwards/shifter/commit/360365dc6ee8ff3a2aaf1a9e1c9c17021fea6d56))
* **ci:** run packer cleanup only after AWS credentials succeeded ([c33de65](https://github.com/Brad-Edwards/shifter/commit/c33de6526b80c51ea7438f5f10b30191e662bf24))
* **ctf:** carry difficulty in CTFd challenge exports ([9cd9c76](https://github.com/Brad-Edwards/shifter/commit/9cd9c76bf0ca7f359aa9b6618b3ae2a5f6648df0))
* **ctf:** import challenge difficulty from CTFd packs ([f5a4ba2](https://github.com/Brad-Edwards/shifter/commit/f5a4ba28e4315fe830523c45223c8896ec7c7774))
* **ctf:** import challenge difficulty from CTFd packs ([d58e435](https://github.com/Brad-Edwards/shifter/commit/d58e4358ec3f04fb1e74454e00adfd3bb3b8c3da))
* **ctf:** launch participant ranges outside the assignment transaction ([ec10c31](https://github.com/Brad-Edwards/shifter/commit/ec10c314b4998142269fc2efb3be341162c070c8))
* **ctf:** launch participant ranges outside the assignment transaction ([ba00812](https://github.com/Brad-Edwards/shifter/commit/ba00812b4a7e3a98eef161572d45142309a942b8))
* **ctf:** narrow the claimed participant user and keep the boundary-mock baseline ([b5310c5](https://github.com/Brad-Edwards/shifter/commit/b5310c5515261eef405f09fdcb199da979a264b1))
* **ctf:** rebuild a failed participant range under its own model-access identity ([ccdf54a](https://github.com/Brad-Edwards/shifter/commit/ccdf54a3421ed43a1b5937bdd832f021ecb5c01c))
* **ctf:** rebuild a failed participant range under its own model-access identity ([c6c9cfe](https://github.com/Brad-Edwards/shifter/commit/c6c9cfed266bce247c0594ed60f769bbfb927b18)), closes [#2462](https://github.com/Brad-Edwards/shifter/issues/2462)
* **ctf:** redirect unslashed login/change-password and add password reveal toggle ([ab9b6fc](https://github.com/Brad-Edwards/shifter/commit/ab9b6fcaf730430359b76ff0f20e60c2d4363b07))
* **ctf:** redirect unslashed login/change-password and add password reveal toggle ([a3f7a99](https://github.com/Brad-Edwards/shifter/commit/a3f7a99c20d83f36a86ac2579e34f90bf1ce1107))
* **ctf:** release temporary accounts when force-deleting an event ([c5a8006](https://github.com/Brad-Edwards/shifter/commit/c5a8006eb9ab0c5271e3997e2f5d39646afb53ea))
* **ctf:** release temporary accounts when force-deleting an event ([9591a66](https://github.com/Brad-Edwards/shifter/commit/9591a66575d6719ded3b7fb52325606ffeb00222))
* **deploy:** release a disabled broker's load balancer before Terraform ([ea86dd3](https://github.com/Brad-Edwards/shifter/commit/ea86dd30253a161fce2f1a26076ae00d18a122f2))
* **deps:** bump postcss-selector-parser to 7.1.6 (GHSA-rj75-hqrm-r3gf) ([a17fa72](https://github.com/Brad-Edwards/shifter/commit/a17fa72d43a0ebd8f0b5d591de02376f0af1f1d1)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **deps:** bump proxy-addr to 2.0.8 and source-map-js to 1.2.2 ([a40322f](https://github.com/Brad-Edwards/shifter/commit/a40322f8cfea207494248ed42c491142314495cf)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **deps:** carry multidict 6.9.1 into the portal's GCP lock ([42722f9](https://github.com/Brad-Edwards/shifter/commit/42722f9e553fc5f716c9884c90d1c1eb8627c141))
* **deps:** clear katex, sprintf-js and multidict advisories ([fc32b02](https://github.com/Brad-Edwards/shifter/commit/fc32b0208bf3df3deb4adddd7022dff20b11c055))
* **ec2:** accept a prepromoted DC whose node authors no domain, as GCE does ([fa308c6](https://github.com/Brad-Edwards/shifter/commit/fa308c6a301beadb016579bdcac007f8a8e4e9c8)), closes [#2528](https://github.com/Brad-Edwards/shifter/issues/2528)
* **eks:** bring proof/prod EKS roots to parity with dev ([63d9fde](https://github.com/Brad-Edwards/shifter/commit/63d9fdeb166346d0dfbbe727c2073dbe33dfe765))
* **eks:** build platform queue and topic ARNs instead of looking them up ([c4eb8ff](https://github.com/Brad-Edwards/shifter/commit/c4eb8ff3019c8aafbfa44283972424574b561d09))
* **eks:** build platform queue and topic ARNs instead of looking them up ([ca1d901](https://github.com/Brad-Edwards/shifter/commit/ca1d90142f951a08a7cd817d0dfa31aacba9f586)), closes [#2466](https://github.com/Brad-Edwards/shifter/issues/2466)
* **eks:** forward the storage bucket to the provisioner Job ([f8159df](https://github.com/Brad-Edwards/shifter/commit/f8159df5c12fe49fa4c1274238191d02dd6e7038))
* **eks:** forward the storage bucket to the provisioner Job ([666abd0](https://github.com/Brad-Edwards/shifter/commit/666abd01e90f7a0ab149df2473cda5c9644af3d8))
* **eks:** grant portal Decrypt on the key range credentials actually use ([cb24718](https://github.com/Brad-Edwards/shifter/commit/cb247187b99859106fdc510ee74d4a217965c8ce))
* **eks:** health-check ALB targets on each service's readiness path ([c7c88c4](https://github.com/Brad-Edwards/shifter/commit/c7c88c41cfe9c3f19b1b3c060d6936f1d5669a8f))
* **eks:** health-check ALB targets on each service's readiness path ([fa36c8c](https://github.com/Brad-Edwards/shifter/commit/fa36c8cc6e1b32f9b1897f3f9a5f52833ac9d786))
* **eks:** identify runtime-plugin nodes by their Auto Scaling group ([1bb6d62](https://github.com/Brad-Edwards/shifter/commit/1bb6d62c708f41b7190bd0e0e03090b7fde14b4b))
* **eks:** land the remaining [#2445](https://github.com/Brad-Edwards/shifter/issues/2445) fixes (credential KMS key, AWS read-after-write) ([f0dd804](https://github.com/Brad-Edwards/shifter/commit/f0dd80420e9dc6d3f562a5d77c8f7815252ad06a))
* **eks:** let the ALB controller admit its backend group to pod targets ([0ee306e](https://github.com/Brad-Edwards/shifter/commit/0ee306ee4e490c338750aec3cdc3f45c13b48922))
* **eks:** let the ALB controller admit its backend group to pod targets ([84dfc9e](https://github.com/Brad-Edwards/shifter/commit/84dfc9ef54fad6ef3baa88262580eb43bf2be288))
* **eks:** let the portal read range participant credentials ([8e85452](https://github.com/Brad-Edwards/shifter/commit/8e85452cf718af00b1836344b419a8c96ad370e8))
* **eks:** let the provisioner decrypt the storage bucket's objects ([abe9267](https://github.com/Brad-Edwards/shifter/commit/abe9267f4c499f67dc42c8ef4d8439554fa22977))
* **eks:** let the provisioner decrypt the storage bucket's objects ([2f33e7f](https://github.com/Brad-Edwards/shifter/commit/2f33e7fd822557b3a09fda4339c8d76dd90b84e1)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **eks:** portal range-credential access and proof/prod EKS parity ([b8e0546](https://github.com/Brad-Edwards/shifter/commit/b8e0546b67bc3069cdf5afda7e722897430b09c7))
* **eks:** restore platform SQS, SNS, storage and metrics access on EKS workload roles ([3a8d867](https://github.com/Brad-Edwards/shifter/commit/3a8d867ec0c7b97e2411da08ac41fa5bd59c7f69))
* **eks:** restore platform SQS, SNS, storage and metrics access on EKS workload roles ([0a6c5d7](https://github.com/Brad-Edwards/shifter/commit/0a6c5d700a34aa360875cb4dfea0b64abbcd8ea8)), closes [#2466](https://github.com/Brad-Edwards/shifter/issues/2466)
* **eks:** size the node-pool labeler for its measured footprint ([a072807](https://github.com/Brad-Edwards/shifter/commit/a072807d6db42f1506669fcfc6f5aac2cb4253e2)), closes [#2526](https://github.com/Brad-Edwards/shifter/issues/2526)
* **eks:** stream guacamole + migration manifests to kubectl over stdin ([1e555ff](https://github.com/Brad-Edwards/shifter/commit/1e555ff92e413a0d3703443a15f137454ccc7d24))
* **eks:** tag the cluster security group for the ALB controller instead ([202965e](https://github.com/Brad-Edwards/shifter/commit/202965e8361279681bfe0954e638c5af60986599))
* **eks:** unblock range smoke — provisioner egress to guests and ENI teardown ([1989cca](https://github.com/Brad-Edwards/shifter/commit/1989cca0aee7db2356830fdec6073ff9b1f587ba))
* **engine:** give acquisition Jobs a private scratch path and tighten feature-artifact types ([a1525ef](https://github.com/Brad-Edwards/shifter/commit/a1525ef43e27a002144cce9da133304436d22ba0)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **engine:** never treat a storage error as a missing feature artifact ([3fed8f4](https://github.com/Brad-Edwards/shifter/commit/3fed8f423a65f4dff09cfd55a94a1303f5243a79)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **gcp:** apply capacity autoscalers and the Guacamole ceiling on CI deploys ([ea0365e](https://github.com/Brad-Edwards/shifter/commit/ea0365e77f3b16a0d6c04ff2b522c9e172c6ff49)), closes [#2502](https://github.com/Brad-Edwards/shifter/issues/2502)
* **gcp:** clear CI on the overlay identity renderer ([d2b9d78](https://github.com/Brad-Edwards/shifter/commit/d2b9d780ae21911de2476152ca7b70764df85f65))
* **gcp:** enable feature-artifact acquisition on CI-deployed tenants ([acdd7e2](https://github.com/Brad-Edwards/shifter/commit/acdd7e2b3171c55380c9d3f8358117cbd6bcfec7))
* **gcp:** enable feature-artifact acquisition on CI-deployed tenants ([a57a1ae](https://github.com/Brad-Edwards/shifter/commit/a57a1ae446bca2704287485f0a106948f40a7797))
* **gcp:** force-destroy the assets and audit-logs buckets during teardown ([17ee2ac](https://github.com/Brad-Edwards/shifter/commit/17ee2ace2e667111967bddc8d7ca9d68aa122dba))
* **gcp:** let the destroy workflow force-destroy the assets and audit-logs buckets ([4ff12d3](https://github.com/Brad-Edwards/shifter/commit/4ff12d3de1e8742ac4415fdd0f337abdb4fd49ff)), closes [#2258](https://github.com/Brad-Edwards/shifter/issues/2258)
* **gcp:** raise Guacamole backend WebSocket timeout past the 30s default ([61d8e90](https://github.com/Brad-Edwards/shifter/commit/61d8e9049a9ea17034e629e065bb97e7aa624d1e))
* **gcp:** raise Guacamole backend WebSocket timeout past the 30s default ([be90693](https://github.com/Brad-Edwards/shifter/commit/be906939383a4f336a2a487a54d1addb336532df))
* **gcp:** remove unreachable log config comparison loop ([b4d11c1](https://github.com/Brad-Edwards/shifter/commit/b4d11c1a36130ded63753ff3197243978073f630))
* **gcp:** render tenant deploy identity at deploy time, not in committed overlays ([46cf550](https://github.com/Brad-Edwards/shifter/commit/46cf55064d31a4988c3cfa246315cc08b3d741d4)), closes [#2468](https://github.com/Brad-Edwards/shifter/issues/2468)
* **gcp:** render tenant deploy identity at deploy time; stop committing it ([5719f69](https://github.com/Brad-Edwards/shifter/commit/5719f699a2ede7517bc28badc4a457ddad8ccebd))
* **gcp:** render the Guacamole BackendConfig with the edge manifest ([2af5750](https://github.com/Brad-Edwards/shifter/commit/2af5750dd1bbb955969ab05e806fa0acc93e422d))
* **gcp:** render the Guacamole BackendConfig with the edge manifest ([0c65ca0](https://github.com/Brad-Edwards/shifter/commit/0c65ca0639618858b713bc922ae423e76842aa42))
* **gcp:** type subnet patch client and update telemetry CI contracts ([c96f804](https://github.com/Brad-Edwards/shifter/commit/c96f804b2b7be169463d2443ad7bad562a9affed))
* **identity:** make administration service export explicit ([79b05ca](https://github.com/Brad-Edwards/shifter/commit/79b05cacc72ab6ee723e2c575361b83713869802))
* **identity:** preserve administration invariants ([b0e38a8](https://github.com/Brad-Edwards/shifter/commit/b0e38a89edc3e3599abe316dd4f29d571886aae8))
* **installation:** own FEATURE_ARTIFACT_JOB_IMAGE as a GCP Helm-rendered key ([fa834ce](https://github.com/Brad-Edwards/shifter/commit/fa834ce467b4f20924293cc19a24ae80b83de434))
* **k8s:** retry ResourceQuota admission conflicts instead of treating them as existing objects ([32f4808](https://github.com/Brad-Edwards/shifter/commit/32f4808354213c5fceb0fa024450400eea72a3c2))
* **k8s:** retry ResourceQuota admission conflicts instead of treating them as existing objects ([8b33e01](https://github.com/Brad-Edwards/shifter/commit/8b33e013597f0b87c7265a725109c528ae50fc7b))
* **packer:** enable the cloud-init units the converted Kali actually ships ([49284f4](https://github.com/Brad-Edwards/shifter/commit/49284f44d389d77505571f25ca9bb37402ebdc5f))
* **packer:** enable the cloud-init units the converted Kali actually ships ([b2b70b8](https://github.com/Brad-Edwards/shifter/commit/b2b70b824b2bb0d627ac11874939d85ed8cba928)), closes [#2459](https://github.com/Brad-Edwards/shifter/issues/2459)
* **packer:** fetch Kali packages over HTTPS and admit the Debian AMI publisher ([879a44d](https://github.com/Brad-Edwards/shifter/commit/879a44d16eb589b06fb013d54891469fe6e84791)), closes [#2459](https://github.com/Brad-Edwards/shifter/issues/2459)
* **packer:** harden AWS Kali AMI networking so range guests bind :22 ([e622771](https://github.com/Brad-Edwards/shifter/commit/e622771f8e1c9b82b20ae7fe44e0afd9de03027e))
* **provisioner:** converge EC2 range network through read-after-write lag ([0db5b9e](https://github.com/Brad-Edwards/shifter/commit/0db5b9e3de9d53e25b688d501b42d8d773b903da))
* **provisioner:** dedupe security-group grants before authorize ([908c3b7](https://github.com/Brad-Edwards/shifter/commit/908c3b7e5eed52d9dba309a909f5cf0021b9c7bc))
* **provisioner:** drop MaxResults from owned EC2 lookups ([54e31c2](https://github.com/Brad-Edwards/shifter/commit/54e31c296f74a05ff5a20991716a03bcd86e850a))
* **provisioner:** fail the range when its realized result is rejected ([284a1dd](https://github.com/Brad-Edwards/shifter/commit/284a1dd54b1868496029588571d70dfe93e6b26b))
* **provisioner:** give plugin guest actions the standard readiness bound ([dcad368](https://github.com/Brad-Edwards/shifter/commit/dcad368a9f03585002723a348f37ccf1adad42a7))
* **provisioner:** give plugin guest actions the standard readiness bound ([0c08fe6](https://github.com/Brad-Edwards/shifter/commit/0c08fe6cc1e75b5bf5c9e69f48749422601de94f))
* **provisioner:** recognize range-guest ENIs by TagSet in EC2 cleanup ([2e61529](https://github.com/Brad-Edwards/shifter/commit/2e615291bb6e76b20fb276a454363d8a3eb0b04c))
* **provisioner:** report which content-delivery step failed ([ea43f74](https://github.com/Brad-Edwards/shifter/commit/ea43f74847083d0de5250a1f97c795c955399245)), closes [#2463](https://github.com/Brad-Edwards/shifter/issues/2463)
* **provisioner:** report why guest SSH never became ready ([5fd873f](https://github.com/Brad-Edwards/shifter/commit/5fd873f6af5ea81a743164c3e82823cb5d5e04ea))
* **provisioner:** report why guest SSH never became ready ([d8e86b4](https://github.com/Brad-Edwards/shifter/commit/d8e86b47fb38cb2917c98d2d161ca49a9d0ac757))
* **provisioner:** scope AWS range resources by the infra env, not Django's ([3b82277](https://github.com/Brad-Edwards/shifter/commit/3b822773a5a1887482adc0f8191dfdf46a3e60e0))
* **provisioner:** set authored subnet_name on realized EC2 members ([a64590a](https://github.com/Brad-Edwards/shifter/commit/a64590a063b0f86400768f0e6a2414ac780b085d))
* **provisioner:** surface the real provision error, not the cleanup's ([2c2c8e2](https://github.com/Brad-Edwards/shifter/commit/2c2c8e20ade6e72b10d852df2f6075d49f021edc))
* **provisioner:** tolerate Secrets Manager read-after-write lag for new guest secrets ([7451723](https://github.com/Brad-Edwards/shifter/commit/7451723812433824e855619aa5737e2d125b33b0))
* **range:** close the pool server's HTTP client and pin the pool envelope ([181e547](https://github.com/Brad-Edwards/shifter/commit/181e5477cab05801a2b001141602afc3cace500e)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **range:** let provisioner Jobs reach the OpenVPN gateway health responder ([d91bb48](https://github.com/Brad-Edwards/shifter/commit/d91bb4842496c530db3680052aef687ddecfb001)), closes [#2030](https://github.com/Brad-Edwards/shifter/issues/2030)
* **range:** narrow the activation realization, plan teardown names without a secret keyword ([524ff68](https://github.com/Brad-Edwards/shifter/commit/524ff681fab47e5f68ecaa493f59c78f24e83906)), closes [#2030](https://github.com/Brad-Edwards/shifter/issues/2030)
* **range:** run the pool server unprivileged and clear its Sonar findings ([7a184da](https://github.com/Brad-Edwards/shifter/commit/7a184da5e3642f5a86b8a16d138b433d19257e92)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **range:** shorten the pool keepalive to 5/30 seconds ([a418416](https://github.com/Brad-Edwards/shifter/commit/a4184165f6d468638b827eeab35043d3574168e0)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **range:** tell pool clients to reconnect when a server stops ([24c0309](https://github.com/Brad-Edwards/shifter/commit/24c03094ecbc1f680e62690382a1e2ce0c0130c4)), closes [#2480](https://github.com/Brad-Edwards/shifter/issues/2480)
* **security:** bump @modelcontextprotocol/sdk to 1.32.1 (GHSA-6qxp-vccf-f47h) ([24a77db](https://github.com/Brad-Edwards/shifter/commit/24a77dba484049f54dcab81fe1a90ffe2f8ef9cd))
* **security:** bump @modelcontextprotocol/sdk to 1.32.1 (GHSA-6qxp-vccf-f47h) ([2337dde](https://github.com/Brad-Edwards/shifter/commit/2337dde5d32163de1041c22563aa41c1777055c6))
* **smoke:** include the provisioner's bounded diagnostic in the failure reason ([22dba48](https://github.com/Brad-Edwards/shifter/commit/22dba486378043942440a98c53781cf440ceeb34))
* **smoke:** include the provisioner's bounded diagnostic in the failure reason ([952e9c4](https://github.com/Brad-Edwards/shifter/commit/952e9c4273ed82a6b377123586da9d08eac79acd))
* **smoke:** report the failed range's recorded reason ([339a043](https://github.com/Brad-Edwards/shifter/commit/339a0436d5471ed57587658fd17eadb702db22ac))
* **smoke:** report the failed range's recorded reason ([e2e58fa](https://github.com/Brad-Edwards/shifter/commit/e2e58fa7d2f90a76d08fc1310f3571f93dd70ff6))

## [4.0.0](https://github.com/Brad-Edwards/shifter/compare/v3.105.0...v4.0.0) (2026-10-01)


### ⚠ BREAKING CHANGES

* **ctf:** add scoped communication API and retire legacy writes

### Features

* **adapters:** bind tenant-managed target images ([872866a](https://github.com/Brad-Edwards/shifter/commit/872866a124bd2c8f714c944ec334b0c27f20d9fb))
* **adapters:** bind tenant-managed target images ([8d54549](https://github.com/Brad-Edwards/shifter/commit/8d54549c8ad9ab01ae37585143582bfb76c76b6c))
* **adapters:** support prepromoted directory images ([2dc6cbc](https://github.com/Brad-Edwards/shifter/commit/2dc6cbcc19424b55cb85391595284a4ed6fd33ed))
* add sauron GCP tenant scaffolding ([a0b0d2e](https://github.com/Brad-Edwards/shifter/commit/a0b0d2ef13eb5f775f7d215d799bf8b183052eb0))
* add sauron GCP tenant scaffolding ([#2259](https://github.com/Brad-Edwards/shifter/issues/2259)) ([7bffe24](https://github.com/Brad-Edwards/shifter/commit/7bffe24e07a91f9607b90f45a5ea2fffe48dc8b5))
* add sauron GCP tenant scaffolding ([#2259](https://github.com/Brad-Edwards/shifter/issues/2259)) ([3847520](https://github.com/Brad-Edwards/shifter/commit/38475207ff51f2c13efbc9ebaf69106a9e6ca220))
* **auth:** unify human and service credentials ([4a0ccba](https://github.com/Brad-Edwards/shifter/commit/4a0ccba9b4729d68d72a9a8b736877b53e71cfdc))
* **auth:** unify human and service credentials ([cd9c662](https://github.com/Brad-Edwards/shifter/commit/cd9c6629168443e2d5e73ca54a88a788804987d9))
* **authz:** implement scoped OpenFGA authorization ([c656707](https://github.com/Brad-Edwards/shifter/commit/c656707daf6d42d501c9a640f2b9f7b338e5dee1))
* **ctf:** add scoped communication API and retire legacy writes ([c939a3d](https://github.com/Brad-Edwards/shifter/commit/c939a3d9d0eaff701c4c6600e62db411b53ad1c1))
* **ctf:** stage unified authorization contracts ([f64e460](https://github.com/Brad-Edwards/shifter/commit/f64e4606b9b03465a091e693beacac002b4e29f2))
* **gcp:** add balrog tenant scaffolding ([10e4d1d](https://github.com/Brad-Edwards/shifter/commit/10e4d1d7631ac468e040acf7d0bfd09d3bcd93ea))
* **gcp:** add balrog tenant scaffolding ([64d625b](https://github.com/Brad-Edwards/shifter/commit/64d625b013a2c8a822e0532fbc6fe2c5ce31ca18))
* **gcp:** add orthanc GCP tenant scaffolding ([663c6ce](https://github.com/Brad-Edwards/shifter/commit/663c6ce2d73e200acd8db940894f48106985d3f4))
* **gcp:** add orthanc GCP tenant scaffolding ([9f5cbfd](https://github.com/Brad-Edwards/shifter/commit/9f5cbfd931c9db1add36443c9fb4170e66617e3a))
* **gcp:** deploy reviewed broker overlay and reconcile runtime drift ([3a35ef0](https://github.com/Brad-Edwards/shifter/commit/3a35ef0d764317f92099f4c5df787765b398f9a9))
* **gcp:** drop unbacked proof bake target and add destroy secret preflight ([d728157](https://github.com/Brad-Edwards/shifter/commit/d72815742b35ca04524db01e7519ef7e49117bab)), closes [#2288](https://github.com/Brad-Edwards/shifter/issues/2288)
* **gcp:** generalize tenant teardown workflow and unify gcp-dev bake naming ([e46d0ff](https://github.com/Brad-Edwards/shifter/commit/e46d0ff8fe0afb392bbb652100f360ea2311f70a))
* **gcp:** generalize tenant teardown workflow and unify gcp-dev bake naming ([6c41c03](https://github.com/Brad-Edwards/shifter/commit/6c41c03eca08cf0459d6e1cbfd6e4dc78cfddf78)), closes [#2288](https://github.com/Brad-Edwards/shifter/issues/2288)
* **gcp:** publish VM disks to GHCR ([7d518dc](https://github.com/Brad-Edwards/shifter/commit/7d518dcbc41e713181d3979cbfd193dc3d1bf028))
* **gcp:** publish VM disks to GHCR ([3af6a9c](https://github.com/Brad-Edwards/shifter/commit/3af6a9c0776ee1b8dfdd405c5d67c1822d817806))
* **identity:** establish account and principal scope ([5aa7381](https://github.com/Brad-Edwards/shifter/commit/5aa738169623f55b544de5863dbafa0289eb7fe9))
* **identity:** prepare account administration for S8 ([42624b6](https://github.com/Brad-Edwards/shifter/commit/42624b60a0d9b531c0bee0722293a033a27c2793))
* **identity:** prepare account administration for S8 ([ed4c127](https://github.com/Brad-Edwards/shifter/commit/ed4c1277e170bfca5df7b1c607c3492da500e9ff))
* **model-access:** configure tenant model sources for ranges and events ([8c01adb](https://github.com/Brad-Edwards/shifter/commit/8c01adb4c01effbe84a80371db6333733a93ad29))
* **model-access:** configure tenant model sources for ranges and events ([e8b1c45](https://github.com/Brad-Edwards/shifter/commit/e8b1c45a8f250683e843d333d2c596ba9011660b))
* **model-access:** count-based reservation and hardened Vertex adapter ([77ead60](https://github.com/Brad-Edwards/shifter/commit/77ead609a9c754b4c96ba0ef1852e4eedabbe7e5))
* **model-access:** count-based reservation and hardened Vertex adapter ([bac0e4c](https://github.com/Brad-Edwards/shifter/commit/bac0e4c1402709acf2f2c69c30e05f4500df7ff4))
* **model-access:** expose scoped operator and organizer management ([ed0a1fd](https://github.com/Brad-Edwards/shifter/commit/ed0a1fd949e966aaac21fa8102fcb2ea93cb8a93))
* **model-access:** expose scoped operator and organizer management ([c7fba76](https://github.com/Brad-Edwards/shifter/commit/c7fba76b5e5faa950e6d4a87cd81ff5946ffac73))
* **model-access:** harden private broker and control API ([8bab829](https://github.com/Brad-Edwards/shifter/commit/8bab8294e4dbfb9a664e39afb97abb092d6e4fa2))
* **model-access:** harden private broker and control API ([39331c7](https://github.com/Brad-Edwards/shifter/commit/39331c710f831e09038b810755a0a3fafa1b9b83))
* **packer:** aws pre-promoted DC bake (dc-prebaked) ([e0b450e](https://github.com/Brad-Edwards/shifter/commit/e0b450efab07254e5c3bd8f07fa0727d44c3c203))
* **packer:** AWS pre-promoted DC bake (dc-prebaked) ([56e7b8a](https://github.com/Brad-Edwards/shifter/commit/56e7b8a925acdec69a9af49c8197d3f7503ea844))
* **packs:** ingest bounded model demand ([f3f2a37](https://github.com/Brad-Edwards/shifter/commit/f3f2a37b0e895a034f484cd2a7cac4173aa46f96))
* **runtime:** install external scenario adapters through tenant administration ([6cbd207](https://github.com/Brad-Edwards/shifter/commit/6cbd20705c3c9eaf22e423bfa4a94869fb48b02e))


### Bug Fixes

* Allow portal to reach Guacamole token API on GKE ([9d33e29](https://github.com/Brad-Edwards/shifter/commit/9d33e290baa13e39782673c61aebf5fde419fcff))
* **api:** refresh credential contract artifacts ([6ea07ed](https://github.com/Brad-Edwards/shifter/commit/6ea07ed1e13a890f6f32c81b52e7576067547c17))
* **auth:** align token revocation lock order with admission ([0f7b4f7](https://github.com/Brad-Edwards/shifter/commit/0f7b4f741a9b59f856f2b8564d46ece0ae9da810))
* **auth:** preserve managed pool cleanup under principal protection ([68531af](https://github.com/Brad-Edwards/shifter/commit/68531af3914a985076c795113f0f316c7d78c273))
* **auth:** resolve delivery gate failures ([1fd2770](https://github.com/Brad-Edwards/shifter/commit/1fd27700d2dec0cef3be356757b5ea9247528df4))
* **aws:** delete stray portal/alb module + formatting ([e76bbba](https://github.com/Brad-Edwards/shifter/commit/e76bbba4f94922a7db6af2ba196c733a5c1fe298))
* **aws:** resolve Security (IaC) gate after the ECS/EC2 rip ([8e4781a](https://github.com/Brad-Edwards/shifter/commit/8e4781a3edde01a169d019cf9577b96327c3e4cf))
* bind gcp deploy identities by purpose ([a89c81d](https://github.com/Brad-Edwards/shifter/commit/a89c81df870bd65a57e1ab72b8b3f69691ac92ae))
* bootstrap GCP foundations before native image bakes ([28bd355](https://github.com/Brad-Edwards/shifter/commit/28bd35574000d0ae2a5fac3faee13e964e985d81))
* bootstrap GCP foundations before native image bakes ([129eaff](https://github.com/Brad-Edwards/shifter/commit/129eaffdf7ab996305d28cdb382263c153434b7f))
* **bootstrap:** honor --yes in confirm_or_manual for headless standup ([b01b335](https://github.com/Brad-Edwards/shifter/commit/b01b3353d796d89139e20c98e25ffd8b486e9daf))
* **bootstrap:** honor --yes in confirm_or_manual for headless standup ([27ad585](https://github.com/Brad-Edwards/shifter/commit/27ad5855fdb1599f1a1587ae07ddb5d0ef7cce38))
* **bootstrap:** honor assume-yes on interactive terminals ([65578e0](https://github.com/Brad-Edwards/shifter/commit/65578e0336f7a5e9fc158861b32d7c52c213c4fb))
* **bootstrap:** poll SSM invocation instead of the 100s-capped waiter ([3e45407](https://github.com/Brad-Edwards/shifter/commit/3e454079ba1a26471ffb203cb851144be5e0a418))
* **bootstrap:** register shipped catalog after GCP migrations ([3a34650](https://github.com/Brad-Edwards/shifter/commit/3a34650f6d8ae658ee96145991d1bb011c389679))
* **bootstrap:** register shipped catalog after GCP migrations ([87458f8](https://github.com/Brad-Edwards/shifter/commit/87458f8811dd958a5e8dcd44391c82410c4f4198))
* **bootstrap:** type-hint the injectable sleep params (Sonar S6540) ([1e233d2](https://github.com/Brad-Edwards/shifter/commit/1e233d28f43cf10442f0beb26d42afb4fb79cccb))
* **bootstrap:** wait for runner SSM-online + install before registering ([7da8ff6](https://github.com/Brad-Edwards/shifter/commit/7da8ff6a89328690c421c402e6ff4940cde87d4c))
* **bootstrap:** wait for runner SSM-online + install before registering ([81d91ca](https://github.com/Brad-Edwards/shifter/commit/81d91ca53dc4fc6bd06bffedfc5955ac71d620d8))
* **charts:** add jobs-namespace private-service + range-access egress netpols ([06e87c5](https://github.com/Brad-Edwards/shifter/commit/06e87c51fb7b27126f2af89bffd3677f09c45b55))
* **charts:** add jobs-namespace private-service + range-access egress netpols ([c4decc0](https://github.com/Brad-Edwards/shifter/commit/c4decc031b74499b96485cd8caaa602866ceace4))
* **ci:** install kubectl + helm in the EKS deploy job ([28d1896](https://github.com/Brad-Edwards/shifter/commit/28d18964cb9ec600a2f6baced7bac383527dd775))
* **ci:** install kubectl + helm in the EKS deploy job ([54035cf](https://github.com/Brad-Edwards/shifter/commit/54035cfd3893ab025cc87e451db6a32bb8950558))
* **ci:** preserve branch identity in manual Sonar scans ([e960b30](https://github.com/Brad-Edwards/shifter/commit/e960b3037b9569a53baa394dcfcc6beb54a05dfc))
* **ci:** preserve branch identity in manual Sonar scans ([b998ad6](https://github.com/Brad-Edwards/shifter/commit/b998ad6a4257bc421f846112ad5f06ac5830133a))
* **ci:** run EKS preflight from scripts/bootstrap so the module resolves ([2b0fd9a](https://github.com/Brad-Edwards/shifter/commit/2b0fd9a68a2839bf1d2d648d85145e7b9d4f843e))
* **ci:** run EKS preflight from scripts/bootstrap so the module resolves ([e9d5c22](https://github.com/Brad-Edwards/shifter/commit/e9d5c224af8eb8c70676134c16ce6ab7ecb4f383))
* **ci:** update GCP database contract fixtures ([03824c1](https://github.com/Brad-Edwards/shifter/commit/03824c12cd53a7067b0cd9b1d0946f918cbfe954))
* clear adapter binding quality findings ([9726087](https://github.com/Brad-Edwards/shifter/commit/9726087ada6f5166fec56850671e3abe9ca26041))
* **cms:** log bounded RAES rejection diagnostics ([9a149fe](https://github.com/Brad-Edwards/shifter/commit/9a149fe2a435b32e4f03d1d523e397753afc53dd))
* **cms:** log bounded RAES rejection diagnostics ([c40a9f7](https://github.com/Brad-Edwards/shifter/commit/c40a9f7d0c56c308c857e2c02c81f0c3d5ee5b9e))
* **ctf:** authorize launches for tenant-owned content ([2dcdbb7](https://github.com/Brad-Edwards/shifter/commit/2dcdbb78c45fb58f0cc28f42592c4ece30628eb4))
* **ctf:** bind tenant adapters for participant ranges ([49620fd](https://github.com/Brad-Edwards/shifter/commit/49620fd402e3b1d1d20c1348f63ff7ab61e27286))
* **ctf:** clarify communication contracts and simplify admission ([8aee758](https://github.com/Brad-Edwards/shifter/commit/8aee758331286293cdc837d94eb95fafa5674ae0))
* **ctf:** connect RAES participant terminals ([20d6f43](https://github.com/Brad-Edwards/shifter/commit/20d6f43333e8a494a2e477dfba612dc831af6301))
* **ctf:** connect RAES participant terminals ([fdc4afb](https://github.com/Brad-Edwards/shifter/commit/fdc4afb532fd6038b5d334cc2416c3febe05019e))
* **ctf:** keep spare teardown retryable after dispatch failure ([8a31d04](https://github.com/Brad-Edwards/shifter/commit/8a31d04694594b7ec82dae775667de21b4ab6e19))
* **ctf:** preserve model grant during range realization ([d8d7edc](https://github.com/Brad-Edwards/shifter/commit/d8d7edcce4f19c9e439ec2cc4d19f93f5ddc6761))
* **ctf:** preserve typed inbox and notification authorization ([34a5a63](https://github.com/Brad-Edwards/shifter/commit/34a5a637f119d377027a7749fde776734dfa6142))
* **ctf:** retain spare cleanup ownership on dispatch failure ([06f8713](https://github.com/Brad-Edwards/shifter/commit/06f8713d2d44064855fb7ec866212891473ce802))
* **ctf:** scale event egress without per-range routers ([b7c40dd](https://github.com/Brad-Edwards/shifter/commit/b7c40dd547d917f41898baf2a95842cb8d113541))
* **deploy:** add sauron as a nazgul-peer GCP environment ([110aef6](https://github.com/Brad-Edwards/shifter/commit/110aef613ad33653caba665ff2aee99c19af1903)), closes [#2281](https://github.com/Brad-Edwards/shifter/issues/2281)
* **deploy:** add sauron to deploy.yml (nazgul-peer CI deploy path) ([ffd7b24](https://github.com/Brad-Edwards/shifter/commit/ffd7b24f07339d542fd1c2e4cf63886a68d2acfc))
* **deps:** remediate the published CVE wave across all lockfiles ([8eee85d](https://github.com/Brad-Edwards/shifter/commit/8eee85d23784c152bda43e241a1e1ea078d42612))
* **engine:** reconcile range NGFW grant ([32b25ac](https://github.com/Brad-Edwards/shifter/commit/32b25ac6ad45d6470541be2cea78c2fedbe578da))
* **engine:** reconcile subnet coordination grants ([8ef4e22](https://github.com/Brad-Edwards/shifter/commit/8ef4e2289da5f3954d23ce00d8a9abfe0fd887a9))
* finish image profile quality gate ([fb8e84b](https://github.com/Brad-Edwards/shifter/commit/fb8e84b89741b2a147094c2d2943e282e8ad37c5))
* format gcp dev terraform variables ([f09d456](https://github.com/Brad-Edwards/shifter/commit/f09d4566de53e3541bfbb0ad8145f3cef0df413c))
* format gcp dev terraform variables ([69136a0](https://github.com/Brad-Edwards/shifter/commit/69136a0cb1b378bd81f1758e7f6e50202b4fec2c))
* **gcp-dev:** blank REDIS_HOST in the migrator job so migrations run without Redis ([c6ac675](https://github.com/Brad-Edwards/shifter/commit/c6ac675694e4d6876d69ad6460b0bbe2bc0112f8))
* **gcp-dev:** blank REDIS_HOST in the migrator job so migrations run without Redis ([c462dfd](https://github.com/Brad-Edwards/shifter/commit/c462dfdcd741c7262ae3b0054bc306a9b5dec0f4))
* **gcp-dev:** configure Artifact Registry auth before provenance verify ([b44273f](https://github.com/Brad-Edwards/shifter/commit/b44273f9851915a85b01d98acca1cc2a7f2e5591))
* **gcp-dev:** configure Artifact Registry auth before provenance verify ([c754b40](https://github.com/Brad-Edwards/shifter/commit/c754b401ab331abddcc6a02cea53168c8105521b))
* **gcp-dev:** move GKE to RAPID channel for the 1.37 VAP-informer fix ([c8ac45c](https://github.com/Brad-Edwards/shifter/commit/c8ac45ce7690138f10900bdfe900202c8c32f83e))
* **gcp-dev:** move GKE to RAPID channel for the 1.37 VAP-informer fix ([8e22b95](https://github.com/Brad-Edwards/shifter/commit/8e22b95f9ca6b40138bcddb77b5884d45f7952fc))
* **gcp-dev:** repair the gcp-dev-destroy teardown path ([#2258](https://github.com/Brad-Edwards/shifter/issues/2258)) ([37f0b11](https://github.com/Brad-Edwards/shifter/commit/37f0b11bec2c6fe6647e930d2342393ab6abac51))
* **gcp-dev:** repair the gcp-dev-destroy teardown path ([#2258](https://github.com/Brad-Edwards/shifter/issues/2258)) ([7379baa](https://github.com/Brad-Edwards/shifter/commit/7379baaff96626589f4b36876fdaaef823a3d676))
* **gcp-dev:** set runAsUser on the migrator job for non-root verification ([c19f3b4](https://github.com/Brad-Edwards/shifter/commit/c19f3b42f99fdf40c2d8a9f088379922e05c520e))
* **gcp-dev:** set runAsUser on the migrator job for non-root verification ([1e7181d](https://github.com/Brad-Edwards/shifter/commit/1e7181dbd6148a534a4dcbf27140739f8dbf89be))
* **gcp:** adopt pre-provisioned Identity Platform config on deploy ([0f7b210](https://github.com/Brad-Edwards/shifter/commit/0f7b210b3b07b33bc0e15aa4052ceece931901a2))
* **gcp:** adopt pre-provisioned Identity Platform config on deploy ([9c9059c](https://github.com/Brad-Edwards/shifter/commit/9c9059c4cc6412f6bd3ee8b32347b48ae2a614f6))
* **gcp:** align IAM guard and bootstrap fixtures with identity contracts ([35120b6](https://github.com/Brad-Edwards/shifter/commit/35120b6a44c842f179e86fbdd41bb89ada35149c))
* **gcp:** allow CTF scheduler to read default pack archives ([a0fe625](https://github.com/Brad-Edwards/shifter/commit/a0fe6257f9192350c16995026469f268b14616f7))
* **gcp:** allow documented smoke probes to reach range guests ([5ce56d0](https://github.com/Brad-Edwards/shifter/commit/5ce56d04a993d6351b94e6a65fd6561ec16a3cc0))
* **gcp:** allow IAP access to Linux bake hosts ([9efb99e](https://github.com/Brad-Edwards/shifter/commit/9efb99e5fb86a634fbe5739d52f7cb1db1dbe4cb))
* **gcp:** allow IAP access to Linux bake hosts ([d875372](https://github.com/Brad-Edwards/shifter/commit/d8753725acba65cd7689ff99b94d50040ac911a4))
* **gcp:** allow validated tenant pack uploads through WAF ([a635f49](https://github.com/Brad-Edwards/shifter/commit/a635f493ea1fb263624b238c5e082e9d7aab93cd))
* **gcp:** attach direct range identity by broker admission ([67eb3f1](https://github.com/Brad-Edwards/shifter/commit/67eb3f13c77a35a31d645b5971196b400aa5ede5))
* **gcp:** avoid disrupting WinRM during DC finalization ([3aaed6a](https://github.com/Brad-Edwards/shifter/commit/3aaed6a5b827b9525ba3f1c02f2b5900d93debfb))
* **gcp:** bootstrap post-deploy smoke pack ([cdcaad2](https://github.com/Brad-Edwards/shifter/commit/cdcaad226e2b85a90451eaa5eb4165cfa89a1010))
* **gcp:** classify image network module and secure CLI scan ([5ddde67](https://github.com/Brad-Edwards/shifter/commit/5ddde679bcc45192ca0d84fb1f251ce6052f51a8))
* **gcp:** complete migration and workload runtime bindings ([35d268d](https://github.com/Brad-Edwards/shifter/commit/35d268d230fa93519d487402aad333936a7aa941))
* **gcp:** complete migration and workload runtime bindings ([472aa52](https://github.com/Brad-Edwards/shifter/commit/472aa52046fd7c06aa3f5c13cd5959ff960fa405))
* **gcp:** correct nazgul k8s overlay project ([4760999](https://github.com/Brad-Edwards/shifter/commit/47609993e896f43b8405eeddf1e9b6e0bf9b3fd1))
* **gcp:** correct tenant overlay and pod-range bindings ([5d9eab5](https://github.com/Brad-Edwards/shifter/commit/5d9eab5458eb7478828362576b2285a48780a99a))
* **gcp:** correct Vale em-dash spacing in ADR enforcement doc ([b7ab2cb](https://github.com/Brad-Edwards/shifter/commit/b7ab2cb99c7ac236d16c33b4507f1048f825e42d))
* **gcp:** document and type destroy ref validation helper ([ff0defa](https://github.com/Brad-Edwards/shifter/commit/ff0defadff500a63607925f7af77cd7a3bde87a4))
* **gcp:** expose scoped web egress on runtime target profiles ([7fb921b](https://github.com/Brad-Edwards/shifter/commit/7fb921b12418887ee3e3eeab78567a1dfb47e47e))
* **gcp:** extend destroy convergence window ([156b74d](https://github.com/Brad-Edwards/shifter/commit/156b74d64e2016e3a6abf7b857424600a30d4a5c))
* **gcp:** fetch imported disk blob by digest ([a56af51](https://github.com/Brad-Edwards/shifter/commit/a56af51a2e169d5fcaba6f1b8430a1ce0c2f3076))
* **gcp:** grant scheduler read access to default pack archives ([a61c748](https://github.com/Brad-Edwards/shifter/commit/a61c7482c063c9d7a994bf18b1016da51c7f890b))
* **gcp:** handle sparse workload templates and scanner rules ([e3f7946](https://github.com/Brad-Edwards/shifter/commit/e3f79468dcc8a78600e13dfc934a7191f6c2504e))
* **gcp:** honor admin-selected public web egress for runtime target images ([a856220](https://github.com/Brad-Edwards/shifter/commit/a85622018318d99c3f64d39b9ae9c0a126bb6e39))
* **gcp:** hydrate smoke job runtime secrets ([190aa5c](https://github.com/Brad-Edwards/shifter/commit/190aa5c80c489530b20266a776d2ee6f7bf9daef))
* **gcp:** include GKE master CIDR in the launcher kube-API egress (helm path) ([8ded371](https://github.com/Brad-Edwards/shifter/commit/8ded371ff9f5769738303b3a6e7f0db9457b1b00))
* **gcp:** include the GKE master CIDR in the launcher kube-API egress (helm path) ([87b0c90](https://github.com/Brad-Edwards/shifter/commit/87b0c905278ac38fbe30f3c456350fc42b1dbe06))
* **gcp:** isolate provisioner database credentials ([f53f812](https://github.com/Brad-Edwards/shifter/commit/f53f812419311e111ab83eb201444e4288c9703d))
* **gcp:** make Identity Platform provisioning idempotent via config GET ([cd382e1](https://github.com/Brad-Edwards/shifter/commit/cd382e1697777130bad06d0309a10dfb039f612c))
* **gcp:** make public image bootstrap foundation-safe ([0d14307](https://github.com/Brad-Edwards/shifter/commit/0d14307d40f3d3dcd0ddd39e9cb4036363b5cbd7))
* **gcp:** make public image bootstrap foundation-safe ([1c8a1b2](https://github.com/Brad-Edwards/shifter/commit/1c8a1b2b077eedd38a47a2b484a577065f22bb15))
* **gcp:** make public image bootstrap reliable ([e60f4f7](https://github.com/Brad-Edwards/shifter/commit/e60f4f7d1228a642e9de106e7bd3c4d495666bf1))
* **gcp:** make range smoke and provisioner DB access reliable ([57d7ad4](https://github.com/Brad-Edwards/shifter/commit/57d7ad4ffbb7ca5e4aa5c01d6fc83aaea781a8ef))
* **gcp:** make tenant destroy converge ([2af0b2c](https://github.com/Brad-Edwards/shifter/commit/2af0b2c3b16dbf89bcdce6df92b8888017842e31))
* **gcp:** order workload bindings after GKE identity pool creation ([15c558b](https://github.com/Brad-Edwards/shifter/commit/15c558b3b1ef01f3661dce18d916bfa710a7128c))
* **gcp:** order workload bindings after GKE identity pool creation ([29a88b3](https://github.com/Brad-Edwards/shifter/commit/29a88b32f00e1746dbd88551497131922c7abdd9))
* **gcp:** parameterize dict annotations (SonarCloud S6543) ([80d9f15](https://github.com/Brad-Edwards/shifter/commit/80d9f157a5dc5b9e90f0f459c2c6a853d4d320a7))
* **gcp:** pin shared pools to primary pod range ([8a545b7](https://github.com/Brad-Edwards/shifter/commit/8a545b73a808f267322f85ab42cb9557414773cf))
* **gcp:** point nazgul k8s overlay at its project ([9fa5e64](https://github.com/Brad-Edwards/shifter/commit/9fa5e645c7126ffb357488159b580ae3da48ed6f))
* **gcp:** point orthanc overlay at prod-lk3ssb tenant project ([b17010e](https://github.com/Brad-Edwards/shifter/commit/b17010ea5d890a69f0541930943d28a22e1eb644))
* **gcp:** point orthanc overlay at prod-lk3ssb tenant project ([fc6a8dc](https://github.com/Brad-Edwards/shifter/commit/fc6a8dc1f082f1d0c409daed5570d9f352819b33))
* **gcp:** point orthanc overlay at tenant project ([2548b2a](https://github.com/Brad-Edwards/shifter/commit/2548b2afab29027371db2215b8ce07d278b81214))
* **gcp:** preserve base image disk defaults ([7164e00](https://github.com/Brad-Edwards/shifter/commit/7164e0027e014596bf3998d40c6e8ae966cc35d1))
* **gcp:** preserve capacity profile on deploy ([c45a5dd](https://github.com/Brad-Edwards/shifter/commit/c45a5ddbb7e9ee149a0bd85d8976f03e7d523697))
* **gcp:** preserve capacity profile on deploy ([c1a689c](https://github.com/Brad-Edwards/shifter/commit/c1a689c98a5d9607a9bafebed7d683d3ffccef55))
* **gcp:** preserve platform dependencies in portal image ([c3f3bfe](https://github.com/Brad-Edwards/shifter/commit/c3f3bfeed9eba75ef90867bafbc6c488e1ce13aa))
* **gcp:** preserve platform dependencies in portal image ([d93239a](https://github.com/Brad-Edwards/shifter/commit/d93239a7c3c1086bfd7db957eca3cbd141c23df9))
* **gcp:** preserve UEFI features on image import ([a13013f](https://github.com/Brad-Edwards/shifter/commit/a13013f9e17f95ea47e17f851333719e7bab28ab))
* **gcp:** provision Identity Platform before deploy on fresh projects ([c12c791](https://github.com/Brad-Edwards/shifter/commit/c12c7912c46d60a568ba6b86bcff20e9f92c6d64))
* **gcp:** provision Identity Platform before deploy on fresh projects ([70ba184](https://github.com/Brad-Edwards/shifter/commit/70ba18451b00a3235f78beadc9cd5df05ca72c78))
* **gcp:** publish image refs through repository endpoint ([0d5c8c6](https://github.com/Brad-Edwards/shifter/commit/0d5c8c637f91b98fe038d4e61f6136968c165ca8))
* **gcp:** reconcile shared NAT for RAES ranges ([bbbc64e](https://github.com/Brad-Edwards/shifter/commit/bbbc64e8dfa9b30bc75921cd7841e42e433f40ff))
* **gcp:** reject destroy trust tuples off protected dev/main ([93a67b8](https://github.com/Brad-Edwards/shifter/commit/93a67b88267e512fdf1a5c2600937c4696ae42fb))
* **gcp:** reject destroy trust tuples off protected dev/main ([076b819](https://github.com/Brad-Edwards/shifter/commit/076b819c71958cab3df379cd5d4042337ec4c6f5))
* **gcp:** remove peering when destroying the service networking connection ([1f304f7](https://github.com/Brad-Edwards/shifter/commit/1f304f7eac0306629548551a432990b44860693b))
* **gcp:** remove temporary smoke identity secret ([f72e2ed](https://github.com/Brad-Edwards/shifter/commit/f72e2ed728baf93c16347e9d2b865006ec66566a))
* **gcp:** remove temporary smoke identity secret ([93134f6](https://github.com/Brad-Edwards/shifter/commit/93134f6cabca0569e366f178b0a2a1900176e2aa))
* **gcp:** restore Guacamole routing for declared Linux RDP ([24e186d](https://github.com/Brad-Edwards/shifter/commit/24e186d613ce6429ab19246147024411292cce14))
* **gcp:** return shared NAT reconcile result consistently ([ca55844](https://github.com/Brad-Edwards/shifter/commit/ca5584429bcc558047bcefd9d493931a97c4dee3))
* **gcp:** reuse GHCR base disks in the single GCE tenant bootstrap ([e6421b6](https://github.com/Brad-Edwards/shifter/commit/e6421b6a1bba62bac85eb16ca7d45882b527ec95))
* **gcp:** reuse GHCR base disks in the single GCE tenant bootstrap ([8235f09](https://github.com/Brad-Edwards/shifter/commit/8235f09c77b6af4ebeeb40b68265c5384e31e699))
* **gcp:** route tenant deploys to tenant runners ([2473b0d](https://github.com/Brad-Edwards/shifter/commit/2473b0d088fc339f7ce32d9dca21e5e093480d75))
* **gcp:** route tenant deploys to tenant runners ([7444abb](https://github.com/Brad-Edwards/shifter/commit/7444abbf4925a3ca3d38b16489cf82435b054493))
* **gcp:** run post-deploy smoke as job ([7b38aea](https://github.com/Brad-Edwards/shifter/commit/7b38aeaf6ba729fa9a838bb95624293417a4cb05))
* **gcp:** seed image registry during deploy ([c966618](https://github.com/Brad-Edwards/shifter/commit/c966618527db8f23ba3e75d294117e4f2f8091b4))
* **gcp:** seed image registry during deploy ([3c185fe](https://github.com/Brad-Edwards/shifter/commit/3c185fee51e60765e3ea68043c2ef3624ec9f816))
* **gcp:** set runAsUser + blank REDIS_HOST on the local bootstrap migrate Job ([d891880](https://github.com/Brad-Edwards/shifter/commit/d891880dea252cb6b5ff85ea307dc3a02bde1277))
* **gcp:** set runAsUser + blank REDIS_HOST on the local bootstrap migrate Job ([50459f2](https://github.com/Brad-Edwards/shifter/commit/50459f261bf7a51561bc6b051262746bdc213b10))
* **gcp:** support scalable preconfigured custom-image hosts ([f0d2c2e](https://github.com/Brad-Edwards/shifter/commit/f0d2c2e65833ec38ffb21df1d0f8b0cdf2c932bb))
* **gcp:** support scalable preconfigured custom-image hosts ([430c9ea](https://github.com/Brad-Edwards/shifter/commit/430c9ea95163f4dd0b04a4abf46a53a3a97902b1))
* **gcp:** sweep optional web firewall during range teardown ([9b1f781](https://github.com/Brad-Edwards/shifter/commit/9b1f781f3ccc8f6db788094dce6c959dd3a659f3))
* **gcp:** upgrade google provider to 8.x and remove service networking peering on destroy ([36ac9e1](https://github.com/Brad-Edwards/shifter/commit/36ac9e1504ce6f8455630b501d5732bb68ae3747))
* **gcp:** verify runtime image identity correctly ([f5dd503](https://github.com/Brad-Edwards/shifter/commit/f5dd5036c7e05fa6152fbda0de51b00f94500a2d))
* **gcp:** verify runtime image identity correctly ([fc4ffd0](https://github.com/Brad-Edwards/shifter/commit/fc4ffd0a9fb40a893e4c90d5cff6b75a165669d3))
* **gcp:** wait for superseded release pods ([ae8733f](https://github.com/Brad-Edwards/shifter/commit/ae8733f8eadee1bd0492f699b3007e75832a7361))
* **gcp:** wait for superseded release pods ([2e5e02e](https://github.com/Brad-Edwards/shifter/commit/2e5e02e08113a2957d36129eabfcab7952e086ae))
* grant validator transport read permissions ([8189177](https://github.com/Brad-Edwards/shifter/commit/8189177cb323b3ddb4e65a74fc6dd231a2d2dd7f))
* **guacamole:** pin patched base (Tomcat 9.0.122) to clear Tomcat/OS HIGH/CRITICAL CVEs ([e076b2b](https://github.com/Brad-Edwards/shifter/commit/e076b2b057b32e3b3592a042c90174479aa791bf))
* **guacamole:** pin patched base (Tomcat 9.0.122) to clear Tomcat/OS HIGH/CRITICAL CVEs ([7cde445](https://github.com/Brad-Edwards/shifter/commit/7cde445537fa2db89da7ed6ec5a376df942152b1))
* **guacamole:** point CMD at the base image's entrypoint.sh (1.6.0 rebuild) ([f05445c](https://github.com/Brad-Edwards/shifter/commit/f05445c50d886dba1443a2dd5710a54aac12ee06))
* **guacamole:** point CMD at the base image's entrypoint.sh (1.6.0 rebuild) ([c3f5d28](https://github.com/Brad-Edwards/shifter/commit/c3f5d28a211ebb0fe2af71a60f532f4d4e40351d))
* **guacamole:** remove unused vulnerable authentication extensions ([acf03f4](https://github.com/Brad-Edwards/shifter/commit/acf03f4464ed4cd758af1e17c9907ce18a0f6aaa))
* **guacamole:** remove unused vulnerable authentication extensions ([e557493](https://github.com/Brad-Edwards/shifter/commit/e55749310c724ed630bcf861b24c1ac26a070d24))
* **iam,ci:** raise assumed-role session to 6h for long AWS applies ([a97db65](https://github.com/Brad-Edwards/shifter/commit/a97db65c8ed641d9e69532a6592ba4d311359e79))
* **iam,ci:** raise assumed-role session to 6h for long AWS applies ([0125035](https://github.com/Brad-Edwards/shifter/commit/0125035a0eaf705b0ecf0bca1ba9d0bddfa98a26))
* **identity:** satisfy platform type checks ([6735bb8](https://github.com/Brad-Edwards/shifter/commit/6735bb8a03a0f7f0775c4bc02580b338bd4adb6c))
* increase provisioner launcher memory for burst requests ([d406c68](https://github.com/Brad-Edwards/shifter/commit/d406c68a2d98f0a5ff4056541412c16971e08893))
* increase provisioner launcher memory for burst requests ([9b8d888](https://github.com/Brad-Edwards/shifter/commit/9b8d88869272806ef1834ef25c1d9076b439c9bc))
* isolate GCP bootstrap credential inputs to the selected checkout ([6ebcc66](https://github.com/Brad-Edwards/shifter/commit/6ebcc66202db63e4c3c205891a6d01ea9c4e135d))
* isolate gcp release-scan preflight ([b601bba](https://github.com/Brad-Edwards/shifter/commit/b601bbac86d3806318517b63317a181c358f7d4d))
* isolate gcp release-scan preflight ([2c67f7e](https://github.com/Brad-Edwards/shifter/commit/2c67f7eb928bc27dee9ea6c0c6c07a10794c677a))
* keep validation tunnel available during guest boot ([c658ebf](https://github.com/Brad-Edwards/shifter/commit/c658ebfdc8b888883c9691957c214ff0385e9158))
* log bounded runtime guest action exit status ([4d73b18](https://github.com/Brad-Edwards/shifter/commit/4d73b182c023357bd8a9d7b0fc7788ce6ec7a5ce))
* **model-access:** allow same-project broker sources ([4683bbb](https://github.com/Brad-Edwards/shifter/commit/4683bbbf3ee9aceed9a573826853db97f6a9e3af))
* **model-access:** guest credential lifetime = range session; ADR-067 (enforcement optional) ([94776a4](https://github.com/Brad-Edwards/shifter/commit/94776a49bbab20559eb427e42f41722c4bedb9fa))
* **model-access:** guest credential lifetime is the range session, not the membership-freshness window ([23310c4](https://github.com/Brad-Edwards/shifter/commit/23310c41600788654678b5174142eaaa2fa790a9))
* **model-access:** keep drain test from replaying SIGTERM ([8cd3f9f](https://github.com/Brad-Edwards/shifter/commit/8cd3f9f313f1d9ab96ee1c0653f3f173a7397ae3))
* **model-access:** resolve SonarCloud findings across API, services and SPA ([56ff88d](https://github.com/Brad-Edwards/shifter/commit/56ff88dc86e7a981d2fac6ddbe3bbcb89c672986))
* **model-access:** restore contracts and resolve CI failures ([5b69495](https://github.com/Brad-Edwards/shifter/commit/5b694959c272171737373834825b7c4248d70736))
* **model-access:** restore default-on keyless range model access (ADR-064) ([cd76216](https://github.com/Brad-Edwards/shifter/commit/cd76216dc479745c19ba100fc1febb74e70c2628))
* **model-access:** restore default-on keyless range model access (ADR-064) ([d596b2e](https://github.com/Brad-Edwards/shifter/commit/d596b2e588522f0b8b8649a61000f05bd3e8613e)), closes [#2275](https://github.com/Brad-Edwards/shifter/issues/2275)
* **model-access:** route vertex token counts correctly ([58e4c3e](https://github.com/Brad-Edwards/shifter/commit/58e4c3ee68e7b2bff9cf06a9e3589a8a411c5bb4))
* **model-access:** satisfy mypy and isolate RangePage test from the model-access card ([e8bc3f2](https://github.com/Brad-Edwards/shifter/commit/e8bc3f23dd5bc8981ddbb99b989e54b9291f5bd3))
* **packer/kali:** allow aiohttp-apispec sdist in the Caldera install ([ed5c16d](https://github.com/Brad-Edwards/shifter/commit/ed5c16d05275b970a2a9cba413f33fb7bfc1634e))
* **packer/kali:** allow aiohttp-apispec sdist in the Caldera install ([8ede46f](https://github.com/Brad-Edwards/shifter/commit/8ede46f9b5d44615715e663f77029d15c36c2326))
* **packer/kali:** carve out only the sdist-only Caldera deps (keep --only-binary) ([61527d5](https://github.com/Brad-Edwards/shifter/commit/61527d5456ef301e55f2c9e138707466c64cee3e))
* **packer/kali:** drop --only-binary so Caldera's sdist-only deps install ([867d38f](https://github.com/Brad-Edwards/shifter/commit/867d38f8651af722dad16a4a25f52c32dd687cbd))
* **packer/kali:** drop --only-binary so Caldera's sdist-only deps install ([730cf91](https://github.com/Brad-Edwards/shifter/commit/730cf917359e2ee858e56563f94c1dfde5d2d262))
* **packer/kali:** enforce HTTPS on the uv installer fetch (shell:S6506) ([16bfb1a](https://github.com/Brad-Edwards/shifter/commit/16bfb1a0ea763c815cac9501e6ccfe2e5e1de75c))
* **packer/kali:** run Caldera under a uv-managed Python 3.12 ([32efbf0](https://github.com/Brad-Edwards/shifter/commit/32efbf014342e2dbcc679bf93400dbb0665342bd))
* **packer/kali:** run Caldera under a uv-managed Python 3.12 ([4268495](https://github.com/Brad-Edwards/shifter/commit/426849575f02ba845f2318821fb9829237c73d82))
* **packer:** quote ${marker} in windows EC2Launch DNS script (parse error) ([5c4788c](https://github.com/Brad-Edwards/shifter/commit/5c4788c5d1459e8901b177213fcbbe98ec5b5084))
* permit metadata on image validation instances ([0754e9f](https://github.com/Brad-Edwards/shifter/commit/0754e9f4a4c048f9db12ba6e47de1f4136cb53bb))
* **platform:** allow plugin job garbage collection ([02b5ba4](https://github.com/Brad-Edwards/shifter/commit/02b5ba4c42164afd13c1766cacd2b6c7223217ab))
* **platform:** allow tenant-sourced CTF launches ([f83ad81](https://github.com/Brad-Edwards/shifter/commit/f83ad81279533a5ed9e10141f02a6c6eb0631708))
* **platform:** preserve accepted plugin results ([81efa57](https://github.com/Brad-Edwards/shifter/commit/81efa57a7b73d5456e0e16e0dd8de199d1a6d5a9))
* **platform:** reclaim completed plugin jobs ([cb4a6a7](https://github.com/Brad-Edwards/shifter/commit/cb4a6a79260140d7aefe2691694a527e27fe82ba))
* **platform:** reconcile revoked model allocations ([2c18043](https://github.com/Brad-Edwards/shifter/commit/2c180431fac572a3091a9ec286da881972bcfb5b))
* **platform:** require patched Autobahn runtime ([3334393](https://github.com/Brad-Edwards/shifter/commit/33343938cd32a8c5d502b7492c0ae584e887556e))
* **platform:** retry transient Kubernetes quota conflicts ([cd03e05](https://github.com/Brad-Edwards/shifter/commit/cd03e0559a8427d013af7037a02a20224cebefbc))
* **platform:** unblock tenant-sourced CTF launches ([83c9b07](https://github.com/Brad-Edwards/shifter/commit/83c9b0760416d3d78be69ce6e55066205f3cfcf9))
* **portal:** patch Debian base-OS HIGH/CRITICAL CVEs ([84d0b49](https://github.com/Brad-Edwards/shifter/commit/84d0b492f6fb72e589b365412c09ebb772ec79ad))
* **portal:** patch Debian base-OS HIGH/CRITICAL CVEs ([94e0677](https://github.com/Brad-Edwards/shifter/commit/94e0677a6affa4b676262707fbf440d8726da9ac))
* **provisioner:** append operation results with insert-only privileges ([26cf56d](https://github.com/Brad-Edwards/shifter/commit/26cf56dcfccad1704be4c331bedaca405c46f0d4))
* **provisioner:** append operation results with insert-only privileges ([32b5dff](https://github.com/Brad-Edwards/shifter/commit/32b5dffb36560f5e99e1c470fe2d8e48885dd5ee))
* **provisioner:** bump Pulumi/kubectl/Terraform + base to clear HIGH/CRITICAL CVEs ([7d2d3f2](https://github.com/Brad-Edwards/shifter/commit/7d2d3f28361393f2b0c84b95c76c0c6cb0068078))
* **provisioner:** clear inherited machine image identity ([9f481f5](https://github.com/Brad-Edwards/shifter/commit/9f481f502ede4d5c8cecc18f131dd8211472f7af))
* **provisioner:** clone RAES machine images ([d83d432](https://github.com/Brad-Edwards/shifter/commit/d83d43277a78ff2a1705731eb6c9852b64a297c0))
* **provisioner:** remove unused Pulumi CLI + patch base/kubectl/terraform ([4fb5742](https://github.com/Brad-Edwards/shifter/commit/4fb57423d243c5dfe8bc22785a4c1063ec0cdaf3))
* **provisioner:** remove unused Pulumi CLI from the image ([6a364ea](https://github.com/Brad-Edwards/shifter/commit/6a364ea71034705c42fd7e7c2ecfcc96c7836859))
* **provisioner:** share instance insertion lifecycle ([3e202a2](https://github.com/Brad-Edwards/shifter/commit/3e202a2302640410d8fcd461443768c984888496))
* **range,packer:** empty-allowlist NFW rule + windows EC2Launch DNS parse + standup gotchas ([d70f6b9](https://github.com/Brad-Edwards/shifter/commit/d70f6b96574b9568a09de8e4bf79ff8abdab7ba9))
* **range:** make ssm-export for_each plan-determinable on a fresh account ([534f55c](https://github.com/Brad-Edwards/shifter/commit/534f55c1162933c7cbca6aa2039569c5c5189eda))
* **range:** make ssm-export for_each plan-determinable on a fresh account ([2fe745e](https://github.com/Brad-Edwards/shifter/commit/2fe745e977158caa36d9ac0d894b321f502f6d44))
* **range:** remove unescaped semicolon from empty-allowlist NFW rule msg ([5b4555f](https://github.com/Brad-Edwards/shifter/commit/5b4555fe911c2e23ef0926182564f75466829ed8))
* record bounded runtime-plugin guest action progress ([14c927e](https://github.com/Brad-Edwards/shifter/commit/14c927eff46043d6692cae39be4d01ba81dd4662))
* require trusted peer for dev authentication in debug mode ([f45770f](https://github.com/Brad-Edwards/shifter/commit/f45770f9f06b63597d4890016187273b0549d30d))
* restore plugin cleanup and burst quota ([84f3654](https://github.com/Brad-Edwards/shifter/commit/84f365406daf39712b08d2e6f6eee9d3735715a9))
* restrict debug-mode dev authentication to trusted peers ([26e0379](https://github.com/Brad-Edwards/shifter/commit/26e03790266a578d3af5fedd7f6724c0cea24b39))
* retry transient GCE machine-image clone rate limits ([87c58bd](https://github.com/Brad-Edwards/shifter/commit/87c58bdd442345c145085ca6036a38264fb83605))
* route nazgul deploy dispatch ([f0214a4](https://github.com/Brad-Edwards/shifter/commit/f0214a4f9ecfa3e0f96b73b3848fcdbfd82effee))
* **runtime:** align sandbox provider and native lifecycle capabilities ([36df93c](https://github.com/Brad-Edwards/shifter/commit/36df93ca1b04258e79c1702e1fa31cdfe6bd0907))
* **runtime:** clear remaining quality findings (cycle 3) ([d36b7cf](https://github.com/Brad-Edwards/shifter/commit/d36b7cf0f458066315380169f343557ababd37e1))
* **runtime:** harden private listeners and resolve quality findings (cycle 2) ([29212cf](https://github.com/Brad-Edwards/shifter/commit/29212cfc3ac7b8fe663f5f6717c71fbe64126120))
* **runtime:** reclaim completed plugin jobs ([a9cbc68](https://github.com/Brad-Edwards/shifter/commit/a9cbc68a7d54327d5ff262fdac97aa2c2cdc1daa))
* **runtime:** resolve adapter integration quality gates ([b268336](https://github.com/Brad-Edwards/shifter/commit/b2683363a25a0eefab91cb6cb53e607cbd2109c4))
* **security:** require patched Autobahn WebSocket transport ([5dfb30c](https://github.com/Brad-Edwards/shifter/commit/5dfb30c63afef10cd906e4d899678b5dee97c8f5))
* size plugin object quota for event launch bursts ([c990bfd](https://github.com/Brad-Edwards/shifter/commit/c990bfd0210b4ae431e91b7d56e38a7411416752))
* **terminal:** release slots on close races ([90ff6bf](https://github.com/Brad-Edwards/shifter/commit/90ff6bfa7c75c0a08ba3f8ce41d748ebcd7183d6))
* unblock GCP candidate validation on fresh foundations ([0a65ced](https://github.com/Brad-Edwards/shifter/commit/0a65ced3836ad69262ea4312faff819bac825b5d))

## [3.105.0](https://github.com/Brad-Edwards/shifter/compare/v3.104.0...v3.105.0) (2026-09-17)


### Features

* **audit:** add tamper-evident audit chain ([6a1eecc](https://github.com/Brad-Edwards/shifter/commit/6a1eecc99f6943f64f8e2db1d04ffbbf257ce564))


### Bug Fixes

* **openapi:** make PackRegistration digest default schema-valid ([480043f](https://github.com/Brad-Edwards/shifter/commit/480043fdeb58ee68711f1243ba9786fdcfec40b8))
* **openapi:** make PackRegistration digest default schema-valid ([9d29347](https://github.com/Brad-Edwards/shifter/commit/9d29347241033887e50cc8da95499c698a846a96))
* **provisioner:** remove dead DC bootstrap-plan path (drop S2583 suppression) ([6da4635](https://github.com/Brad-Edwards/shifter/commit/6da4635cae3aaa3d0c55533618231eac8c5d5231))

## [3.104.0](https://github.com/Brad-Edwards/shifter/compare/v3.103.0...v3.104.0) (2026-09-16)


### Features

* add administrator audit log and activity history surface ([3a30e4c](https://github.com/Brad-Edwards/shifter/commit/3a30e4c4ea20abb3bf5a93b309f4ca5be3c3ff85))
* add administrator audit log and activity history surface ([a22bfab](https://github.com/Brad-Edwards/shifter/commit/a22bfab950a1c7d2b121cd4f7d41909caff9b993))
* add AWS environment teardown workflow ([ed3a891](https://github.com/Brad-Edwards/shifter/commit/ed3a89101b1a763e44712cb148f4252df2067c98))
* add AWS environment teardown workflow ([#1287](https://github.com/Brad-Edwards/shifter/issues/1287)) ([346f868](https://github.com/Brad-Edwards/shifter/commit/346f868b3ba64abe0deef3fea6d3e12ce2f9b34e))
* add in-tenant artifact preparation ([d14930f](https://github.com/Brad-Edwards/shifter/commit/d14930f492b9b9a1bed5c984ea823f08e4f1ffc1))
* add in-tenant artifact preparation ([03f24dd](https://github.com/Brad-Edwards/shifter/commit/03f24dd26869194cb0dfb29deb8b40211c3008c2))
* add nazgul GCP tenant scaffolding + bake lane ([f092e2e](https://github.com/Brad-Edwards/shifter/commit/f092e2e5c0e7070b612f9652ad1c01777de89a20))
* add runtime Mission Control lease policies ([f830b44](https://github.com/Brad-Edwards/shifter/commit/f830b446716497270034bf4dcb1af31a4efa0752))
* administer range-to-workspace scoping and reassignment (PLAT-237) ([b9b8268](https://github.com/Brad-Edwards/shifter/commit/b9b82681818fed7da26fcedaa93d37586bc14c74))
* administer range-to-workspace scoping and reassignment (PLAT-237) ([21c27c4](https://github.com/Brad-Edwards/shifter/commit/21c27c4db22c4ecd4699679c91cc606166575b63))
* **api:** expose retry-safe range operations and truthful cleanup outcomes ([07ab2ac](https://github.com/Brad-Edwards/shifter/commit/07ab2aca4a8bc629da6e4cde8ab7cb0989d0a3d6))
* **api:** expose retry-safe range operations and truthful cleanup outcomes ([a1d823c](https://github.com/Brad-Edwards/shifter/commit/a1d823cb2ac99a82b485f071eeb5674d5066f132))
* **cms:** ship a launchable smoke-linux in-box pack ([e596e71](https://github.com/Brad-Edwards/shifter/commit/e596e71ad81d75e59dd3eba9ec9f2b57197d86ce))
* complete SPA and RAES authority cutover ([9cddc3c](https://github.com/Brad-Edwards/shifter/commit/9cddc3cfcf2c342997c561cda2c27705af7e8b59))
* complete SPA and RAES cutover ([aaa78a6](https://github.com/Brad-Edwards/shifter/commit/aaa78a64d04f7cead06100ced10364445b5c9fe9))
* **ctf:** add public event registration ([d40f27e](https://github.com/Brad-Edwards/shifter/commit/d40f27e7a854c840e77fc327b6e148ead6603ab6))
* **ctf:** bind signed receipts to range identity ([ab5bcbd](https://github.com/Brad-Edwards/shifter/commit/ab5bcbdcde4189f874aa2dab6c937ac0651a7df1))
* **ctf:** bind signed receipts to range identity ([ad97760](https://github.com/Brad-Edwards/shifter/commit/ad9776016c1659beb7a4e24113cb1aa79a281a71))
* **ctf:** durable delivery worker and in-app channel for scoped communications ([56ed720](https://github.com/Brad-Edwards/shifter/commit/56ed720345e81554ee190dbfe8897f2cea6ef2fa))
* **ctf:** durable delivery worker and in-app channel for scoped communications ([ee69e35](https://github.com/Brad-Edwards/shifter/commit/ee69e356389b1e7d150f30154c5200b051cd7570))
* **ctf:** in-place content refresh for managed CTF events ([66ccfea](https://github.com/Brad-Edwards/shifter/commit/66ccfea956623e75c0cdd306dc835686e7dee181))
* **ctf:** in-place content refresh for managed CTF events ([8416c53](https://github.com/Brad-Edwards/shifter/commit/8416c53850013ecb7992aa0905b5547679e92dbc))
* **ctf:** model scoped communication campaigns, audiences, content, and deliveries ([0d7a75d](https://github.com/Brad-Edwards/shifter/commit/0d7a75d7a5c3d2487668772eea58719add930cdd))
* **ctf:** model scoped communication campaigns, audiences, content, and deliveries ([28c4904](https://github.com/Brad-Edwards/shifter/commit/28c4904c1390559910aa094c5497d896e9feb54e))
* **ctf:** platform-admin global CTF event administration ([2324f4b](https://github.com/Brad-Edwards/shifter/commit/2324f4b57e675a7b1b1f0430626b64b47408f578))
* **ctf:** platform-admin global CTF event administration ([c7a02c6](https://github.com/Brad-Edwards/shifter/commit/c7a02c62f672466a4480b7c6fae9d382670c8491))
* **ctf:** support multiple full co-organizers per CTF event ([7863ca0](https://github.com/Brad-Edwards/shifter/commit/7863ca042f4ddc35147f93384884cf2241e018e4))
* **ctf:** support multiple full co-organizers per CTF event ([d16915a](https://github.com/Brad-Edwards/shifter/commit/d16915a761ee51ad9dc4713a7ada67b180ab27e6))
* **ctf:** unified communication admission and scheduler due-time integration ([6a9da4f](https://github.com/Brad-Edwards/shifter/commit/6a9da4f00e81ffec5c9e8e1bc7676dff20efd375))
* **ctf:** unified communication admission and scheduler due-time integration ([ac30b92](https://github.com/Brad-Edwards/shifter/commit/ac30b927bae932cb9c8fa4a1f1c412e7d41691c5))
* deployment-configurable Mission Control range lease policy ([ac9a0e5](https://github.com/Brad-Edwards/shifter/commit/ac9a0e560ba20e99744d6a314f87894af5466cb7))
* deployment-configurable Mission Control range lease policy ([79f160e](https://github.com/Brad-Edwards/shifter/commit/79f160e5ca94b855ae2899b264206767c1113b49))
* enforce browser accessibility with an axe gate and ADR-055 baseline ratchet ([d0e9533](https://github.com/Brad-Edwards/shifter/commit/d0e953395c9c6e12c4734d03de1b549d7bf4f169))
* enforce browser accessibility with an axe gate and ADR-055 baseline ratchet ([10d18f7](https://github.com/Brad-Edwards/shifter/commit/10d18f74e15a21a34534b3c935c2e907f19e65bb))
* enforce GCP zero-egress firewall for pinned none ranges (PLAT-238) ([5e625db](https://github.com/Brad-Edwards/shifter/commit/5e625db97977581f59a8954909504fcd5ad85c3a))
* **engine:** seed RAES image registry from base range image env ([c4b44fb](https://github.com/Brad-Edwards/shifter/commit/c4b44fb836f9ef16526653c2783415873381ec0c))
* **gcp:** add the [#2087](https://github.com/Brad-Edwards/shifter/issues/2087) range-escape containment-signal seam ([dea807f](https://github.com/Brad-Edwards/shifter/commit/dea807f1dfcdeaddcdcc36aa3bc501475ac072ed))
* **gcp:** add the [#2087](https://github.com/Brad-Edwards/shifter/issues/2087) range-escape containment-signal seam ([4a4613c](https://github.com/Brad-Edwards/shifter/commit/4a4613c44eda03f77758cf76b578e3b47070958d))
* **gcp:** bootstrap single-project deployments from external inventory ([5fbf929](https://github.com/Brad-Edwards/shifter/commit/5fbf929df82717164ed027c01f8ed355b95c0929))
* **gcp:** bootstrap single-project deployments from inventory ([0b08091](https://github.com/Brad-Edwards/shifter/commit/0b080912fccf7456751c92ea019c2a8761ad8563))
* **gcp:** fail-fast on GCE range preconditions before gdc-bootstrap deploys ([0105598](https://github.com/Brad-Edwards/shifter/commit/0105598a1b365438f371fa3b24ef421cdf237669))
* **gcp:** fail-fast on GCE range preconditions before gdc-bootstrap deploys ([d1b44b0](https://github.com/Brad-Edwards/shifter/commit/d1b44b0d16d2938ca9d3e8c27dfbe71f8b02b167))
* **gcp:** multi-region range-cell placement via RANGE_NETWORK_ZONES ([b89c773](https://github.com/Brad-Edwards/shifter/commit/b89c77322e837086b0de02ac1b5636cc1a3a1501))
* **gcp:** multi-region range-cell placement via RANGE_NETWORK_ZONES ([3d56aa4](https://github.com/Brad-Edwards/shifter/commit/3d56aa40990b63f22f012f6e3e25485b0b045f43))
* **gcp:** package isolated model broker deployment ([345ef30](https://github.com/Brad-Edwards/shifter/commit/345ef3022c2aa00f3cf30445fc0be9f6d8d1f7e7))
* **gcp:** package isolated model broker deployment ([05c51e8](https://github.com/Brad-Edwards/shifter/commit/05c51e84da898105be05fa55f577e6219a7994ec))
* **installation:** complete AWS EKS bundle runtime-env projection and doctor preflight ([3aa0741](https://github.com/Brad-Edwards/shifter/commit/3aa0741783c2cd339e4a99a11a882d04c19f3712))
* **installation:** complete AWS EKS bundle runtime-env projection, doctor preflight, and settings/inventory modules ([b2d3c14](https://github.com/Brad-Edwards/shifter/commit/b2d3c14e0c2360c52bb2cd681242e5d6a4784a7d))
* **mission-control:** enforce per-file agent upload limit before transfer ([9b45170](https://github.com/Brad-Edwards/shifter/commit/9b4517081c40ce31f488a612f0276915d9dcc297))
* **mission-control:** enforce per-file agent upload limit before transfer ([e624add](https://github.com/Brad-Edwards/shifter/commit/e624addf2e4f74ea2aab01a13a0ef6dd614209b3))
* **model-access:** define policy catalog and shared access contracts ([fadb418](https://github.com/Brad-Edwards/shifter/commit/fadb418d3846cbc16066a570029bb048c3667df8))
* **model-access:** enforce project sharing authority ([39c1337](https://github.com/Brad-Edwards/shifter/commit/39c1337f4a1402916f7f8445e5333290f78d4733))
* **model-access:** enforce required scenario/event model admission before launch (PLAT-202) ([7511688](https://github.com/Brad-Edwards/shifter/commit/75116884dad647addaa0b69fdcc67641080d27a8))
* **model-access:** enforce required scenario/event model admission before launch (PLAT-202) ([4cb00fa](https://github.com/Brad-Edwards/shifter/commit/4cb00fa9bb0c38a33f29dec720f628047db8ace7))
* **model-access:** persist sharing bindings and resolve overlapping policies ([201f097](https://github.com/Brad-Edwards/shifter/commit/201f097d7d2bcc5751c76c7bf6f5f3adf1f5b38e))
* **model-access:** persist sharing bindings and resolve overlapping policies ([551d671](https://github.com/Brad-Edwards/shifter/commit/551d671f5795b21cb5070bc3c244c98e56c6a571))
* **model-access:** project sharing authority changes ([9d004d8](https://github.com/Brad-Edwards/shifter/commit/9d004d8b47d847b4da5df0daa3d888371e0e98b5))
* parameterize gdc-bootstrap by environment for multi-tenant standup ([985f91e](https://github.com/Brad-Edwards/shifter/commit/985f91e806b7ea915ccb464adc324272addf32b2))
* parity-safe GCP range pause/resume for GDC VM Runtime and GCE ([557c699](https://github.com/Brad-Edwards/shifter/commit/557c699b25546c7d2eca8bc6bd3b64cae82dd792))
* parity-safe GCP range pause/resume for GDC VM Runtime and GCE ([144838e](https://github.com/Brad-Edwards/shifter/commit/144838e6ef6f0ded282593608694c732754cd54a))
* range-owned GCP Cloud NAT so none ranges have no NAT path (PLAT-238) ([fd7842e](https://github.com/Brad-Edwards/shifter/commit/fd7842e39c3a4fcc4f461698f8d76ea61ffc04aa))
* **range:** configurable warm pool for faster initial launch ([045d7e9](https://github.com/Brad-Edwards/shifter/commit/045d7e9c9eeb97a9e242b04a65c9e18b7ec675cb))
* **range:** configurable warm pool for faster initial launch ([#28](https://github.com/Brad-Edwards/shifter/issues/28)) ([5672618](https://github.com/Brad-Edwards/shifter/commit/567261837c5a6799cc8a86260e91ba5a1cb858f5))
* **range:** ship launchable smoke-linux pack + RAES-aware post-deploy smoke ([4e218af](https://github.com/Brad-Edwards/shifter/commit/4e218afcaa016b6332095ab0bb457a548725019a))
* realize pinned range egress on the AWS provisioner path (PLAT-238) ([b741e72](https://github.com/Brad-Edwards/shifter/commit/b741e72af63b14d69dea9c3ca3b14e8f2147c77d))
* user lifecycle administration (suspend/reset/ownership transfer) ([5764ad4](https://github.com/Brad-Edwards/shifter/commit/5764ad4ebdb1a4caa36e82a4b392d0c70e9a183c))
* user lifecycle administration (suspend/reset/ownership transfer) ([d96706a](https://github.com/Brad-Edwards/shifter/commit/d96706aa127cc6f77a474ce35c71a7c268a85a3d))
* workspace egress policy control in the SPA admin surface (PLAT-238) ([b5f3ede](https://github.com/Brad-Edwards/shifter/commit/b5f3ede4378ad2eb1687c76fa4819bc21ba4c6b3))
* workspace network egress policy backend spine (PLAT-238) ([a97dcd8](https://github.com/Brad-Edwards/shifter/commit/a97dcd8fb4aa7929c28517323a11f6a0ce60b3ea))
* workspace-level network egress policy (zero-egress) on AWS and GCP ([518fdbd](https://github.com/Brad-Edwards/shifter/commit/518fdbd685bdcd4a67cd6e45a43767b32881a209))
* **workspaces:** add member invitations and onboarding ([810564a](https://github.com/Brad-Edwards/shifter/commit/810564a61edc79bf76ba4ceed93ebd21b69a8670))
* **workspaces:** add member invitations and onboarding ([e0a4a57](https://github.com/Brad-Edwards/shifter/commit/e0a4a574fa4202fc4687980c5a7c3b22a5ee7d83))
* **workspaces:** add per-workspace resource quotas and usage ([36a06b7](https://github.com/Brad-Edwards/shifter/commit/36a06b780004dc2318f8d36d99cb8a0da281dd4c))
* **workspaces:** add per-workspace resource quotas and usage ([ce594fd](https://github.com/Brad-Edwards/shifter/commit/ce594fd5eafd55223fb8b7d4421c666ceb2ae739))


### Bug Fixes

* address pre-merge review — undeployable NAT, deny-all firewall, agent URL, token-auth contract (PLAT-238) ([f40bf02](https://github.com/Brad-Edwards/shifter/commit/f40bf02a5bebcdb709d6c974d81c212fa06096d1))
* address review cycle 2 — move-chain, fail-closed egress, model layering, session-only auth (PLAT-238) ([53e9d19](https://github.com/Brad-Edwards/shifter/commit/53e9d195d4040637dc47164d2c58d1439b32dc2e))
* **adr-guard:** address Sonar documentation findings ([613f365](https://github.com/Brad-Edwards/shifter/commit/613f365ac037a4b23481e3f87d1b841dec9ca33f))
* **adr-guard:** address Sonar documentation findings ([245ec34](https://github.com/Brad-Edwards/shifter/commit/245ec34d0b38b7252f52f3f3210cf92301eaf6b6))
* **adr-guard:** clarify ingress schema field ([e504650](https://github.com/Brad-Edwards/shifter/commit/e504650a31001a20e154e08a7c59dfcfff6dacab))
* **adr-guard:** resolve new-code Sonar findings ([e85bafa](https://github.com/Brad-Edwards/shifter/commit/e85bafa93c1aa352dd207205b4df5bb79c792a81))
* **adr-guard:** resolve new-code Sonar findings ([237e378](https://github.com/Brad-Edwards/shifter/commit/237e3787c832c073a054255d82fb051d0436caa1))
* **api:** address CI Postgres-lane + SonarCloud findings on retry-safe operations ([aef8c4b](https://github.com/Brad-Edwards/shifter/commit/aef8c4b6ef5d1897bc3dbda83adfd6740fcaaa29))
* **api:** align public contract with runtime boundaries ([ee6639c](https://github.com/Brad-Edwards/shifter/commit/ee6639ca9ab5a2c772860a482eab2213fc42bd4e))
* **api:** align published contract with runtime authority ([33d15c7](https://github.com/Brad-Edwards/shifter/commit/33d15c73ad4ece7de4205f00d7ba2f10436980bc))
* **api:** align scoreboard runtime with published contract ([bfa34eb](https://github.com/Brad-Edwards/shifter/commit/bfa34eb8c329866466bc8975c254b96899db54bf))
* **api:** resolve SonarCloud findings in retry-safe launch mixin and cleanup projection ([1e98a9a](https://github.com/Brad-Edwards/shifter/commit/1e98a9aec0863481d54bb9fa2a85d414d75a5ee1))
* **api:** split range history projection ([7fe8066](https://github.com/Brad-Edwards/shifter/commit/7fe806686476ed35377a5094524b3ca789e700b6))
* **bootstrap:** stop deploy facade from clobbering distinct module main entrypoints ([9dcc016](https://github.com/Brad-Edwards/shifter/commit/9dcc016cc5e7f8bcb301fe034b27fcabf2fc7a94))
* CI quality gate — mypy auth typing, ruff format, provisioner operation-dict assertion (PLAT-238) ([4808b41](https://github.com/Brad-Edwards/shifter/commit/4808b41cef944a35f51aa38ebefd28b6e5ba35a0))
* clarify gcp resource metadata handling ([ec14d31](https://github.com/Brad-Edwards/shifter/commit/ec14d315789fff24eca9782a233b852a931b9e05))
* clear artifact preparation quality findings ([4cb947d](https://github.com/Brad-Edwards/shifter/commit/4cb947d6bd43b134425b31fe6b192358b53da707))
* clear remaining SonarCloud new-code smells (docstrings, type hint, S5778) ([e5a170a](https://github.com/Brad-Edwards/shifter/commit/e5a170a5ed847cd7a74eee0d6570151f247fe2b8))
* close cyberscript GCE egress gap + RAES router leak; test-quality forwarding (PLAT-238) ([fdcd8d4](https://github.com/Brad-Edwards/shifter/commit/fdcd8d4a5c47a63ae7f1dd2812a1ae90d199df35))
* **cms:** align retry-safe launch with post-PLAT-202 create_range_dispatch ([64bb600](https://github.com/Brad-Edwards/shifter/commit/64bb60057fecbc8a53d8e4307a921c24295d7540))
* complete artifact preparation quality gates ([ab9e00b](https://github.com/Brad-Edwards/shifter/commit/ab9e00bfcc539d5663b5c415b0a6fdc25c0ebe90))
* **ctf:** address validator quality findings ([eff78a4](https://github.com/Brad-Edwards/shifter/commit/eff78a4d09a7c2303a47a796ab5f240271996bf6))
* **ctf:** address validator quality findings ([cd3e16a](https://github.com/Brad-Edwards/shifter/commit/cd3e16a2cfcd888d3997f8c0340be2b27002d28e))
* **ctf:** clear remaining SonarCloud new-code findings (type hints, re-export imports) ([4583bd4](https://github.com/Brad-Edwards/shifter/commit/4583bd48ac1efb940f2b076304a69d4248a607c8))
* **ctf:** close participant readiness safety gaps ([29fa2f3](https://github.com/Brad-Edwards/shifter/commit/29fa2f38c084315e315935de3b168bb3a1981cec))
* **ctf:** close participant readiness safety gaps ([69abe12](https://github.com/Brad-Edwards/shifter/commit/69abe125ab3f3070c91fcae2945c38662cbb4bf9))
* **ctf:** close participant readiness safety gaps ([7eecf96](https://github.com/Brad-Edwards/shifter/commit/7eecf96379df59b2f2db3c40089f5a0755850070))
* **ctf:** keep staff-assign role request field backward-compatible (ADR-040) ([82e830d](https://github.com/Brad-Edwards/shifter/commit/82e830d0cdd0a1c9dcef5ec6dbf269e6a0686f26))
* **ctf:** lock receipt range without nullable join ([1117dd4](https://github.com/Brad-Edwards/shifter/commit/1117dd48152a4dd9581dc4a11a7be0927d19440a))
* **ctf:** narrow parsed URL type ([ffde5d3](https://github.com/Brad-Edwards/shifter/commit/ffde5d3509bf42c29bf2741b377b6a453fe7e719))
* **ctf:** narrow parsed URL type ([5840905](https://github.com/Brad-Edwards/shifter/commit/5840905e4d57a4afacd74d7db001dc14bcbe6fa8))
* **ctf:** precompute challenge filter URLs in the view (Web:MaxLineLengthCheck) ([800f1be](https://github.com/Brad-Edwards/shifter/commit/800f1bec0485c08cb494560b220c5a2bf2de8756))
* **ctf:** refresh submission API contract ([e28fdbf](https://github.com/Brad-Edwards/shifter/commit/e28fdbfee7d677eaf435ea045d21a739a4e0fb04))
* **ctf:** renumber shared audit entity_type migration to 0015 after dev merge ([984fc05](https://github.com/Brad-Edwards/shifter/commit/984fc0540b37a6a53ee6e00ea6c2a902584982cc))
* **ctf:** resolve SonarCloud new-code findings (type hints, file split, audit atomicity) ([4ddbfe0](https://github.com/Brad-Edwards/shifter/commit/4ddbfe0006dbccef946aa29eaad88201d06f1dcd))
* **ctf:** service-boundary authz asserts, stale-role revocation, and file splits ([b573353](https://github.com/Brad-Edwards/shifter/commit/b573353105e5eb54b6a11a4cb1c71abce76eb374))
* **ctf:** trim _crud.py docstrings under the 500-line new-code limit ([6db33c4](https://github.com/Brad-Edwards/shifter/commit/6db33c4c45db3b0537fbc66b6ab2aa84fb3bd943))
* enforce participant readiness evidence ([84d7f9f](https://github.com/Brad-Edwards/shifter/commit/84d7f9f6b175f5e45a3a849d8a802af317bb5b1c))
* enforce participant readiness evidence ([4209e94](https://github.com/Brad-Edwards/shifter/commit/4209e946051efb724caf321268e0c73feedc57da))
* **frontend:** redirect legacy settings route ([711245d](https://github.com/Brad-Edwards/shifter/commit/711245df8cf823cc20e5754573a9d51caefd4604))
* gate GCS usage-log delivery for Domain Restricted Sharing orgs ([435c9ef](https://github.com/Brad-Edwards/shifter/commit/435c9ef380d240c717aef63e397d0dada737c23a))
* **gcp:** add platform-network Private Google Access DNS for googleapis ([3114d68](https://github.com/Brad-Edwards/shifter/commit/3114d680280faf49707f0d3ed87554927a058fe2))
* **gcp:** add platform-network Private Google Access DNS for googleapis ([8c853fa](https://github.com/Brad-Edwards/shifter/commit/8c853facf1c21ee26eb8017311b52616dbb26c6d))
* **gcp:** add the missing Workload Identity annotation for provisioner-launcher ([3bc7234](https://github.com/Brad-Edwards/shifter/commit/3bc7234fa5858cb63807656b09331785c4d1c999))
* **gcp:** address bootstrap CI and Sonar findings ([09118d7](https://github.com/Brad-Edwards/shifter/commit/09118d7a4686b05e6b5691b9930716cee7c6d3c0))
* **gcp:** allow egress to the GKE metadata server for Workload Identity ([5ec586e](https://github.com/Brad-Edwards/shifter/commit/5ec586e604072ee8d045adb3aafce02fb217da96))
* **gcp:** allow provisioner-launcher egress to the GKE control-plane CIDR ([8e21f89](https://github.com/Brad-Edwards/shifter/commit/8e21f898ac0e4e77dd9258850461872e0952daf6))
* **gcp:** allow shifter-jobs egress to Cloud SQL for range provisioning ([ef015d2](https://github.com/Brad-Edwards/shifter/commit/ef015d2672934b18d0de68944bcdb12bd3dc8486))
* **gcp:** allow the Google APIs backend range on platform/jobs egress ([f45b1ab](https://github.com/Brad-Edwards/shifter/commit/f45b1ab7bfb8e76609644b32d397ccbd89db1488))
* **gcp:** close range-cell egress release-blockers under ADR-056 ([27cd255](https://github.com/Brad-Edwards/shifter/commit/27cd255ca3a6dec132d3711b380f1e32946a052a))
* **gcp:** close range-cell egress release-blockers under ADR-056 ([84217da](https://github.com/Brad-Edwards/shifter/commit/84217dadb1fdbd480c72b09dd5e6b19d1468f3f9))
* **gcp:** deploy worker-operation-result-applier (was orphaned manifest) ([a5a536c](https://github.com/Brad-Edwards/shifter/commit/a5a536c088e0c27ace2a96ec48658696e703744c))
* **gcp:** disable NodeLocal DNSCache (incompatible with Dataplane V2) ([08865ff](https://github.com/Brad-Edwards/shifter/commit/08865ff40701b540f11f63c80b863c3f748cd10d))
* **gcp:** disable NodeLocal DNSCache (incompatible with Dataplane V2) ([bf33891](https://github.com/Brad-Edwards/shifter/commit/bf3389132ce1331987d1703e883b6104e88f00e0))
* **gcp:** docstring the containment-signal delivery helper (Sonar) ([2e6a5b9](https://github.com/Brad-Edwards/shifter/commit/2e6a5b9fc384d8e17b593e5b0606b71b5a14e58b))
* **gcp:** drop the inert 34.126.0.0/18 backend range (red herring) ([a92846d](https://github.com/Brad-Edwards/shifter/commit/a92846d88f7bbf0428cd3a69796bdbd52ae2c530))
* **gcp:** enable Cloud NAT dynamic port allocation for the platform VPC ([b44cfa7](https://github.com/Brad-Edwards/shifter/commit/b44cfa72d7475f6aca59453e628d484a00bd8f4f))
* **gcp:** enable Cloud NAT dynamic port allocation for the platform VPC ([7754782](https://github.com/Brad-Edwards/shifter/commit/7754782ae996e83f215ed57a872c1f124c502e7a))
* **gcp:** enable workload identity for gcp-dev platform pods ([c26362a](https://github.com/Brad-Edwards/shifter/commit/c26362a344e80393a1b81fbba1947f9cff55d312))
* **gcp:** enforce control-plane NetworkPolicy via GKE Dataplane V2 ([4d4b726](https://github.com/Brad-Edwards/shifter/commit/4d4b7268f23d01567700d99af7b4851abace54a0))
* **gcp:** enforce control-plane NetworkPolicy via GKE Dataplane V2 ([07ff61f](https://github.com/Brad-Edwards/shifter/commit/07ff61f589119f0f496d41ab31f711849778c50b))
* **gcp:** fix fresh GCE-backend deploy gaps (GDC baremetal-gcr gate + virtctl) ([218faf1](https://github.com/Brad-Edwards/shifter/commit/218faf1a5fcdef7a631c6ff32e345d245793915d))
* **gcp:** gate GDC baremetal-gcr image-reader off the default GCE apply ([3c2d810](https://github.com/Brad-Edwards/shifter/commit/3c2d81013d690c44f6e53c19e6e2442ccd4145fd))
* **gcp:** grant the CI deploy SA the platform-core roles it needs ([a35a5fb](https://github.com/Brad-Edwards/shifter/commit/a35a5fb429e239d535f364de20c1751e6c4da9e6))
* **gcp:** grant the CI deploy SA the platform-core roles it needs (enumerated) ([24d2497](https://github.com/Brad-Edwards/shifter/commit/24d2497c10a55159356fe3496de3684a5987d16e))
* **gcp:** harden the cluster default node pool config (Shielded secure boot) ([f6328bb](https://github.com/Brad-Edwards/shifter/commit/f6328bb27ab93da270b7151c781f38b37251265c))
* **gcp:** keep range model under the S104 line ceiling ([47e06c1](https://github.com/Brad-Edwards/shifter/commit/47e06c16797a7450068a7be65a9f73c905cb81b9))
* **gcp:** make CI OIDC/WIF a foundational root so gcp-dev destroy+rebuild cycles ([728403d](https://github.com/Brad-Edwards/shifter/commit/728403d141509587e2ac811f95b33430cf09c258))
* **gcp:** make CI OIDC/WIF a foundational root so gcp-dev destroy+rebuild cycles ([b84ff7c](https://github.com/Brad-Edwards/shifter/commit/b84ff7cfa39a744fd3dceb132b86fdb647d4e9b8))
* **gcp:** make range guests reachable for setup + probe ([19cefe0](https://github.com/Brad-Edwards/shifter/commit/19cefe0ae4196176137833f1d671c3b476daca62))
* **gcp:** pin the GKE cluster default node pool to the dedicated node SA ([6fd9463](https://github.com/Brad-Edwards/shifter/commit/6fd946352ec22c8bf373a04b52f738f9f6c6a9f4))
* **gcp:** pin the GKE cluster default node pool to the dedicated node SA ([8a5b504](https://github.com/Brad-Edwards/shifter/commit/8a5b5044dcbed66c26af2bbc2cacb3abdd21353a))
* **gcp:** pin virtctl digest and gate it off the default GCE provisioner image ([afea747](https://github.com/Brad-Edwards/shifter/commit/afea7478b8ff0447205d7d3240108eeb6168362c))
* **gcp:** resolve gcp-dev-destroy state addresses by suffix ([e55a65e](https://github.com/Brad-Edwards/shifter/commit/e55a65ecb11ebb1fdf2c277bfcb015dc0d29c1ea))
* **gcp:** resolve gcp-dev-destroy state addresses by suffix (fix skipped guards) ([2da283e](https://github.com/Brad-Edwards/shifter/commit/2da283ec471dd16250d85e23edc4641a0701487b))
* **gcp:** scope the deploy SA's serviceAccountUser to the GKE node SA ([b1d944d](https://github.com/Brad-Edwards/shifter/commit/b1d944d1bc9a0006ca502bf9408501c4577be500))
* **gcp:** separate CI identities ([f6f0b7b](https://github.com/Brad-Edwards/shifter/commit/f6f0b7b340cd3dd81f9de8b3bd49368ad5e2e774))
* **gcp:** separate CI identities ([d1a1146](https://github.com/Brad-Edwards/shifter/commit/d1a11466d755b34df4f6a26c0e0d587ec26308d5))
* **gcp:** support immutable GitHub deployment identities ([abfd5e9](https://github.com/Brad-Edwards/shifter/commit/abfd5e9b45480d9bd6c2d9f32768751001c0c985))
* **gcp:** type hints + keep range model within line budget (Sonar [#2037](https://github.com/Brad-Edwards/shifter/issues/2037)) ([1dc3f89](https://github.com/Brad-Edwards/shifter/commit/1dc3f89b389bb99f908491251e5c0a3ba988c47f))
* ignore create-only default-pool node_config drift on GKE cluster ([f39a905](https://github.com/Brad-Edwards/shifter/commit/f39a9056f2f0dad917a3fb2a2e8307522db9e46a))
* make network firewall teardown ordering-safe (rule-group dereference + inspection route toggle) ([f722188](https://github.com/Brad-Edwards/shifter/commit/f7221883b0c43b837d5eda5608b5b73ec3b6d284))
* **model-access:** regenerate /api/v1 contract for CTFEvent.model_demand ([1c20b63](https://github.com/Brad-Edwards/shifter/commit/1c20b6360e257070eec044f1365aaf8426a0e18f))
* **model-access:** regenerate SPA openapi types for CTFEvent.model_demand ([f8ecdf6](https://github.com/Brad-Edwards/shifter/commit/f8ecdf610f769972357e0a60dd657d2f23142c22))
* **model-access:** resolve remaining quality findings ([23521bf](https://github.com/Brad-Edwards/shifter/commit/23521bfc318a4fe0d1e16de1b7faeeb6c635ff6c))
* **model-access:** resolve SonarCloud quality-gate findings ([ac84696](https://github.com/Brad-Edwards/shifter/commit/ac84696924103d7344f5dc67ddbf5a36cab05097))
* **model-access:** satisfy PostgreSQL and quality gates ([f34e4d7](https://github.com/Brad-Edwards/shifter/commit/f34e4d7608d6d0d60465158b8688f096327fa112))
* **model-access:** satisfy Sonar line-length rule ([e9ec4ec](https://github.com/Brad-Edwards/shifter/commit/e9ec4ec610db679f9367515686a1337b84cf57ed))
* **ngfw:** drop dead popup.closed===undefined check (javascript:S3403) ([9323209](https://github.com/Brad-Edwards/shifter/commit/93232094e6149dc3970910dc60e9a5b31eff94c7))
* order-safe Network Firewall teardown for range rule groups and portal route toggle ([bbd41fe](https://github.com/Brad-Edwards/shifter/commit/bbd41fe6116193472104fce10943b7154afcd2f5))
* **packer:** kali GCE guest boots + sshd binds — static networkd config ([bee2443](https://github.com/Brad-Edwards/shifter/commit/bee2443a4fb504cd1ca615e63ac08b0152b35ffe))
* **packer:** kali guest boots on GCE — remove NetworkManager dual-stack ([0496561](https://github.com/Brad-Edwards/shifter/commit/049656157922c8411ecb6f4b1812726b838382c7))
* parametrize dict generics for SonarCloud new-code gate ([#1287](https://github.com/Brad-Edwards/shifter/issues/1287)) ([11fd1de](https://github.com/Brad-Edwards/shifter/commit/11fd1de573b700087b9732d3f40aca5bd6e4da09))
* postgres FOR UPDATE join + SonarCloud new-code findings ([19c0f15](https://github.com/Brad-Edwards/shifter/commit/19c0f153aee41d80c62eb004bfa48f1963040e7f))
* **provisioner:** drop invalid provider= kwarg to build_guest_execution_context ([483e7c0](https://github.com/Brad-Edwards/shifter/commit/483e7c0dd8278aa2912d7da786dde912bfda3b06))
* **provisioner:** keep compensation diagnostics bounded and file under size gate ([42284ca](https://github.com/Brad-Edwards/shifter/commit/42284ca216f16cd8eb055737e52bf2f00894fd40))
* **provisioner:** log credential-channel failure type without leaking secrets ([c6cd210](https://github.com/Brad-Edwards/shifter/commit/c6cd210c3c7451bf91022f58006e79e70b1f829e))
* **provisioner:** route failed-provision compensation through canonical teardown ([e3ce40d](https://github.com/Brad-Edwards/shifter/commit/e3ce40dd1cc0c6341aa1060cf5f98dd938f20d88))
* **provisioner:** route failed-provision compensation through canonical teardown ([cfbe0cd](https://github.com/Brad-Edwards/shifter/commit/cfbe0cdeac125d034b5140bc5d2baea1b67a742b))
* **provisioner:** surface the real cause of credential-channel failures ([a741e85](https://github.com/Brad-Edwards/shifter/commit/a741e856ba0a50177c42d3738581cf8efd841ba7))
* **quality:** extract inline template JS to static files, split long JS/templates, bundle tags-builder params; document verified SonarCloud false-positives ([c3b01ee](https://github.com/Brad-Edwards/shifter/commit/c3b01ee538ffc02aca52b9e40a27833b2e53e0a2))
* **quality:** resolve ~400 SonarCloud maintainability findings (type hints, docstrings, static methods, comment placement, complexity) ([811713f](https://github.com/Brad-Edwards/shifter/commit/811713f18df4985566ab7dfd2370b67f6d7f0175))
* **quality:** resolve all open SonarCloud findings across the repo ([a3cd24a](https://github.com/Brad-Edwards/shifter/commit/a3cd24a821b584e000d1bcacbaa871bacb1ebe7e))
* **quality:** resolve all open SonarCloud findings across the repo ([9a069f9](https://github.com/Brad-Edwards/shifter/commit/9a069f9a4b4b4084c0cefe7c0dc61036513c8e1d))
* **quality:** resolve SonarCloud vulnerabilities, bugs, and critical findings (code smells tracked in [#2185](https://github.com/Brad-Edwards/shifter/issues/2185)) ([25f22ed](https://github.com/Brad-Edwards/shifter/commit/25f22ed06a42edc6588d45fd1ac6f64ae537440a))
* **raes:** scope image-registry projection by authored source name ([0bb8530](https://github.com/Brad-Edwards/shifter/commit/0bb8530d8df557a0692a4305c332cacd1bb6dfd8))
* re-parent 0055 egress-mode migration onto 0054 placement-zone leaf (PLAT-238) ([879a570](https://github.com/Brad-Edwards/shifter/commit/879a570643d282485a12d7bdcc426076ea86c1ae))
* resolve API contract drift and SonarCloud new-code smells (PLAT-237) ([845defa](https://github.com/Brad-Edwards/shifter/commit/845defa7d74f9229e8c4f192319beb42120d17db))
* resolve bootstrap SAST B404 on type-only subprocess import ([#1287](https://github.com/Brad-Edwards/shifter/issues/1287)) ([e758373](https://github.com/Brad-Edwards/shifter/commit/e758373752c35586ca1cbdbb1fac47bcb8b118c8))
* resolve remaining preparation quality findings ([1c95d7a](https://github.com/Brad-Edwards/shifter/commit/1c95d7ac4524c13cf657fbe2f4138bfac354f6e9))
* return authored range-scope error messages (CodeQL py/stack-trace-exposure) ([b36d668](https://github.com/Brad-Edwards/shifter/commit/b36d6686dd9e1cfa8c8680748ade3880e67ff3d1))
* **runner:** standardize isolated runner network placement ([43e6b79](https://github.com/Brad-Edwards/shifter/commit/43e6b79fc44812fe22f6b8283f7274404e7ccbd7))
* **runner:** standardize isolated runner network placement ([bab316e](https://github.com/Brad-Edwards/shifter/commit/bab316e1b7621121a48595648d0922a65af25dc3))
* sanitize request id in range-scope logs (CodeQL py/log-injection) ([6dcd083](https://github.com/Brad-Edwards/shifter/commit/6dcd08378e3c4fb1df2ce1cf37dec04499cf2645))
* satisfy cutover API and quality gates ([3482e15](https://github.com/Brad-Edwards/shifter/commit/3482e1541aa518b00ae6c54b78f409e02a7d356f))
* **security:** validate same-origin redirect targets in extracted JS and stop exception-detail exposure in auth session view (CodeQL) ([540e793](https://github.com/Brad-Edwards/shifter/commit/540e7932466b5d3c1fb20557e7052214417d4ab9))
* **smoke-linux:** re-bind pack digest after concepts.md em-dash fix ([ffed60e](https://github.com/Brad-Edwards/shifter/commit/ffed60ef50ad4d944116f79af0f68c81f09212ad))
* **smoke:** make post-deploy smoke work with RAES-native ranges ([dd717eb](https://github.com/Brad-Edwards/shifter/commit/dd717eb9fa54a9b54b36af2065caa6be37008bad))
* **test:** satisfy gce range preconditions via the process boundary, not a first-party patch ([03d3330](https://github.com/Brad-Edwards/shifter/commit/03d333064cac233ff17df37056e494b41a2f9c42))
* **warm-pool:** clear remaining Sonar new-code findings (cast replace(), re-export __all__, test globals) ([14da16d](https://github.com/Brad-Edwards/shifter/commit/14da16db016788be3fbe5ee8f78dc5209d50c2fa))
* **warm-pool:** resolve Sonar quality-gate findings and claim-consistency constraint ([7cf9b9c](https://github.com/Brad-Edwards/shifter/commit/7cf9b9ce749e983c40327c49cc35db0115e51766))
* **workspaces:** clear remaining invitation quality findings ([6d6879c](https://github.com/Brad-Edwards/shifter/commit/6d6879c91610ed898865a1b7543a6865bcfc3427))
* **workspaces:** resolve invitation quality findings ([6a60f3c](https://github.com/Brad-Edwards/shifter/commit/6a60f3c13cb8026ab8446bac991334c52f924469))

## [3.103.0] - 2026-07-20

### Security

- Risk register UI and API now require membership in a configured Cognito group (`RISK_REGISTER_ALLOWED_COGNITO_GROUPS`); unauthorized authenticated users receive HTTP 403. (#151)
- The portal runtime now authenticates to its PostgreSQL database with short-lived RDS IAM tokens instead of a stored password: the running web and worker processes hold no database password (they connect as a dedicated `rds_iam` `portal_runtime` user over SSL), while the master password user is kept only for schema ownership and migrations. Django `SECRET_KEY` rotation is now zero-downtime via `SECRET_KEY_FALLBACKS`, so a rotation no longer invalidates active sessions (#159). (#159)
- Standardize deploy-managed AWS IAM role and instance profile names under the `shifter-*` prefix via an `iam_name_prefix` seam, and narrow GitHub Actions OIDC `iam_scoped` permissions to that namespace with a managed-policy attachment allowlist (#253). (#253)
- SSHExecutor no longer logs raw PAN-OS command text or raw/cleaned device output, closing a clear-text-credentials-in-logs path (CWE-532). Command and output visibility is now byte-count only, mirroring the NGFWExecutor discipline. (#418)
- CTF participant magic links now remain reusable through the event end instead of expiring after the default short TTL while the CTF is still active, with `MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS` available for operators who need a stricter event-link ceiling. (#556)
- Portal settings now fail closed when production runtime config is missing for allowed hosts, database, OIDC, field encryption, or email backend selection; dev/test/build defaults remain explicit posture-gated exceptions. (#558)
- ADR guard now blocks hardcoded CTF flag literals (`FLAG{...}`) in Mission Control runtime code (`no-mission-control-flag-literals`, ADR-004-R16), keeping challenge answers in the CTF/CTFd content domain rather than the application path. (#560)
- Remove hardcoded `YOUR_EMAIL@example.com` budget-alert placeholders from AWS core Terraform; alert recipients now flow through per-environment `budget_alert_email` deploy secrets (`TF_VARS_*_CORE`) and gitignored `local.auto.tfvars`. Add ADR guard checks that block operational Terraform placeholders and `AdministratorAccess` on the GitHub Actions OIDC role from re-entering the repo. (#562)
- **Mission Control upload cancel now keeps browser-session CSRF protection intact.** Agent upload cancellation requires a signed current-upload token matched to the session lock, and unload cleanup sends a CSRF-bearing form beacon instead of relying on a CSRF-exempt endpoint. (#565)
- Hardened the GCP VM-Series NGFW path: NGFW attachment-state resolution no longer misclassifies a GCP firewall as AWS when its explicit `cloud_provider` is absent (a namespaced KubeVirt `data_attachment_id` like `<ns>/<vm>:eth1` is now recognised as GCP), and the bootstrap GCS object URL and NGFW management / next-hop IPs are fingerprinted in logs instead of being emitted in clear text. (#613)
- Added platform-wide scoped API token authentication (PLAT-102). Programmatic clients can now authenticate with `Authorization: Bearer shf_…` tokens that carry explicit `<resource>:<operation>` scopes; browser/SPA clients continue to use session cookies. Tokens are generated and revoked from the Django admin, the raw token is shown exactly once, and only a non-reversible verifier is stored. The risk-register API (`/api/v1`) now accepts these scoped tokens (`risk:read` / `risk:write`) end-to-end. The legacy risk-register `X-API-Key` is deprecated (retirement tracked in #1124). (#677)
- Hardened filesystem and subprocess call sites flagged by SonarCloud's taint analysis (`pythonsecurity:S8707` / `S8705`). Operator- and CLI-supplied paths in the installation config loaders, the layer-import checker, and the Terraform workspace stager are now normalised (and, where a workspace root exists, containment-checked) before any filesystem access, and the bootstrap deploy script validates argv tokens (rejecting NUL bytes) before invoking subprocess. (#779)
- **Restored portal east-west segmentation so the CTFd instance can no longer reach Django or the Guacamole token API directly.** The inspection-firewall ingress fix had widened the Django (`8000`) and Guacamole client (`8080`) security groups to the whole public-subnet CIDR, where the standalone CTFd instance and the NAT also live, letting CTFd open TCP connections straight to those services and bypass the ALB, WAF, and `/admin` deny. CTFd now lives in a dedicated public-workload subnet tier, and the inspected ALB→target CIDR rules are scoped to an ALB-only `alb_ingress_subnet_cidrs` output (AWS Network Firewall breaks security-group referencing across the routed middlebox, so the CIDR rule is required when inspection is enabled). A new `check-portal-target-sg-sources` guard (pre-commit + CI) prevents the target-service SGs from being re-widened back to the public tier. (#933)
- Hardened portal auth and audit trust: dev-login admission is now bound to the direct peer address (loopback/admin CIDRs) instead of the spoofable Host header, audit source IPs are resolved from the trusted rightmost X-Forwarded-For hop rather than the client-controlled leftmost value, and every self-service `user_type` change now writes a fail-closed, reviewable audit row for the resulting CTF group membership. (#937)
- Enabled AUTH and in-transit encryption on the AWS ElastiCache Redis channel-layer backbone. The portal replication group now generates an AUTH token stored in Secrets Manager under the portal CMK and requires TLS; the portal hydrates it at startup and verifies the server certificate against the system trust store (AWS public CA) via the new `REDIS_CA_MODE` trust-mode seam, preserving GCP Memorystore's private-CA fail-closed behaviour. The dev-only single-node path documents its retained plaintext posture as a threat-model acceptance. (#938)
- **Guacamole session token URLs are no longer retained at rest after delivery.** The asynchronous bootstrap flow now returns the signed Guacamole URL exactly once and clears the token material from the database row in the same transaction, never persists a URL for a request that finished after its TTL expired, and runs a dedicated scheduled service that prunes expired bootstrap rows in bounded batches. A database read can no longer disclose a live RDP/SSH session URL. (#939)
- Enforced CTF participant-only access server-side on the Mission Control range lifecycle endpoints (launch/cancel/destroy/pause/resume), so a participant-only account can no longer drive these verbs against its own event range by calling the API directly. Previously the restriction was applied only in the UI. (#944)
- Stop leaking raw exception detail in CMS experiment AJAX error responses (CodeQL `py/stack-trace-exposure`). The two JSON error sinks in `shifter/shifter_platform/cms/experiments/views.py` — `scenario_instances` and the script-upload initiation path — previously returned `str(exc)` in the response body. Because `ScriptUploadError` is frequently raised from inner exceptions (`raise ScriptUploadError(f"... {e}") from e`), that text could carry internal detail to the client. Both sinks now log the full exception server-side via `logger.exception` and return a classified, authored message selected by `shared.errors.classify_user_message`, matching the error-envelope idiom already used across `mission_control/views`. (#999)
- Hardened source and deployment guardrails for generated runtime artifacts, Terraform secret-bearing inputs, and immutable GCP image references. (#1001)
- Enabled at-rest encryption on the AWS portal Redis (ElastiCache) replication group under a dedicated customer-managed KMS key, closing the data-on-disk and snapshot gap left when #938 enabled AUTH and in-transit encryption. The `CKV_AWS_29` / `CKV_AWS_191` Checkov deferrals and the matching ADR-004-R11 exception clause are removed. (#1059)
- Moved the CTF invite magic-link token off the URL query string. Invite emails now carry the token in the URL fragment (`#token=`), and a CSRF-protected token-exchange endpoint consumes it, keeping the credential out of access logs, the request formatter, and `Referer` headers (SonarCloud S8435). (#1088)
- Organizer-authored CTF email templates are now rendered with a placeholder-only substitution over an explicit per-notification-type scalar allowlist instead of the Django template engine, closing a server-side template injection / information-exposure path (CWE-1336). Custom bodies may only use simple `{{ name }}` placeholders; tags, comments, filters, and attribute traversal are rejected at write time and ignored (failing closed to the default template) at send time. (#1095)
- Commercial self-serve ranges can run in an explicit zero-egress posture (`settings.range_egress.mode: none`) where participant subnet route tables have no `0.0.0.0/0` route to Network Firewall, NAT, or the internet. Existing event allowlist behavior is unchanged (ADR-026). (#1171)
- Close the range DNS exfil/C2 channel by removing public-recursive `8.8.8.8:53` Network Firewall egress and enforcing split-horizon DNS via Route 53 Resolver DNS Firewall plus VPC DHCP pointing at AmazonProvidedDNS. (#1172)
- Hardened the `run_manage_command` MCP ops tool against remote shell injection (CWE-78): Django management commands are now parsed into structured argv and every token is validated against a strict allowlist that rejects shell-control syntax before the fixed `docker exec … manage.py …` invocation is rendered, closing the gap where only the first token was checked and the raw remainder reached the remote `AWS-RunShellScript` shell. (#1176)
- Restricted creation of privileged provisioner Jobs in the `shifter-jobs` GKE namespace. A new `ValidatingAdmissionPolicy` denies any Job that runs as the `provisioner` service account unless it mirrors the full canonical task-runner contract: submitted by the `workers` service account, a single `pulumi-provisioner` container on the pinned `ENGINE_TASK_IMAGE`, no entrypoint (`command`) override, a `range`/`ngfw` command family, no `envFrom`, `emptyDir`-only volumes, the read-only/non-root/drop-`ALL` security context, and `restartPolicy: Never`. This closes a privilege-escalation path where a compromised platform token could submit a Job running with the provisioner's Workload Identity. The policy ships identically in both the Helm chart and the static `platform/k8s/gcp/base` manifests. (#1177)
- Removed an over-broad, unused SSM Parameter Store grant from the shared range guest instance role. The `ssm-dc-config` policy allowed `ssm:PutParameter`/`GetParameter`/`DeleteParameter` on `parameter/shifter/*/range/*` — wildcarded across every environment and range — so any range guest could read or modify every other range's credential namespace. Range guests never use their instance role for Parameter Store (all range SSM access is brokered by the engine provisioner via Run Command), so the grant was dead privilege. A new `check-tf-iam-ssm-range-scope` guardrail (ADR-004-R17) blocks reintroduction of cross-range/cross-environment SSM grants on the range-instance role. (#1178)
- Scoped the engine-provisioner task role's SSM Run Command permissions to Shifter range guest instances. `ssm:SendCommand` and `ec2:RebootInstances` now require range-instance resource tags instead of targeting any EC2 instance in the account, so a provisioner compromise cannot run commands on portal or runner instances. (#1179)
- Removed the Guacamole runtime credentials (`POSTGRESQL_PASSWORD`, `JSON_SECRET_KEY`) from the Helm chart contract so they can no longer be persisted into chart values or Helm release history. The `shifter` chart now references the `guacamole-runtime` Kubernetes Secret by name only; the Secret is created out of band by the deploy bootstrap (`kubectl apply` from the provider secret store), which remains the single runtime copy alongside Secret Manager. The chart's raw-payload `Secret` template and the deployment's checksum-over-secret annotation were removed, closing a latent secret-exposure path (#1180). (#1180)
- Agent upload finalization now installs the exact bytes CMS validated. Completion copies the validated staging object to a fresh, immutable install key via a provider conditional copy (S3 `CopySourceIfMatch` + `IfNoneMatch`, GCS source/destination generation preconditions) and persists only that key, closing a TOCTOU window where a still-valid presigned PUT URL could overwrite an upload after validation but before install. (#1181)
- Bounded the CPU cost of organizer-authored CTF regex flags, closing a regular-expression denial-of-service path (CWE-1333 / CWE-400) where a crafted pattern/input pair could pin a request worker. Regex flags are now rejected at creation time when over-long or uncompilable, participant submissions are length-capped before matching, and matching runs under a per-call timeout that fails closed (treated as an incorrect submission) rather than blocking the worker. Limits are tunable via `CTF_REGEX_FLAG_MAX_PATTERN_LENGTH`, `CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH`, and `CTF_REGEX_FLAG_MATCH_TIMEOUT_SECONDS`. (#1183)
- Replaced CTF participant magic-link access with isolated, temporary username/password accounts, dedicated login and password-change flows, deny-authoritative platform boundaries, credential reset delivery, and post-event anonymization. (#1206)
- Gated the GDC VM Runtime range backend for live-fire scenarios: normal Mission Control and CTF range provisioning now fails closed unless the approved GCE VM range-cell backend is selected, with a CMS service-boundary gate and a provisioner defense-in-depth denial. GDC VM Runtime is development/validation only (ADR-030). (#1348)
- Hardened CTF service logging against log injection (CWE-117 / CodeQL `py/log-injection`): participant email, challenge name, and event name are now routed through the canonical `safe_log_value` sanitizer instead of the weaker CR/LF-only `safe_log`, so attacker-influenced values can no longer forge or smuggle content into log lines. (#1498)
- Separated CTF Organizer authority from self-service identity data (REV1 S1). A self-mutable `custom:user_type` / profile claim can no longer grant or retain the `CTF Organizer` group (or any staff/superuser/provisioning authority); the self-service sync now reaches only the `CTF Participant` group. Organizer authority is granted exclusively from administrator-controlled sources: verified provider group claims mapped through the new `CTF_ORGANIZER_PROVIDER_GROUPS` allowlist (fail-closed when unset), or explicit local assignment via the Django admin. The provider group is authoritative for provider-derived authority, so a verified login revokes a provider-derived `CTF Organizer` membership once the administrator removes the user from the allowlisted group (provenance is tracked so explicit local assignments are never auto-revoked). A data migration revokes every existing self-service-derived `CTF Organizer` membership with a per-user audit trail; re-grant affected organizers through the provider group claim or the Django admin. (#1516)
- Scoped the GCP application workload identities (portal, workers, CTF scheduler, provisioner) off broad project-level IAM: Secret Manager access is now bound per named runtime secret and Cloud Storage access per named bucket, driven by a single canonical workload/resource matrix in the `portal/iam` module (ADR-008-R7). A repo-native Terraform guard (`scripts/check_tf_gcp_iam_resource_scope`, wired into pre-commit and CI) fails closed on any project-level Secret Manager payload/admin or Cloud Storage object-admin grant to a workload identity, and effective-permission tests assert each identity's required resource set. Two dynamic-secret grants that cannot yet be resource-scoped (portal guest-credential reads and the provisioner's per-range secret lifecycle) remain project-level as documented, expiring allowlist residuals; the dedicated range-secret project/broker boundary that removes them is tracked in #1586. (#1517)
- Isolate GCP provisioner Job and ephemeral Secret mutation behind a dedicated, durable launcher worker and least-privilege Kubernetes identity. (#1518)
- Established verifiable build and deployment provenance (ADR-037): third-party actions in cloud-credentialed workflows are commit-SHA pinned and enforced fail-closed by a new `workflow-action-sha-pinning` guard; every Docker base image is digest-pinned with a Dependabot-tracked refresh; downloaded CLIs (Terraform, Pulumi, kubeconform, kube-linter) are checksum-verified before use; the provisioner image installs Python dependencies from hash-pinned locks; release OCI images (portal, provisioner, guacd, guacamole-client) publish an SBOM and a GitHub OIDC-signed provenance attestation; and AWS ECS and GKE deployments verify that attestation against the exact `image@sha256` and the `Brad-Edwards/shifter` identity before rollout. (#1519)
- Added a staged, deny-by-default browser security policy baseline: a global Content-Security-Policy shipped in Report-Only via Django's native CSP middleware, explicit `Referrer-Policy: same-origin` and a `Permissions-Policy` capability denylist, and a bounded same-origin CSP violation report collector at `/security/csp-report/` that logs through the existing structured pipeline. Front-end dependencies previously loaded from public package CDNs (xterm, Split.js, Chart.js, and Mermaid) are now vendored and served same-origin so no public CDN is a script authority. Governed by ADR-036; promotion to enforcement is a tracked follow-up. (#1520)
- Administrator bootstrap now requires strict provider verification (non-empty issuer, subject, email, and the literal `email_verified is True`) on both the Cognito/OIDC and GCP Identity Platform login paths, and privileged accounts are bound to the provider `(issuer, subject)` pair (bind-once, fail-closed on drift) instead of email alone. (#1521)
- Made the platform→provisioner ACES `ProvisioningPlan` transport versioned and fail-closed (ADR-032-R7). The provisioner now validates the transport contract version and the `aces-sdl` producer version and rejects unknown resource types, malformed payloads, duplicate identities/aliases, and dangling network references before any cloud mutation, so version skew or a malformed plan can no longer silently provision a partial or incorrect topology. (#1522)
- **ACES-native GCE provisioning now realizes authored account login credentials without exposing secret material in plans or evidence.** Password and account-specific SSH-key methods are generated per concrete guest, installed over the pinned post-boot management channel, verified on Linux and Windows, and removed during range teardown; unsupported methods and the inconsistent cross-OS `mail` claim now fail closed. (#1560)
- ACES-native GCE provisioning now realizes authored service principal names as real range-local Active Directory state. The backend promotes and verifies the authored Windows controller, joins and verifies Windows members with machine-scoped offline-domain-join packages instead of exposing the domain authority password, creates domain accounts, registers each SPN with uniqueness-preserving `setspn -S`, and reads the directory state back before reporting success. Unsupported topology combinations fail before dispatch, domain credentials use opaque deterministic Secret Manager entries and a separate SSH stdin channel, and the former Linux/Windows SPN marker files are removed. (#1561)
- Closed the packer.yml base-image build privilege boundary (issue #1656, PR2 of 2): the base `build` job now assumes a dedicated least-privilege image-pipeline IAM role (`github_actions_image` in `platform/terraform/global/iam`) instead of the broad GitHub Actions deploy role. Its OIDC trust is pinned to the exact `dev`/`main` protected-branch subjects (never `repo:...:*`), and its `iam:PassRole` is scoped to exactly the environment range instance role (`shifter-${env}-range-range-instance`) passed to `ec2.amazonaws.com` - so the fresh-boot verifier can launch a range-profile instance while no more-privileged instance profile can be passed to EC2. A new ADR-004-R22 guardrail (`check_tf_iam_role_naming`) pins the exact-subject and exact-range-role invariants in pre-commit and CI, and the `build_ami` MCP dispatcher's protected-ref gate is re-applied after it regressed in the #690 module split. The global-IAM `terraform apply`, the `AWS_IMAGE_ROLE_ARN_*` GitHub secrets, and the live OIDC-subject verification are the post-merge operator cutover (see the AWS AMI seeding runbook). (#1656)
- Hardened the pre-promoted Domain Controller AMI publication path so the `/shifter/ami/dc` runtime pointer can only be set from a validated, trusted-provenance id (issue #1656, follow-up to #1633). Both publishers - the `packer.yml` base build and the `packer-promote.yml` prod promote - now read `dc-amis.json` from a dedicated checkout of the protected `dev` ref (independent of the dispatched/build ref and any self-hosted-runner leftovers) and resolve it through one shared validator (`scripts/bake/resolve-dc-ami.sh`) that fails closed unless the id exists, matches the AWS AMI shape, and names an image that EC2 reports as `available` and owned by the account being published into. The prod promote job's previously bare, unvalidated `jq -r '.prod'` is replaced and gains a fail-closed `dev|main` protected-ref gate. The operator dispatchers (`scripts/ami.sh` and the `build_ami` MCP tool) now dispatch the packer workflows against a protected ref (dev by default, main opt-in) instead of the working-tree branch, so a feature-branch copy of a workflow can no longer be used to weaken its own inline gate. (#1656)
- **CTF temporary participant accounts no longer fall back to a shared, repo-visible bootstrap password.** Bootstrap credential resolution now fails closed: the participant-account service accepts only a per-event `participant_password_override` or an explicitly configured `CTF_DEFAULT_PARTICIPANT_PASSWORD`, validates each against the configured password policy, and refuses account creation, attachment, credential reset/resend, and the organizer reveal when neither source is set. Operators must configure a secure event override or platform credential before provisioning participant accounts; there is no built-in default value. (#1665)
- Bound the admitted GCP range backend and instantiation purpose immutably to Engine-owned range state at provision time, and routed range destroy/reconcile from that persisted binding instead of the deploy-wide `GCP_RANGE_BACKEND` env selector (issue #1666, the deferred larger half of #1348). Previously, flipping the deploy selector `gdc -> gce` (to enable live-fire) would make teardown route existing GDC ranges through the GCE path and strand their namespaces, VMs, disks, secrets, L2 Networks, and subnet allocations. Now the CMS live-fire gate's admission result is persisted as a write-once `range_backend`/`instantiation_purpose` on the Engine `Range` (new nullable columns, migration `0029`), the provisioner reads it through its existing request-scoped database projection, and destroy, compensation, retry, and reconciliation route from the range's own backend so a selector flip can no longer strand a range. Legacy (pre-#1666) ranges with no persisted binding resolve their backend only from durable ownership evidence (the `asset_type` discriminant on their instance state) or an explicit operator backfill (`manage.py backfill_range_backend_binding`); an evidence-free row fails closed with a `prerequisite` diagnostic and retains its cleanup state rather than guessing from the mutable selector. No secret material enters the new state, argv, Job env, events, or logs, and the Job env/admission contract is unchanged. (#1666)
- Tightened the GCP GitHub Actions credentialed-CI trust boundary (issue #1690, GCP half of ADR-004-R23; AWS half tracked in #1697). The `cicd-github-oidc` Workload Identity provider now admits only this repository, an exact protected `assertion.ref` (`refs/heads/dev` / `refs/heads/main`), and an allow-listed `assertion.sub`, and binds the CI build service account to exact `principal://.../subject/<sub>` members instead of a repository-wide `principalSet` - so a feature-branch or tag dispatch can no longer federate into GCP by reusing an `environment:` subject. The `CKV_GCP_125` repository-scope waiver is removed, a new `check-tf-gcp-wif-trust` guard (pre-commit + CI) pins the exact-subject condition / bindings and blocks drift between the condition and `local.federated_subjects`, and the five GCP workflows set `persist-credentials: false` on checkout (they already pin `github.sha` and least-privilege permissions). Live WIF/IAM activation and GitHub Environment deployment-branch policies are a documented fail-closed operator cutover with readback (`docs/dev/deploy-secrets.md`); decomposing the shared build SA into per-purpose identities is tracked in #1699. (#1690)
- Sanitized user-controlled values at every log sink in the CSP violation collector and the CTF participant notification service, closing two CodeQL `py/log-injection` alerts (CWE-117). The CSP collector now runs its bounded report fields through `safe_log_value` for both the formatted message and the structured `extra` fields, and the notification service sanitizes the event id in every invitation/credential/reminder/announcement log entry. (#1752)
- Sanitize the operator-supplied `strategy` and spare-pool `count` values through `safe_log_value` before logging them in the CTF range-recovery and spare-provisioning services, resolving three CodeQL log-injection findings (alerts 1087–1089) raised on the #1018 recovery feature.
- Bumped vulnerable npm dependencies to patched versions (part of #1498): `hono` 4.12.23 → 4.12.29 in the ops/planner/ngfw MCP servers, and `js-yaml` 3.14.2 → 3.15.0 in the platform frontend toolchain.
- Bumped vulnerable Python dependencies to clear known advisories (part of #1498): `cryptography` 46/47 → 49.0.0 (platform + provisioner), `bleach` 6.3.0 → 6.4.0, `ujson` 5.12.1 → 5.13.0, and `msgpack` 1.1.2 → 1.2.1.

### Added

- Portal cookie notice shell with client-side dismissal and a public `/privacy/` page for operator-supplied privacy notice content. (#67)
- Added `scripts/delete-user.sh` and `python manage.py delete_user` for deleting test users from Cognito and Django during manual testing. (#83)
- Automatic rotation for the portal Redis AUTH token: a Secrets Manager rotation Lambda rotates the ElastiCache replication-group AUTH token on a schedule (default 90 days) using the ElastiCache `ROTATE` strategy, so the previous token stays valid alongside the new one and the Django Channels backbone never loses authentication mid-rotation. The new token is promoted to `AWSCURRENT` and the portal ASG is refreshed so containers rehydrate it (#159). (#159)
- Added a disaster-recovery runbook (`docs/ops/disaster-recovery.md`) for the AWS portal stack — a component recovery matrix with RTO/RPO targets, per-component restore procedures (RDS PITR/snapshot, Terraform and engine/Pulumi state versions, Cognito reseed, EC2/ASG rebuild, Secrets Manager regeneration), and an RDS point-in-time recovery drill executed against the dev database (2026-06-24: observed ~53 min RTO, ~7 min RPO), recorded in the runbook evidence log. Backup failures are now detected: a new `portal/backup-alerts` Terraform module creates an RDS event subscription (categories `backup`/`failure`/`low storage`/`availability`/`maintenance`/`recovery`) routed to a dedicated CMK-encrypted SNS topic, wired into the dev, proof, and prod portal environments. The dedicated topic is required because RDS events cannot publish to the shared `alias/aws/sns`-encrypted alerts topic. (#160)
- Audit logging for authentication and terminal-session events: OIDC callback token-validation failures are now recorded as failed logins with a bounded reason, browser logout is audited, and terminal sessions that end on idle/max-duration timeout are distinguishable from ordinary closes (with the user email attached to session-lifecycle rows). (#162)
- Range Kali and Ubuntu guest AMIs now auto-launch Claude Code (`--dangerously-skip-permissions`) on interactive Mission Control terminal sessions, with guards so provisioning and non-interactive SSH are unaffected. (#180)
- Post-deploy smoke tests now provision a real dev range after portal deploy, verify SSH/RDP connectivity through existing range services, tear down by request id, and open a GitHub issue when the advisory smoke job fails. (#218)
- CloudWatch log metric filter and alarm for SQS worker restart warnings on portal EC2, with per-queue dimensions and SNS alerts when restarts exceed the configured threshold (#274). (#274)
- **Added CloudWatch health alarms for the self-hosted GitHub Actions runners.** Each runner now has EC2 instance/system status-check, sustained-CPU, and runner-service-liveness alarms wired to an SNS topic, plus a host systemd-timer monitor that reports `actions.runner.*` service state. The liveness alarm treats missing data as breaching so a hung host that stops reporting is detected instead of going silent, and the system status-check alarm can opt into EC2 auto-recovery. A response runbook lives at `docs/ops/github-runner-health-alerts.md`. (#292)
- Platform deploy pipelines now run a post-deploy `verify` job that fails closed when the portal ALB target group, `/health/`, Guacamole ECS services, Guacamole target group, or `/guacamole/` smoke probe are not healthy after deploy. (#310)
- Added rate limiting (backpressure) on the Mission Control range-launch and NGFW-create endpoints to prevent cascade failures under load. Each endpoint enforces a per-user budget and a system-wide (fleet) budget; exceeding a budget returns HTTP 429 with a `Retry-After` header. The limits are backed by the shared Redis cache in production and are tunable via the `RANGE_LAUNCH_*` / `NGFW_LAUNCH_*` settings. (#322)
- Added `build_ami` and `promote_ami` tools to the shifter-ops MCP server, mirroring `./scripts/ami.sh` by triggering the `packer.yml` and `packer-promote.yml` GitHub Actions workflows. (#411)
- Range instance visibility is configurable per event (#483): organizers choose which instance OS types participants see in the terminal (defaulting to attacker boxes only, empty meaning all), replacing the hardcoded Kali-only rule via a pluggable shared visibility policy. (#483)
- Added a GCP Compute Engine guest-image build pipeline parallel to the AWS AMI path (PLAT-001.10): `googlecompute` Packer templates under `shifter/packer/gcp/` for `ubuntu`/`brokenbk`/`kali`/`windows`/`dc`, the `packer-gcp.yml` (build) and `packer-gcp-promote.yml` (promote) workflows on `ubuntu-latest` with Workload Identity Federation, and `build_gce_image`/`promote_gce_image` MCP ops tools. GCE images are versioned by image family (`shifter-<type>`) rather than AWS SSM parameters; AWS `amazon-ebs` builds and workflows are unchanged. Kali requires an operator-imported base image (no public GCP image). Builds are statically validated; live builds require a bootstrapped GCP project. (#505)
- CTF events now carry an explicit, organizer-configurable scoring mode. Standard scoring (fixed per-challenge points, less hint penalties) is the default and only supported mode; solve scoring dispatches through a scoring-mode strategy so future modes can be added without changing the submission flow. Existing events default to standard. (#520)
- The CTF scheduler (CTF-1001/#526) now retries transient task failures with exponential backoff, exposes an organizer task history with run-now on the monitoring page, and documents its intentionally one-shot, deployment-supervised model. (#526)
- CTF organizers can now change challenge visibility at any time, including during a live event, to stage new challenges or hide broken ones (CTF-110). Locked challenges show participants a locked notice in the SPA instead of a submit form, and the organizer challenge page displays the current visibility state. (#544)
- The SPA challenge form now supports scheduling a release time, so hidden challenges auto-reveal at the configured moment (CTF-111); previously this could only be set through the legacy form. (#545)
- The organizer challenge page now shows the configured target instance and port alongside the participant-specific connection details already shown to players (CTF-115). (#548)
- The SPA event form now exposes submission cooldown and the attempt-limit mode (permanent lockout or timed cooldown) with its timeout, completing per-event brute-force controls in the new UX (CTF-112). (#549)
- Challenge tags now appear in the participant and organizer challenge listings with one-click tag filtering in the SPA (CTF-113); tag labels are included in the participant browse API. (#550)
- Challenge descriptions and solution writeups now render as Markdown in the SPA (code blocks, lists, tables via GFM) instead of plain text (CTF-117). (#551)
- Challenge topics (the managed knowledge-area taxonomy) are now shown and filterable in the participant and organizer challenge listings in the SPA (CTF-119). (#552)
- Participants can now rate solved challenges (1-5) in the SPA, with averages shown when the event's rating visibility is public; organizers see the aggregate on the challenge page and can set rating visibility (public / organizer-only / disabled) on the event form (CTF-120). (#554)
- Default email templates now cover every CTF notification type (CTF-805), including the new range-ready, provisioning-failure, and final-results messages; per-event customization stays validated against the placeholder allowlist. (#580)
- Reminder intervals and the event timezone are now configurable from the canonical API and the SPA event form (CTF-1005). (#582)
- Participants now see the event schedule in their local timezone with a live countdown to start or end, plus the event rules, on the workspace home page (CTF-702). (#583)
- Added a GitHub Actions to GCP Workload Identity federation for the packer GCE image builds (`packer-gcp.yml`): a Workload Identity pool, a repository-scoped OIDC provider, and a least-privilege packer build service account, all codified in terraform (`modules/cicd-github-oidc`). This is the GCP analog of the existing AWS GitHub OIDC role and lets the image-build workflow authenticate without long-lived service-account keys. The build service account holds only the roles the GCE image build and GCS export need (compute instance admin, service-account user, compute/storage admin, IAP tunnel access for external-IP-free builds, and Cloud Build). The same module provisions the supporting build infrastructure: a dedicated packer builder subnet (internal-IP builds reachable over IAP, so no external IP is needed under the project's `compute.vmExternalIpAccess` org policy), an IAP-scoped ingress firewall, and a GCS bucket the built GCE images are exported into as `gs://` disk sources for the GDC VM Runtime (read-granted to the VM Runtime image-pull identity). `packer-gcp.yml` now exports each built GCE image to that bucket as a qcow2 (a GCE image family cannot be booted by the VM Runtime, which imports a disk from a `gs://` source), and the GCP guest-image build → export → wire pipeline is documented in `docs/architecture/gcp-guest-images.md`. (#615)
- Challenges can be exported and imported as portable packs (CTF-1101/CTF-1102): full-fidelity Shifter format (verification material, hints, taxonomy) with per-entry error reporting and duplicate detection on import, driven from the admin challenges page. (#629)
- Event results export (CTF-1103): organizers can download final rankings, per-participant solve details, hint usage, and aggregate statistics as JSON or CSV. (#631)
- CTFd-compatible challenge packs import and export (CTF-1104): CTFd JSON entries map to Shifter challenges (plaintext flags hashed on import, hints with costs); exports omit unrecoverable flag values and Shifter-only fields. (#632)
- The canonical CTF REST API is complete (CTF-1201): full event/challenge/participant/scoring/hint coverage with OpenAPI documentation, and the large list endpoints now accept optional limit/offset pagination with a total count. (#633)
- Outbound webhooks (CTF-1203): organizers register per-event endpoints that receive signed JSON payloads on flag solves, first blood, event state changes, and registrations, with exponential-backoff retries and delivery status visible on the event page. (#635)
- Organizer analytics dashboard (CTF-1302): score distribution, solves over time, challenge difficulty calibration (solve rate against point value), and cohort engagement metrics, live during and after events. (#636)
- Custom event pages (CTF-1303): organizers author markdown pages (rules, FAQ, getting started) that participants read from the workspace home page. (#637)
- CTF extension points (CTF-1401): external Django apps can register custom flag validators and scoring strategies from AppConfig.ready; registered types become valid model values and win dispatch, with no standalone plugin lifecycle. (#638)
- Per-event branding (CTF-1402): events carry a logo and accent color shown on the participant workspace. (#639)
- Events can now use dynamic (decay) scoring (CTF-202): a challenge starts at its full value and decays toward a configured minimum as solves accrue, with linear or logarithmic curves per challenge. Every new solve retroactively re-prices earlier solvers so all hold the same base value, with hint penalties preserved. Configure the mode on the event form and the decay parameters on each challenge. (#641)
- Organizers can now grant bonus points or deductions from the participant page in the SPA (CTF-204): awards carry a reason, appear in the participant's score breakdown, count toward the total score, and can be revoked. (#642)
- Scoreboard visibility now has three modes (CTF-404): public (anyone with the link, for example projector screens), participants-only, and hidden (organizers only). Existing events keep their prior behavior; the mode is changeable at any time from the event form. (#643)
- Team events are fully usable from the SPA (CTF-501): participants create or join teams directly on the Team page, and team mode plus size limits are frozen once an event starts so mid-competition team structures stay stable. (#644)
- Participants can now create teams in the SPA (CTF-502): unique name per event, with the creator becoming captain. (#645)
- Team captains now have real powers (CTF-503): rename the team, remove members, transfer captaincy, and disband, all captain-authorized in the API and available on the Team page. (#646)
- Team invite codes are now first-class in the SPA (CTF-504): captains see and share the code, can regenerate it to invalidate the old one, and joiners enter it on the Team page. (#647)
- Team size limits are enforced everywhere (CTF-505): the locked capacity check now also covers organizer team assignment at invite time, not just participant joins. (#648)
- Participant registration is fully enforced (CTF-601): delivery emails are unique per event (invite, bulk import, and a database constraint), with the registration window and capacity checks already guarding every entry path. (#650)
- Invitation lifecycle documented as complete (CTF-602): organizer invites, status tracking, resend with credential reset, and revocation via participant removal cover the requirement under the isolated-account model. (#651)
- Bulk participant import is now partial-success (CTF-603): bad rows (format errors, duplicates in the file or against the event) are skipped and reported per row while the rest import, and the SPA gained a CSV import dialog. (#652)
- Event-scoped participation roles (CTF-604): observers can watch an event (content, scoreboard) but never submit flags, unlock hints, or appear in rankings; organizers toggle the role from the participant page. (#653)
- Participants can be banned and unbanned (CTF-605): a banned participant loses all event access while their submission history is preserved, with the reason recorded and shown to organizers. (#654)
- Hidden participants (CTF-606): organizers can hide a participant so they play normally but never appear in rankings or affect team totals; admin views still show them with a hidden flag. (#655)
- Delegated event staff (CTF-607): organizers assign moderators (participants, announcements) and judges (submissions, awards) per event; staff never gain access to event configuration, challenges, or scoring. (#656)
- Event-scoped participant profiles (CTF-610): a new Account page lets participants edit their display name and affiliation, backed by profile endpoints on the me-surface. (#658)
- Cancelling an event now notifies all participants before ranges are destroyed, and cancellation (like every lifecycle transition) is available from the canonical API and the SPA event page (CTF-706). (#662)
- Events now carry organizer-authored rules text shown to participants on the workspace home page (CTF-707, markdown). (#663)
- CTF milestone emails are complete (CTF-801): participants now get range-ready notices, provisioning-failure notices, and a final-results email with their rank when the event ends; delivery stays asynchronous and failures never block event operations. (#664)
- Real-time in-app notifications (CTF-802): the CTF workspace now subscribes to the platform notification bus and shows live toasts for announcements, challenge releases, first blood, and range readiness; disconnected participants receive pending notifications on their next connection. (#665)
- Announcements are now participant-visible (CTF-803): a feed on the workspace home page lists all past announcements with markdown bodies, and new announcements arrive live. (#666)
- The CTF layer now declares event capacity to the provisioning engine before spinup (CTF-908): expected concurrent ranges (roster plus spares), cohort size, the provisioning window, per-range shape, and organizer-authored shared-resource hints. The engine records declarations durably with admin visibility; allocation strategy stays out of scope. (#668)
- Documentation coverage enforcement for major platform features (GEN-001): a `documentation-coverage` ADR guard check (ADR-022) backed by `docs/adr/documentation-coverage.yaml` now verifies that every major feature ships both user and technical documentation that exists and is linked from an index. Added the missing CTF documentation (participant guide, organizer guide, and technical reference) and removed a dangling scenario link. (#670)
- GCP deployments can now send transactional email (sign-up verification, password reset, invitations) through an operator-chosen SaaS — SendGrid or Mailgun — via `django-anymail`, reaching parity with the AWS SES path (PLAT-002). The ESP API key is supplied through Secret Manager and hydrated at runtime; it is never committed. Email stays optional, falling back to the console backend when unconfigured. GCP deployments can also now publish the portal capacity gauges (`Shifter/PortalCapacity`: in-flight requests, worker busy ratio, terminal-session utilization) to Cloud Monitoring, reaching parity with the AWS CloudWatch path. The emitter selects the publisher by `CLOUD_PROVIDER`; metrics stay optional and fail-soft, never blocking worker boot. (#671)
- Added backend-aware `shifter-config init` and `doctor` commands: `init` scaffolds a starting `shifter.yaml` from a checked backend example, and `doctor` validates the selected backend before deployment (required tools, secret references, generated outputs, owned paths, and the backend bundle's non-mutating validation checks; opt-in read-only health probes), classifying each check as local-only, cloud-read-only, or deployment-mutating. Non-mutating by default. (#727)
- Completed the GCP backend bundle contract: the `gcp` entry in the installation registry now ships a closed `GcpBackendSettings` model (`project_id`, `region`; unknown keys fail closed, `range_egress` stays owned by the shared cross-backend validator), an anchored Google Secret Manager reference grammar for `django_secret_key`, the full generated runtime-env projection classified from `installation.runtime_inventory` (secret references vs. public config, with per-key portal/worker/provisioner/range-task consumers), and the canonical GCP validation checks (`terraform fmt`, `helm template`, `kubectl kustomize`, `kube-linter`). Publishing the closed GCP `settings_schema` is an additive completion of the provisional entry (like AWS in #728), so the published backend-bundle contract stays at version 1. GCP deployments should set `settings.project_id` / `settings.region`. See `docs/architecture/gcp-backend-bundle-migration-preflight-729.md`. (#729)
- Added a sanitized `shifter-config runtime-inventory --check` command that inventories checked-in runtime configuration surfaces and catches GCP runtime env drift without printing env values. (#763)
- Add DB connection churn diagnostics to the event-load harness report so operator runs can evaluate whether Django database connection lifecycle contributes to event-load latency before changing connection posture. (#853)
- Added a scripted event-load harness (`uat/event-load-harness`) that drives a deployed Shifter portal over its real HTTP and websocket paths (authenticated page traffic, terminal websockets, range-status polling, Guacamole RDP bootstrap) and renders a sanitized concurrency-envelope report, providing measured evidence for the event baseline and portal sizing instead of an analytical-only estimate. (#926)
- **Portal NFW inspection is now gated behind a post-apply wiring assertion.** Enabling portal east-west inspection removes the direct private → NAT default route, so a stale, wrong-AZ, unhealthy, or missing firewall endpoint could silently blackhole egress while `terraform apply` still reported success. The committed dev/prod portal tfvars now default `enable_portal_inspection` to `false`, and when inspection is enabled the portal apply job runs `scripts/assert_portal_inspection`, which proves against live AWS state that route tables point at healthy per-AZ Network Firewall endpoints matching `firewall_status.sync_states` and fails the deploy otherwise. Inspection remains visibility-first (stateful pass / ALERT-only); the assertion proves the inline path is healthy, it does not enforce drops. (#932)
- Made portal autoscaling react to application request-path saturation instead of average EC2 CPU, so the fleet scales out before CPU pins. The portal ASG now scales on ALB `RequestCountPerTarget` and `TargetResponseTime` target-tracking policies (which also own a saturation-aware, drain-respecting scale-in), with an additive scale-out driven by a new app-emitted worker busy ratio; average EC2 CPU is demoted to a guardrail notification alarm and the CPU-low scale-in is removed. A per-worker daemon publishes `Shifter/PortalCapacity` gauges (in-flight HTTP request concurrency, worker busy ratio, and terminal-session counts/utilization) to CloudWatch under a least-privilege, namespace-scoped IAM grant; it is fail-soft and never adds latency to the request path. The signal is made observable through CloudWatch alarms (ALB latency/5xx/rejected-connections/unhealthy-hosts, worker busy ratio, and a capacity-metrics-missing alarm) and a portal-capacity dashboard, all environment-owned via `terraform.tfvars` and the `portal/ssm` knob path (`PORTAL_CAPACITY_METRICS_ENABLED`, `PORTAL_WORKER_SOFT_CONCURRENCY`) read by both container hydration paths. The event-load harness collects the new ALB `RequestCountPerTarget`/`ActiveConnectionCount` and `Shifter/PortalCapacity` signals so a load run can show scale-out tracking request saturation ahead of CPU. (#940)
- Added `shifter-config render`, which generates the range egress allowlist's provider Terraform bridge variables (AWS `victim_allowed_cidrs`; GCP `range_egress_mode` + `range_egress_allowed_cidrs`) directly from the validated `settings.range_egress` policy in `shifter.yaml`. Operators now render the deployment tfvars from the single authoritative source instead of hand-maintaining a second gitignored allowlist copy, so the configured policy and deployed firewall rules cannot drift. (#958)
- Added an operator flow to recover a CTF participant's live-fire range when it has been destroyed beyond in-place repair. From the CTF admin range list an organizer can rebuild a fresh same-event/same-scenario range or reassign an available range from the event's prewarmed spare-range pool; the old range is always destroyed. The participant keeps their scoreboard identity, submissions, awards, team/bracket membership, and registration; the recovery is idempotent and safe to retry after a partial failure; and its phase and any failure reason are surfaced in the admin surface. Also adds an event spare-range pool: each spare is provisioned under a dedicated managed system user (never a participant) until it is consumed, formalizing the previously hand-made spare-user process. (#1018)
- Added the `proof` AWS tenant as a first-class deploy environment: the deploy/platform/packer workflows now route `dev`/`proof`/`prod` (per-environment AWS role, ECR repositories, instance and task-definition names, and portal secrets), `scripts/bootstrap/deploy.py` recognises `proof`, and `platform/terraform/environments/proof/` provides the proof tenant Terraform. Pushing `aws-proof` deploys the proof tenant; Quality is skipped on that manual-deploy path since the SHA already passed on `dev`. (#1083)
- Hospital CTF CyberScript schemas (`cyberscript.schemas.ctf`) with `AnyRangeSpec` discriminator and CMS `CTFScenarioTemplate` / `hydrate_ctf` path for the penumbra-scenarios #8 contract. (#1085)
- **Added platform DRF API conventions and OpenAPI endpoints.** The API now has a shared error envelope, authenticated schema/docs routes under `/api/v1/`, route-level v1 namespacing, and developer guidance for adding scoped DRF endpoints. (#1119)
- Add a native CTF smoke & validation protocol under documentation/docs/qa/ — a hybrid (automated CLI/DB + manual Browser) harness covering the organizer and participant journeys plus regression guards for the confirmed concurrency/integrity/state-machine bugs (#1135, #1137-#1149). (#1150)
- Added provenance-only ACES package-source catalog persistence (`AcesPackageSource`) and surfaced active, non-shadowing package-source entries in the unified scenario catalog projection. Access stays governed by `ScenarioMetadata` (enabled / staff-only); launchability is derived from conformance readiness. (#1252)
- Added data-driven, workflow-aware launchability to the scenario registry: ACES package entries are launchable only when their source/contract/profile is supported, their refs/digests re-validate, they pass conformance, and they do not shadow an active legacy scenario. Range launch, CTF event selection, and CTF participant provisioning now consume launchable-only scenarios (with an explicit guard at range creation), while the staff catalog still shows non-launchable ACES entries for review. Legacy YAML and DB custom scenarios are unchanged. (#1253)
- Expose read-only ACES package-backed catalog metadata (identity, contract/profile, package + lock digests, conformance status/report ref, bounded provenance summary, access and launchability state) through the CMS catalog API (`/api/v1/cms/catalog/`) and the scenario editor. Staff can inspect ACES entries and toggle their access overlay; ACES entries remain read-only (no authoring, YAML edit, clone, delete, or export). No raw ACES SDL, generated content, credentials, or provider payloads are exposed. (#1254)
- Published Shifter's ACES `provisioning-only` backend manifest (`backend-manifest-v2`) as a checked-in source under `shared/aces/`, validated against the ACES contract/profile tooling. The manifest declares only the provisioning capability Shifter genuinely realizes and claims no orchestrator, evaluator, or participant-runtime capability. (#1261)
- Added Shifter's ACES RuntimeTarget provisioning adapter (`shared.aces.runtime_target` + `cms.aces.range_realization`), a translation boundary that validates an ACES `ProvisioningPlan` against Shifter's `provisioning-only` capability envelope and translates a supported plan into a valid wrapped Shifter range spec through the incumbent hydration path, with no live dispatch. (#1262)
- Added an automated ACES backend conformance gate that validates Shifter's published `provisioning-only` backend manifest (builder and checked-in artifact) through ACES-owned conformance tooling, with bounded, sanitized diagnostics. (#1263)
- Added live validation for the Shifter ACES-native provisioning path (the ADR-031 cutover evidence gate). The new `run_aces_backend_validation` management command launches a registered ACES package through the normal product path (`create_range_dispatch` to `create_aces_native_range`), polls it to READY, reads back the redacted operation-receipt, operation-status, and runtime-snapshot evidence through the same Mission Control read seam (`shared.aces.projections`), and asserts a non-vacuous realization: an accepted receipt, a succeeded status, and a snapshot carrying at least one realized resource. It re-asserts the redaction contract as defense in depth, always tears the range down by `request_id`, and maps failures to bounded, sanitized diagnostics. The evidence-collection logic lives in `cms.aces.validation` (`collect_evidence` + `validate_evidence`). A minimal, provisioning-only validation package ships at `scenario-dev/shifter-aces-validation/`, and the evidence path is documented in `docs/architecture/aces-cutover-evidence-1264.md`. The command runs only with `SHIFTER_ACES_NATIVE_PROVISIONING` enabled; with the flag off the path is inert. (#1264)
- Added first-class ACES operation sidecar persistence for receipt, status, runtime snapshot, and execution-plan reference records, keyed by Shifter `request_id` with explicit profile/version discriminators, idempotent writes, retention metadata, and secret-rejecting validation. (#1273)
- Added an ACES operation-status projection bridge that maps validated ACES operation status (plus the submitted range operation intent) into Shifter `ResourceStatus` through an explicit, runtime-safe adapter, then projects it onto the existing range event path (`RangeEventOutbox`, drainer, worker retry, and reconciler). ACES-backed range status now flows to CMS `RangeInstance`, the CTF bridge, and Mission Control through the current handler seams with DB-authoritative recovery; invalid and stale observations are rejected and never reach range state. (#1274)
- Added read-only Mission Control APIs exposing ACES operation status, operation receipts, and runtime snapshots for a range, keyed by `request_id`: `GET /api/v1/mission-control/range/<request_id>/aces/{operation-status,operation-receipts,snapshots}/`. They reuse the existing session/API-token authentication and the exact `mission_control:range:read` scope, authorize range ownership through `cms.services.get_range_by_request_id` before any sidecar lookup (unknown or not-owned `request_id` returns 404 with no enumeration), and return redacted projections through a shared read seam (`shared.aces.projections`) with per-record-kind response allowlists so raw sidecar payloads, secrets, prompts, scripts, tokens, flags, and provider dumps are never returned. (#1275)
- Surfaced ACES-backed operation state as a secondary, read-only projection in the Mission Control range dashboard. The active/paused range tiles now show the latest ACES operation status (with a display label kept distinct from the Shifter range lifecycle), when the operation was observed, and a runtime-snapshot resource count, read through the #1275 projection seam. The projection is namespaced as an optional `aces_projection` object on the range read responses and is absent for legacy/non-ACES ranges, so existing range launch, lifecycle controls, status polling, and websocket updates are unchanged. Only bounded, sanitized values reach templates and JavaScript (no raw snapshots, resources, secrets, prompts, commands, or provider dumps), and ACES state never drives range lifecycle, reconnect, or timeout behavior. (#1276)
- Added bounded retention and a dedicated pruning service for ACES operation sidecar records: rows are stamped with a settings-backed `retention_expires_at` at write time and the new `run_aces_operation_record_prune` service deletes expired rows in bounded batches (wired into the AWS portal, GCP Kubernetes, and Helm deployments alongside the guacamole prune worker). Runtime snapshots stay bounded operational observations, not an archive. (#1277)
- Added read-only Mission Control APIs (`.../aces/participant-implementations/`, `.../aces/participant-runtimes/`) backed by first-class ACES participant-runtime sidecar storage, mirroring the ACES operation-record pattern. (#1288)
- Added `participant_behavior_history` and `participant_evidence` reference record kinds to the ACES participant-runtime sidecar family. Both are append/reference oriented: they cite Shifter scripts, prompts, dispatch receipts, transcripts, artifacts, and behavior events by storage ref, digest, provenance source, capture profile, redaction policy, and retention class, and the shared validators reject every prohibited payload class (presigned URLs, upload/Guacamole tokens, SSH keys, RDP passwords, CTF flags, terminal streams, rendered commands, and prompt/script/transcript/provider bodies) so no raw execution material enters ACES rows. (#1289)
- Surfaced read-only ACES participant/runtime and access-channel projection fields (`aces_participant_runtime`) on the Mission Control range read responses and dashboard, sibling to the existing `aces_projection` and absent for legacy/non-ACES ranges. (#1290)
- Added the Risk Register single-page application (SPA) workspace (the first module of the ADR-029 SPA cutover) behind the `RISK_REGISTER_SPA_ENABLED` rollout flag (default off). It is a React 18 + TypeScript + Vite frontend (built into Django's static tree and served by WhiteNoise) that consumes the existing `/api/v1/` Risk Register endpoints with session authentication and CSRF, using React Router v7 and TanStack Query over a single typed API client. When the flag is on, the GET pages under `/risk-register/` are served by the SPA host view while the legacy Django POST action URLs remain for compatibility and rollback; when off, the existing Django templates are unchanged. Also adds a `/api/v1/bootstrap/` session endpoint (principal, permission flags, feature flags) and closes the STRIDE-category validation gap on the Risk create/update API. (#1302)
- Published the backend-bundle contract as a committed, versioned JSON artifact (`shifter/installation/published_contract/`) generated from the Pydantic contract and registry. The published schema encodes the contract's security-relevant validators, and `installation.validate_published_bundle` is a parity-complete portable validator for downstream bundle authors. Adds a `shifter-config contract` CLI and CI gates for drift, unversioned breaking changes (a recursive full-surface compatibility differ against immutable per-version snapshots), registry conformance, and append-only snapshot immutability (#1323). (#1323)
- Published the `/api/v1/` surface as a committed OpenAPI contract (`shifter/shifter_platform/openapi/v1.json`) generated deterministically from the DRF surface, with CI drift and breaking-change gates and a documented versioning policy. Downstream consumers, including the single-page application types, are generated from the committed artifact. (#1329)
- Added an explicit GCE range-cell backend for GCP ranges, including deterministic private IP planning, per-range network/firewall/VM cleanup, Secret Manager credential references, and provider metadata compatible with existing range lifecycle state. (#1341)
- Enabled participant and operator portal access (browser SSH terminal and Guacamole SSH/RDP) to scenario endpoints inside GCP VM range cells, at parity with the existing AWS range access, by authorizing the portal and guacd workloads to reach range guests over the private range network. (#1349)
- Added the platform-wide SPA shell (#1369): a single role-aware React shell with global navigation, a home/dashboard surface, and auth-adjacent states, built on the locked Apple-dark design system. Navigation renders from one shared, role-aware contract (the seam later Phase 2 modules register into), and the Risk Register is rehomed under the unified client router. It ships behind the reversible `PLATFORM_SPA_ENABLED` rollout flag with the legacy Django pages preserved for rollback; the shell meets WCAG 2.1 AA (skip link, landmarks, route-change focus, keyboard navigation). (#1369)
- Ported the Mission Control workspace onto the platform SPA (#1370, SPA Cutover Phase 2), behind the new `MISSION_CONTROL_SPA_ENABLED` rollout flag (in addition to `PLATFORM_SPA_ENABLED`); the legacy Django templates stay the default and remain available for rollback. The React module (`frontend/src/features/mission-control/`) covers the range dashboard, range history, launch, and detail; live range status (a Channels range-status socket used as an advisory refresh trigger over authoritative `/api/v1/` reads, with bounded polling as the fallback per ADR-025-R4); an embedded xterm.js SSH terminal over the existing terminal Channels route; server-brokered Guacamole RDP/SSH sessions opened in a new tab (never embedded, no signed URL persisted); and NGFW, credentials, and agent-upload surfaces. All data access is on the canonical `/api/v1/mission-control/` DRF surface, which was given typed response serializers and `@extend_schema` so `gen:api` now generates real TypeScript types; a new `GET /api/v1/mission-control/ranges/` range-history endpoint was added, and the DRF current-range read now applies the CTF-participant Kali-only instance filter that the legacy template path already applied. Loading, empty, validation, permission, error, and destructive-confirm states are handled throughout, targeting WCAG 2.1 AA. Where Mission Control still lacks `/api/v1/` read coverage (agent deletion, listing existing credentials, and deployment-profile / SCM-credential pickers), the SPA notes the gap in place rather than calling legacy endpoints or adding ad hoc ones; that consolidation is tracked separately (#1328 / #1329). (#1370)
- Added the Scenario Editor single-page application (SPA) workspace (SPA cutover Phase 2, following the Risk Register and Mission Control modules) behind the `SCENARIO_EDITOR_SPA_ENABLED` rollout flag (default off, AND-gated with `PLATFORM_SPA_ENABLED`). It is a React + TypeScript module in the platform SPA that consumes new canonical `/api/v1/cms/scenario-editor/` DRF endpoints (structured create/update, delete, clone, availability metadata, YAML export, plus the existing catalog and YAML validate/create routes) with session authentication and CSRF. Authors can browse the scenario catalog and create, edit (structured or YAML), clone, enable/disable, restrict, export, and delete custom scenarios; built-in, ACES, and CTF scenarios are read-only. When the flag is on, the GET pages under `/scenario-editor/` are served by the SPA host view while the legacy Django POST action URLs remain for compatibility and rollback; when off, the existing Django templates are unchanged. (#1371)
- Add a typed `/api/v1/ctf/` DRF surface (participant + organizer) powering the CTF workspace SPA. (#1372)
- Added the SPA Administer workspace (Phase 2 of the SPA cutover) for staff operators, behind the default-off `ADMINISTER_SPA_ENABLED` rollout flag (served only when `PLATFORM_SPA_ENABLED` is also on). It provides native user administration on the canonical `/api/v1/administer/` DRF surface as explicit named operations rather than a broad model CRUD: a bounded, paginated, filterable user list and detail (roles, account origin, and provenance shown read-only, with no identity-binding fields exposed), plus activate/deactivate, soft-delete, and a grant-only local CTF-Organizer operation. Every operation requires a staff session (platform API tokens are rejected) and the matching Django model permission, and writes a strict, request-attributed audit row inside its atomic service boundary. Platform Settings ships as a read-only, deployment-managed informational surface and Cost as a truthful "unavailable" state pending a separately owned canonical cost source. Django admin at `/admin/` is unchanged and remains available in every rollout state; flipping the flag off restores prior behavior. (#1373)
- Add `scripts/sync-deploy-secrets.sh` to push each environment's local deploy overlays (`local.auto.tfvars` for portal/range/core, plus the `shifter.yaml` for `SHIFTER_CONFIG_*`) into their matching `TF_VARS_*` / `SHIFTER_CONFIG_*` GitHub Actions secrets. Operators now sync from the same files they use for local `terraform` instead of hand-editing whole-file secrets in the GitHub UI; the script supports `--dry-run`, fails loud on a missing overlay, and never prints secret contents. Documented in `docs/dev/deploy-secrets.md`. (#1379)
- Added the ACES-native provisioning core (ADR-031/ADR-032, behind the `SHIFTER_ACES_NATIVE_PROVISIONING` feature flag, default off): a Shifter ACES RuntimeTarget backend (`shared.aces.runtime_target`) that validates a compiled ACES `ProvisioningPlan` against the backend capability envelope (failing closed on any out-of-envelope term) and dispatches the serialized plan itself through an injected port, superseding the earlier `scenario_ref` passthrough. Per ADR-032, Shifter rides the ACES contract end to end: it introduces no parallel SDL or re-modeled spec; the engine persists the serialized ACES plan in `range_config` and the provisioner reads it via accessors that mirror the reference ACES backend (image from the authored `source`, sizing from `resources`, `os_family` for OS dialect only), resolving concrete artifacts at realization from the authored identity. The backend is verified by the ACES-owned conformance suite (fixture + a live target probe that rejects a vacuous pass), and a platform-side drift test keeps the provisioner reader aligned with the reference backend. The producer uses the released `aces-scenario-packs` 1.2.0 / `aces-sdl` 0.20.0 pair, while the provisioner retains a bounded rolling-read window for persisted 0.19.1 plans; an import-linter contract confines ACES SDL tooling to `shared.aces`. With the flag off there is no behaviour change; the existing cyberscript range path stays authoritative. (#1444)
- Added ACES-native GCE range-cell realization (ADR-031/ADR-032, behind the `SHIFTER_ACES_NATIVE_PROVISIONING` feature flag, default off). The provisioner realizes a serialized ACES ProvisioningPlan into a real Compute Engine range cell via a new `aces-range provision|destroy --request-id` command: it maps the authored topology into the neutral GCE range-cell plan (image resolved from the authored `source` against the tenant registry, sizing from `resources`, `os_family` as OS dialect only, authored network CIDRs to subnets, deterministic IP assignment, `count` fan-out) and provisions it by reusing the provenance-neutral GCE apply primitives with an ACES-owned instance path that mints one provisioner-managed SSH key per node for reachability and carries no cyberscript scenario, role, RDP, or Vertex coupling. Authored node ACLs are realized as fail-closed GCE firewall rules placed below the management plane so an authored deny never severs the provisioner's own reachability. Authored ACES composition is realized genuinely as guest bootstrap (ADR-032-R6): content placements (inline files written for real; directories created; non-inline content supplied by the baked image), account placements (real guest users with groups/shell/home/mail/spn, locked when disabled), and service feature bindings (a real install+enable step whose package is provided by the baked image or guest repo) are emitted as an idempotent Linux-bash / Windows-PowerShell script appended to the instance startup script. All plan-controlled values are shell-quoted, file bytes go through base64, and identifiers are validated fail-closed, so authored content cannot inject shell; a placement targeting an absent node aborts. A node that declares no `source` still boots: the backend resolves a base OS image from the tenant registry keyed on `os_family` (ADR-032-R5), a policy distinct from the prohibited inference of an image from `os_family` for an authored source. Image version pins are honored exactly -- a pinned version never silently falls back to the any-version registry mapping, matching aces-sdl (opaque version, no substitution) and the reference backend (hard-fail on an unavailable image). The backend capability manifest now declares the backing capability (`supports_acls`, `supports_accounts`, `supported_content_types`, `supported_account_features`) and the platform capability envelope accepts and fail-closed-validates content/feature/account placements. With the flag off there is no behaviour change; the cyberscript range path stays authoritative. (#1477)
- Wired the ACES-native provisioning path's operational evidence into the existing ACES sidecar/Mission-Control read seams (ADR-031, behind `SHIFTER_ACES_NATIVE_PROVISIONING`, default off). The provisioner now emits `operation_status` observations (running/succeeded/failed) and a `runtime_snapshot` of the provisioned topology from the `aces-range` provision/teardown path, via new `range.aces.operation` / `range.aces.snapshot` outbox events; the engine consumer persists them as `operation_status` and `runtime_snapshot` AcesOperationRecords through the validated, redacted persisters (a new `persist_runtime_snapshot_record` fills the one missing write helper). The snapshot carries only bounded `{address, resource_type, status}` entries built from the authored plan, never the raw GCE outputs (which hold secrets/CIDRs), and failures map to a bounded, sanitized status reason. Records are readable through the existing redacted Mission Control ACES endpoints, keyed by `request_id`; range lifecycle status stays driven by the neutral range status events, so the ACES records are additive evidence. With the flag off there is no behaviour change. (#1478)
- Made ACES packages launchable through a native provisioning path, gated by `SHIFTER_ACES_NATIVE_PROVISIONING` (default off, ADR-031-R5). A new package loader (`shared.aces.package_loader`) turns a registered pack-root `package_ref` into a dispatched launch: under `ACES_PACKAGE_ROOT`, CMS re-verifies the registered canonical content digest, the loader selects the pack's single direct SDL entry, compiles it with `aces-sdl`, plans it against the Shifter provisioning-only backend, and applies the compiled plan through an injected dispatch port. A new launch service (`cms.services.create_aces_native_range`, routed by `create_range_dispatch`) launches a registered ACES package in parallel to the cyberscript `create_range`: it reuses the same ownership, active-range, launchability, and audit checks and persists the same CMS `Request` + `RangeInstance` bookkeeping (with no cyberscript `RangeSpec`), so Mission Control visibility, active-range admission, and range-status propagation all work uniformly. ACES catalog entries become launchable only with the flag on; with the flag off, no ACES entry is launchable and `create_range_dispatch` is byte-identical to `create_range`. Fixed two ACES-conformance gaps that previously blocked launching any real ACES package: the Shifter backend manifest now declares `switch` node support (the aces-sdl planner rejects every network resource otherwise, even though Shifter realizes networks), and the provisional provisioning snapshot now echoes the authored realization concerns (`os_family`, `node_type`, content `spec.type`) so the aces-sdl runtime non-approximation gate confirms the backend committed to realize exactly what the author declared. (#1479)
- Added an explicit `TEST_DB_BACKEND` test-database selector (separating `TESTING=1` posture from the database backend) and a required PostgreSQL CI lane that runs the broad platform suite against real PostgreSQL, so production persistence semantics (transactions, constraints, row/table locking) are exercised instead of only SQLite. (#1524)
- Added GCP-native self-hosted GitHub Actions runners so a GCP dev tenant runs its own CI/deploy instead of borrowing the AWS runner fleet (dev-tenant containment). `deploy.py runners --cloud gcp` provisions a GCE runner into the target GCP project via a dedicated Terraform root (`platform/terraform/gcp/global/github-runner/`, separate state prefix so a platform destroy never removes it): a private-only Shielded VM in a custom VPC with Cloud NAT egress and SSH reachable only over IAP. Registration mints a single-use token per runner and delivers it to the host over the `gcloud compute ssh` stdin stream into a root-only temp file, kept out of the operator's argv/logs, Terraform state, instance metadata, and Secret Manager. (The runner's `config.sh` requires `--token` for non-interactive registration and offers no stdin/file/env channel, so the single-use token is present only momentarily in the isolated runner VM's process args during registration, then removed.) The runner registers with `--no-default-labels` + the `gcp-dev` label, and the command fails closed unless the runner reports online with that label. GCP-dev deploy and destroy workflows now target the `gcp-dev` runner; a new `check-tf-gcp-runner-network` guard (ADR-008-R8) and the extended ADR-003-R5 exposure checker keep the isolation and pull-request gating intact. (#1546)
- Authored ACES `Node.services` ports are now realized as fail-closed, range-scoped ingress firewalls on the GCE range backend (ADR-032-R8): each declared TCP/UDP service opens a deterministic per-node-tag rule admitting only the same range's network CIDRs, kept below authored ACLs and the management plane in precedence, with malformed/unknown-protocol services rejected at the provisioner trust boundary. Behind `SHIFTER_ACES_NATIVE_PROVISIONING` (default off). (#1562)
- ACES-native provisioning now genuinely delivers authored source-backed `file` and `directory` content into range guests: the payload is materialized from the digest-verified pack, promoted content-addressed to object storage, delivered over the authenticated guest channel, and verified in-guest by digest before the range becomes ready. `file` and `directory` are re-declared as backend content capabilities. Gated by `SHIFTER_ACES_NATIVE_PROVISIONING` (default off). (#1564)
- Added a tenant-facing management surface for the ACES image registry (the ADR-032-R2 realization seam that maps an authored ACES image `source` to a concrete provider image). Operators can now register, list, and disable `AcesImageMapping` rows through three surfaces that share the single validated `engine.services` write path: an ACES Images page in the SPA Author area, canonical `/api/v1/cms/aces-image-mappings/` DRF endpoints, and an `aces_image_registry` management command. Disabling preserves the row for audit rather than deleting it. The whole surface is gated by `SHIFTER_ACES_NATIVE_PROVISIONING` (default off) and the SPA page additionally requires `PLATFORM_SPA_ENABLED`; authoring access uses the existing CMS authoring gate. The launch and validation docs now cover registering the validation package's image mapping. (#1566)
- Object-storage-backed ACES packages (`source_kind="object"`) are now launchable behind `SHIFTER_ACES_NATIVE_PROVISIONING`. At launch the portal downloads the single immutable package archive named by `package_ref` from the configured package bucket (`SHIFTER_ACES_PACKAGE_BUCKET`, optionally `SHIFTER_ACES_PACKAGE_PREFIX`), safely extracts it under fail-closed size and entry bounds (rejecting path traversal, symlinks, hardlinks, and device files), and verifies the canonical `package_digest` before dispatch, giving object packs the same containment and immutable-identity guarantees as repo packs (ADR-034-R5). Adds a bounded, precondition-aware object download to the `ObjectStorage` seam (AWS and GCP) and least-privilege read-only portal IAM to the package bucket in both clouds' Terraform. Object rows stay non-launchable (fail closed) until a package bucket is configured. (#1567)
- Added a shared, fail-safe deploy preflight (`scripts/bootstrap/preflight.py`) that validates deployment prerequisites (tools, secrets, config) the same way locally and in CI. It reports every missing prerequisite up front before any Terraform apply, runs interactively by default (with a `--headless` mode and TTY auto-detection), and replaces the GCP operator-seed silent skip with an explicit, logged `SHIFTER_SKIP_OPERATOR_BOOTSTRAP` opt-out. Run it on demand with `deploy.py preflight --cloud {aws,gcp} --env <env>` (ADR-035). (#1575)
- Added a uniform, entitlement-blind content-ingestion path: registering a scenario pack is now one operation regardless of provenance (in-box, public, private, or self-authored). A new CMS registration service backs an authenticated API endpoint (`POST /api/v1/cms/catalog/packs/`, `cms:authoring:write` scope), a `register_pack` management command, and a `bootstrap_inbox_catalog` command that loads the shipped in-box catalog through the same service rather than a privileged code path. Shifter pins `aces-scenario-packs` 1.2.0 with `aces-sdl` 0.20.0, delegates foreign-input validation to the upstream consumer API, and rejects broken, malformed, or non-conformant packs. Repo registration binds the advertised digest to the exact canonical ACES associated-artifact inventory; native launch verifies it again before selecting the pack's single direct SDL entry, so post-registration content changes fail closed. Registration records a provenance-only reference and never an entitlement or identity-of-source check. Object-storage-backed packs are registrable but remain non-launchable until an object resolver exists (#1567). See `docs/ops/content-ingestion.md` and ADR-034. (#1578)
- Made ACES scenario packs image-optional and made parameterized experiment runs representable in the catalog/realizability model (ADR-034). A pack whose SDL declares no VM image `source` now imports through the uniform ingestion path, appears in the catalog, and passes realizability unchanged. Image-bearing is optional, and image count is never a realizability proxy. Added a bounded, body-free run-representation seam (`shared.aces.runs`) that validates a proposed parameter binding against a scenario's declared ACES SDL variables and identifies a run by a one-way binding digest (no raw parameter values persisted or surfaced), plus a catalog-model run-capability projection (`cms.scenarios.run_capability.get_run_capability`) reporting whether a registered pack declares parameterized runs and their bounded parameter schema. (#1579)
- Documentation is now a single public site: all product and engineering docs are consolidated under top-level `docs/`, built with mkdocs (Material), and published to GitHub Pages by `.github/workflows/docs.yml` (PRs get a strict build check; pushes to the default branch publish). The in-app login-gated Django documentation reader is retired; the portal's Docs and Help links point at the hosted site. Internal design notes, machine registries, deprecated content, and scratch dirs are kept in-repo but excluded from the published site (ADR-038; #1591). (#1591)
- CTF participants can change their own login username from the new Account page, validated and audited like the organizer rename. (#1593)
- CTF participants can download a range-scoped OpenVPN profile from the Range page and use a standard OpenVPN client to reach only their assigned Kali target. (#1695)
- Mission Control ranges now expose their remaining server-enforced lifetime in the SPA, support bounded owner-requested extensions up to a fixed maximum, and offer a scoped OpenVPN profile download when the provisioned range supports it. CTF and Mission Control automatic teardown now share the same persisted range-lease reconciler. (#1696)
- Added an operator-triggered `techvault-scenario-bake` workflow that bakes the TechVault golden AMI (the APTL `techvault-operational` stack plus the VS Code seat) and records it in the `/shifter/ami/techvault` SSM parameter, automating the manual bake runbook.
- Add the TechVault purple-team scenario: a scenario template plus the range bootstrap that writes the AWS Bedrock credential shard for Claude Code on the host seat and RDPs in as the `ubuntu` seat user (gated on the `techvault` AMI key).
- Add TechVault purple-team scenario documentation and the golden-AMI bake runbook.

### Changed

- Reduced peak memory use during CMS agent and CTF challenge file uploads by streaming SHA256/size calculation instead of retaining all read chunks in memory. (#96)
- Internal: make `.tgz` compound extension explicit in shared upload inspection helper (no user-visible behavior change). (#97)
- Added operator-triggered rotation for the Cognito portal client secret: an on-demand Lambda performs the blue/green client replacement (Cognito has no in-place secret-rotation API). It creates a new app client copying the current one's config, swaps it into the OIDC secret bundle, and refreshes the portal ASG, while a scheduled EventBridge reminder emails the admin when rotation is due. Documents the API-token and legacy-API-key rotation cadence. Completes the #159 secrets-rotation strategy (#159). (#159)
- Consolidated the GitHub Actions OIDC deploy role's managed IAM policies from 10 (the AWS hard limit of 10 managed policies per role) into 5 by AWS service category - `compute`, `networking`, `data`, `security`, and `management` - in `platform/terraform/global/iam/github-oidc.tf`, freeing 5 attachment slots so future services extend an existing category instead of adding new attachments. `scripts/check_tf_iam_role_naming` fails the build if the role drifts back above 6 managed-policy attachments, and now also fails it if any category policy document approaches the AWS 6,144-character managed-policy size limit (ADR-004-R19), so a category can be extended safely without a late `LimitExceeded` at apply time. The OIDC trust policy, `iam:PolicyArn` attach allowlist, and `iam:PassedToService` constraints are unchanged, and the module's `environment` validation now accepts `proof` alongside `dev`/`prod` to match the existing `proof.tfvars`/`proof.s3.tfbackend` and the `aws-proof` deploy branch. Alongside the consolidation, the scoped policies were extended to cover the full platform deploy surface so the role can run an end-to-end deploy without falling back to inline administrator access (verified by a green `aws-proof` deploy: Core, Range, Engine, Guacamole, and Shifter Platform plan + apply). New coverage includes application auto scaling, Cloud Map service discovery, Bedrock invocation-logging config, ElastiCache, ECS/log/SES/SQS/Firehose/EventBridge/Budgets management for the portal and range namespaces, and IAM policy/role lifecycle scoped to `shifter-*`/`${environment}-*`. The added grants use explicit action lists derived from the actions the deploy actually invokes (least privilege by verb); where AWS does not support resource-level constraints for those actions (CloudWatch Logs, CloudWatch alarms, SES identities, Cloud Map, ElastiCache describe/tag) the statements scope by action and keep `Resource = "*"`, and the remaining `*`-action statements (S3, SQS, Firehose) are constrained to the `*-portal-*`/`*-range-*`/`shifter-*-infra-*` resource namespaces. (#254)
- CMS↔Engine range lifecycle now uses `RangeRef` at service and channel boundaries: `engine.create_range` returns `RangeRef`, destroy/cancel accept `RangeRef`, and Mission Control WebSocket broadcasts carry a validated `range_ref` payload. (#268)
- Provisioner event/status constants now import from the incumbent `cyberscript` wire-contract package instead of hand-mirrored literals; contract and canary tests guard against drift across the process boundary. (#273)
- Inter-service event handlers now consume typed `TypedDict` payloads instead of untyped `dict[str, Any]`. Bus (SNS/SQS) event contracts live in `shared.messages.payloads` (`RangeStatusUpdatedPayload`, `RangeProvisionedPayload`, `NGFWEventPayload`) and Django Channels `group_send` contracts in `shared.channels.payloads` (`RangeStatusChannelEvent`, `NGFWStatusChannelEvent`). Engine/CMS/Mission Control handlers and the Mission Control websocket consumers are annotated with these, so mypy now catches event field typos and type mismatches at the call site. This is a static-typing change only: envelope parsing, `ResourceStatus`/ownership/`RangeRef` validation at the untrusted SQS/channel boundary is unchanged. (#296)
- Internal refactor: `InstanceSpec` inherits `uuid` from `SpecBase` instead of redeclaring the field. (#313)
- Migrated inline `style=""` attributes and `<style>` blocks out of the Django portal templates (Mission Control, CTF admin/participant, experiments, scenario editor, and standalone auth pages) into namespaced static CSS files loaded via `{% static %}`. Behaviour is unchanged; the change improves maintainability, browser caching, and standards compliance. Email-body templates keep inline CSS for mail-client compatibility. (#414)
- Decomposed the GCP control-plane Terraform tree into provider-native submodules (VPC, Cloud SQL, GKE, Pub/Sub, GCS, Secret Manager, Identity Platform, and related services) mirroring the AWS module layout, while keeping `platform-core` as a composition facade with unchanged outputs. (#504)
- Reorganized oversized backend runtime modules into smaller responsibility-scoped modules under the 500-line cap. Affected areas include the CTF services, the provisioner configuration and range operations, the engine models, the GCP task runner, the installation contract, and the cyberscript script context. Public import paths, APIs, and behavior are unchanged. (#561)
- Python type checking is now an enforced, blocking CI quality gate. The `shifter-platform-typecheck` and `provisioner-typecheck` jobs in `.github/workflows/_quality.yml` no longer swallow failures (`continue-on-error: true` and `|| true` removed) and run as guardrails that fail the PR Gate on any mypy error, matching the architecture and SAST jobs. The enforced/transitional boundary lives in each package's `pyproject.toml` `[tool.mypy]` policy (the package minus excluded `migrations`/`tests`), and a stale loop-variable shadow in `cyberscript/schemas/ctf/ctf_range.py` was fixed so the platform estate type-checks clean. (#564)
- CTF notification emails are now delivered asynchronously (non-blocking); reported counts reflect messages queued for delivery. (#581)
- Disqualification reworked per CTF-609: it now records a reason, keeps the participant's login and view access alive, blocks all competitive actions, and is reversible; previously it silently anonymized the account. (#657)
- Automated range cleanup (CTF-703/CTF-1003) destroys ranges in throttle-friendly batches, warns participants 30 minutes before destruction, and can be deferred or cancelled by the organizer; ending an event no longer bypasses the configured post-event review window. (#660)
- The registration deadline now defaults to the event start for display (CTF-705) and closes self-registration only: organizer manual adds and imports work after the deadline so stragglers can join a live event. (#661)
- Internal refactor: finish decomposing the Django `engine` god modules. `engine/ecs.py` and `engine/handlers.py` are split into by-responsibility packages (`engine/ecs/` with `_env`/`_config`/`_local` behind the facade; `engine/handlers/` with `_range`/`_ngfw`/`_audit` behind the routing facade), and the `Range` model's realized-instance projection and status classification move into a dependency-neutral `engine/_range_state.py` (re-exported through `engine.services`). Public `engine.services` / `engine.ecs` / `engine.handlers` import paths, the `engine.handlers.process_event` SQS worker entry point, logger namespaces, audit sources, and all lifecycle, persistence, dispatch, and event-retry behavior are unchanged. (#685)
- Refactored the bootstrap deployment CLI internals into focused operation modules while preserving the existing `deploy.py` entrypoint and command behavior; generated GCP Helm values no longer stage Guacamole runtime credentials on disk. (#687)
- Internal refactor: split the `mcp/ops` server monolith (`index.js`) into a thin composition root plus per-domain tool modules under `mcp/ops/tools/` and support modules (`aws.js`, `db.js`, `schemas.js`, `reconcile.js`, `github-actions.js`, `respond.js`). Public MCP tool names, request/response shapes, capability classes, and trust metadata are unchanged. (#690)
- Internal refactor: split the CMS experiments view module (`cms/experiments/views.py`) into a flow-focused `cms/experiments/views/` package (`_scripts`, `_experiments`, `_downloads`, `_ajax`) behind a stable `cms.experiments.views` facade. View handlers, URL routing, templates, and responses are unchanged; the split keeps each view module focused on a single request/response flow while orchestration stays in `cms.experiments.services`. (#698)
- Add advisory Trivy (first-party Dockerfiles and Terraform) and OSV-Scanner (repo-root lockfiles) CI jobs that upload SARIF artifacts without blocking merge. (#708)
- The portal, background workers, and the range provisioner now derive the active cloud backend from one validated selection resolved at each process's composition root (validated against the `installation` backend registry, the single source of truth) instead of re-reading `CLOUD_PROVIDER` with an implicit `aws` default at roughly twenty scattered call sites. A deployed process now fails closed on a missing or unsupported backend rather than silently behaving as AWS; each cloud factory validates that the selected backend declares the capability it needs before constructing an adapter; and provider-routing sites dispatch explicitly per backend rather than treating any non-GCP value as AWS. `CLOUD_PROVIDER` is now renderer-owned, derived from `shifter.yaml`'s selected backend at deploy time: GCP emits it from the runtime-env renderer, and AWS renders it via `shifter-config render-runtime` into a Terraform variable that the portal and provisioner modules receive rather than hardcoding. The `aws` default remains available only under development, test, and build contexts. Implements PLAT-2005, and is the first runtime consumer of the PLAT-2001 / PLAT-2003 root-config contract. See `docs/architecture/root-configured-backend-bundles.md`. (#726)
- Migrated AWS into a real (non-provisional) backend bundle. The `aws` entry in `shifter/installation/registry.py` now validates its `settings` against a closed model (`region` required, unknown keys rejected), checks the `django_secret_key` and `db_password` references against a machine-readable grammar, and admits the `proof` deployment profile alongside `prod` and `dev`. The shared cross-backend `range_egress` policy stays owned by `installation.range_egress`, so the loader validates it separately from a backend's closed settings model and preserves its verbatim CIDR diagnostics. The published backend-bundle contract artifact was regenerated to match (#728). (#728)
- Environment deploys are now manual: run the Deploy workflow with a `workflow_dispatch` `environment` input (`aws-dev`, `aws-proof`, or `gcp-dev`) instead of them auto-triggering on a push to the env branch. The branch you run the workflow from is the code that deploys; no branch name selects the target. Push and pull_request run validation only. (#730)
- CI Quality workflow jobs now run only for path categories touched by the PR (or the full matrix when workflow files or the path-filter config change). (#774)
- Plan-rules and changelog contributor docs now count as guardrail documentation for CI Quality routing, so edits to `.gc/plan-rules.md` or `changelog.d/README.md` run the full Quality (including SonarCloud) gate instead of being treated as ordinary docs-only skips. (#783)
- SonarCloud now downloads coverage artifacts only from test jobs that actually ran, so path-scoped PRs no longer fail waiting for skipped-job artifacts. (#786)
- Moved inline `style` attributes in scenario editor and NGFW detail app templates into named CSS classes (`theme.css` and page-local styles). Visual behavior unchanged. (#789)
- Bumped enforcement toolchain dependencies: ESLint 10, stylelint 17, eslint-plugin-security 4 across frontend and MCP packages; pre-commit-terraform, Checkov, Ruff, Gitleaks, and Actionlint hooks in `.pre-commit-config.yaml`. (#790)
- Batch safe dependency and security-posture tool updates (npm globals, setuptools pins, types-pyyaml, gitleaks, actionlint, shellcheck-py). (#791)
- Native CTF scoring now serves the live scoreboard, participant rank, and flag-submission responses from materialized per-participant and per-team leaderboard columns instead of recomputing the entire event board from raw submissions/awards on every request. Flag submissions, the participant dashboard, and the auto-refreshing scoreboard poll no longer scale their database work with participant count, so native CTF scoring stays responsive under event load. The materialized state is maintained incrementally on solve/award/disqualification/team-change, is rebuildable from the authoritative submission and award rows via the new `ctf_recompute_leaderboard` management command (and automatically on event completion), and falls back to the exact authoritative recompute for frozen and bracket-filtered team views, so rankings, tie-breaks, freeze, and visibility semantics are unchanged. (#850)
- Reorganised the CTF web layer: the monolithic `ctf/views.py` is now a `ctf/views/` package. URLs and behaviour are unchanged. (#885)
- Split the CMS experiments orchestrator into a package (coordinator plus per-phase modules) to stay under the per-file size limit; no change to experiment lifecycle behavior. (#886)
- Internal refactor: split `ctf.services.participant` into a package (`lifecycle`, `bulk_import`, `queries`) to resolve SonarCloud file-length limit. Public API and behavior unchanged. (#889)
- Internal refactor: `ctf/services/range.py` is now the `ctf/services/range/` package (`provision`, `batch`, `tasks`, `lifecycle`, `status` submodules behind a public facade), clearing SonarCloud `python:S104`. The throttle pacing policy is extracted into a pure `compute_throttle_delay` seam. No behaviour change. (#890)
- Decouple Terraform state backend configuration from committed repo files; per-instance backend configs are rendered at init from deployment-owned settings. (#893)
- Reduced per-request database work in the authenticated portal page renders. The portal context processors now resolve a user's group membership once per request instead of issuing the `auth_user_groups` query up to five times, `cms.services.get_active_range` eager-loads its `agent`/`request` foreign keys (removing an N+1), and the full terminal active-range payload (instances, runtime IP overlay, connection URLs, terminal JSON) is built only on the terminal page — every other authenticated page now pays a single cheap `has_active_range` indicator query for the sidebar. Measured per-render query counts drop accordingly (e.g. the dashboard with an active range from 11 to 4 queries). (#898)
- Corrected the portal terminal-capacity model for the multi-worker runtime and made the runtime capacity knobs tunable without an image rebuild. The portal now runs Gunicorn with `PORTAL_WEB_WORKERS` Uvicorn workers, and the terminal session caps are process-local, so the real per-instance ceiling is `PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS` (and `* TERMINAL_MAX_SESSIONS_PER_USER` per user); the capacity doc and the `settings.py`/`asgi.py` comments now state this instead of the stale single-process figures. `PORTAL_WEB_WORKERS` and the five `TERMINAL_*` knobs are published as SSM `String` parameters by the `portal/ssm` Terraform module and read (with integer validation before they reach the Docker argv) by both container hydration paths (`user_data.sh` on first boot and `scripts/portal-deploy/deploy_portal.sh` on SSM redeploy), so they can be retuned on a running fleet by updating the parameter and converging/restarting the container. Deployed worker counts are now sized to the instance vCPUs in `terraform.tfvars` (dev `t3.large` → 2, prod `t3.xlarge` → 4). (#930)
- The shared persisted WebSocket notification subsystem (`/ws/notifications/`) is now disabled by default behind the non-secret `WEBSOCKET_NOTIFICATIONS_ENABLED` flag (issue #941). It had no front-end consumer, so its per-recipient database writes and channel-layer fan-out were latent event-load cost for no delivered value. When disabled, `shared.notifications.publish_notification` creates no `WebSocketNotification` rows and performs no fan-out, and the shared notification socket rejects connections with a `SERVICE_UNAVAILABLE` close code. The direct experiment-status WebSocket (`/ws/experiment-status/<id>/`) is unaffected and keeps delivering live experiment updates. Re-enabling requires a real browser consumer, bounded fan-out, and scheduled pruning (`manage.py prune_notifications`); see `docs/architecture/notifications-websocket-fanout-preflight-941.md`. (#941)
- Organizer "Provision All Ranges" now runs in the background on the CTF scheduler and returns immediately, with live queued/provisioning/ready progress in the admin UI, instead of blocking the request thread and risking a half-provisioned event when the worker times out. (#943)
- Portal settings now require an explicit `ENVIRONMENT` at boot instead of silently defaulting to `production`, log resolved posture for each subsystem at startup, and ship a generated env-var manifest as the deploy contract (#948). (#948)
- Deduplicated the CMS range pause/resume services behind a single parameterized `cms.services._range_lifecycle` helper (mirroring `engine.services._lifecycle`), and tightened the ADR-001 layer-import gate so private split-package submodules (for example `cms.services._range_pause`, including the `from cms.services import _range_pause` shape) are no longer importable across layers — only the public service facade is. Enforced consistently by both `scripts/check_layer_imports` and `scripts/adr_guard`. (#949)
- Enforce the cyberscript shared-only import boundary in CI: only `shared` may import `cyberscript` directly; `cms/experiments` now routes through `shared.script_context` and `shared.template_vars` shims. (#950)
- Internal schema persistence now uses stable registry slugs for catalog types and versioned discriminators on persisted spec JSON blobs, enabling a future aces-sdl swap without rewriting module paths in the database. SonarCloud on path-filtered PRs now downloads coverage artifacts only for test jobs that actually ran, fixing PR Gate failures when unrelated suites (for example packer) were skipped. (#951)
- Pin ECS provisioner RangeSpec JSON key-walks to the cyberscript wire contract with cross-package drift tests, completing the #273/#952 process-boundary guardrails alongside existing event/status canaries. (#952)
- The built-image stack smoke now exercises the real OIDC login path (`/login`, authorization, callback, first-login provisioning, session) against a local Cognito-shaped provider double, instead of minting a Django session directly, so a regression in OIDC config, the callback, provisioning, or session establishment is caught automatically. (#988)
- **The `mission_control` → `engine.services` layer-import boundary is now enforced per-symbol.** The presentation layer may import from `engine.services` only the sanctioned realized-runtime/data-plane symbols (`connect_terminal`, `SSHConnection`, `get_ssh_connection_info`, `get_rdp_connection_info`, `connect_ngfw_terminal`, `get_ranges_for_ngfw`); any other `engine.services` symbol, or a bare `import engine.services` module import, is a layer-import violation, so control-plane operations keep fronting through `cms.services` (ADR-001-R4). (#994)
- The AWS (`_range.yml`) and GCP (`_gcp-dev.yml`) deploy workflows and `scripts/bootstrap/deploy.py`'s GCP control-plane apply now render the range egress allowlist tfvars from the deployment's `shifter.yaml` (`settings.range_egress`) via `shifter-config render` at plan/apply time, instead of carrying the egress CIDRs in a separately maintained deploy secret. The allowlist is now single-source end-to-end: CI receives `shifter.yaml` as a deployment secret (`SHIFTER_CONFIG_DEV_RANGE` / `SHIFTER_CONFIG_PROD_RANGE` / `SHIFTER_CONFIG_GCP_DEV`), `victim_allowed_cidrs` no longer belongs in `TF_VARS_*_RANGE`, and a missing config fails the deploy loud rather than silently applying `status-quo`. See `docs/dev/deploy-secrets.md`. (#1015)
- Migrate Mission Control JSON endpoints to the shared DRF `/api/v1/mission-control/` surface with scoped platform API-token access and legacy route compatibility, and keep the IAM role naming guardrail stable on all-files runs. (#1120)
- Migrated the CTF JSON API onto the platform DRF `/api/v1/ctf/` surface with scoped token admission and legacy route compatibility. (#1121)
- Added canonical DRF CMS API routes under `/api/v1/cms/` with platform session/token authentication, CMS authoring scopes, and feature-flag-preserving experiment endpoints. (#1122)
- CTF flag-submission concurrency tests (duplicate-solve, attempt-limit lockout, submission cooldown) now run against a real PostgreSQL backend in CI, proving `submit_flag()`'s row-lock guard serializes concurrent requests. (#1182)
- Documented the ACES migration triage for CyberScript and scenario backlog items, making CyberScript extension requests route to current-stack maintenance, ACES migration, superseded, or close buckets instead of extending the legacy DSL indefinitely. (#1231)
- Removed an unreachable dead `APIKey` branch from the `risk_register` access policy, left over after the legacy `rr_live_` API key was retired in #1124. Internal cleanup with no user-facing or behavioral change; the archival `APIKey` model and table are unaffected. (#1244)
- The portal container image build and CI now build the SPA frontend: a Node/Vite stage in `shifter/shifter_platform/Dockerfile` compiles the bundle into the static tree before `collectstatic`, and a new `SPA (shifter_platform frontend)` job in the Quality workflow lints, typechecks, unit-tests (Vitest), and builds the frontend on changes under `shifter/shifter_platform/`. (#1302)
- Added the `aces-parity-inventory-path-integrity` ADR guard check (ADR-024-R4): `adr_guard --all --level ci` now fails when a `legacy_source` or `validation_evidence` clause in `docs/architecture/aces-migration-parity-inventory.yaml` is a repository path or glob that no longer resolves, while classifying shell-command and prose clauses so they are never false-flagged. The check is a global repository invariant (it runs even when the inventory is not in the changed-file set) and is wired into the `ci` level, a dedicated always-run `adr-guard-parity-inventory` pre-commit hook, and the always-present `deploy.yml` pre-commit job so a referenced-file deletion cannot silently leave the ACES cutover parity ledger pointing at nonexistent paths. (#1313)
- Define and structurally enforce the provider-neutral range-substrate contract for provision, destroy, pause, and resume across AWS Terraform and GCP GDC adapters, with Azure explicitly deferred pending conformance. (#1322)
- Consolidated the Mission Control and CTF app-local JSON HTTP APIs onto the versioned `/api/v1/` DRF surface and retired the legacy duplicate mounts. The Mission Control UI (dashboard, agents, terminal, NGFW, credentials) and the CTF UI now call the canonical `/api/v1/mission-control/` and `/api/v1/ctf/` routes exclusively, and the internal callers that produced Guacamole and redirect URLs were repointed to them. The legacy `/mission-control/api/*` mount was removed entirely, and `/ctf/api/*` was reduced to the single scoreboard endpoint (intentionally retained because its v1 twin uses different public-access semantics). Two previously legacy-only CTF operations, event spare-range provisioning and participant range recovery, were added to `/api/v1/ctf/` so the versioned surface is complete. As part of the removal the per-mount error-format compatibility shim was dropped, so Mission Control endpoints now always return the canonical `{"error": {"code", "message", "details"}}` envelope instead of the legacy flat `{"error": "..."}` form. (#1328)
- **GCP VM range cells now enforce a closed scenario-to-platform contract.** Canonically validated scenario content crosses as a digest-bound artifact, while the platform owns admission, network bindings, lifecycle, membership, declared participant access, and cleanup. Destroy can replay without scenario-owned CIDRs, and host-management credentials stay outside participant access results. (#1344)
- GCP ranges now provision on the GCE range-cell backend by default (`GCP_RANGE_BACKEND` defaults to `gce`). The GDC VM Runtime path is retained and can be re-selected per environment with `GCP_RANGE_BACKEND=gdc`. Added the range-scoped `GCP_RANGE_CELL_PROJECT_ID` so range cells target the real range project independently of the control-plane project. (#1387)
- Gate the platform deploy on worker/scheduler container health. The post-deploy checks only covered the portal web tier (image digest + ALB `/health/`), so crash-looping workers (outbox drainer, reconciler, ctf-scheduler, etc.) shipped as a green deploy. A new `verify-asg-workers` step SSM-checks each in-service instance's worker containers and fails the deploy when any never reaches `healthy`, retrying to tolerate the health-start-period and a single transient restart. (#1398)
- Made the post-deploy range smoke agent-independent. It now provisions minimal ranges built entirely from base range AMIs: `smoke_linux` (Kali attacker + Ubuntu victim, SSH probe) and `smoke_windows` (Kali attacker + plain Windows victim, RDP probe), with no XDR agent, and no longer requires the `SMOKE_LINUX_AGENT_ID` / `SMOKE_WINDOWS_AGENT_ID` secrets. The smoke validates the platform (provision, connect, teardown); XDR/agent install is scenario content exercised by real scenarios, not the smoke. (#1422)
- The self-hosted runner Terraform (`platform/terraform/global/github-runner`) gains an explicit ADR-004-R20 opt-in, `allow_default_vpc`, for account-default-VPC placement. The guard still fails closed by default; when opted in (aws-dev/aws-proof set it) the stack auto-resolves the default VPC and one of its subnets, so no live VPC/subnet IDs are committed (ADR-004-R14). This reconciles the #1222 non-default-VPC mandate with the reality that deploys have always run runners in the default VPC. The pinning checker, its tests, ADR-004-R20, and the runner runbook/README are updated to match, and issue #1437 tracks reassessing the durable placement design. (#1425)
- Bootstrap can now provision **and register** self-hosted GitHub Actions runners end-to-end. A new `deploy.py runners` subcommand (and the `full` flow) applies the runner Terraform root (optionally provisioning a dedicated, ADR-004-R20-compliant runner VPC via the new `create_runner_network` variable), then registers each runner over SSM using a single-use GitHub token minted per runner and verifies it online via the GitHub API. Registration tokens never touch Terraform state, user data, SSM Parameter Store, Secrets Manager, or operator logs. Manual `config.sh` registration is no longer required. (#1433)
- Removed all committed environment-specific values from the public repository. Deleted the finished `tssummit` event Terraform (`global/tssummit/`, `global/tssummit-ranges/`), which hard-coded operator and participant home IPs, and scrubbed the operator IP from docs. Templated the pinned base and marketplace AMI IDs (`ec2_ami_id`, `ctfd_ami_id`, `vm_series_ami_id`) out of the committed `terraform.tfvars` baselines, which are region and version specific and go stale, so real values come from gitignored `local.auto.tfvars` and `TF_VARS_<ENV>_*` secrets. The `no-live-cloud-identifiers` guardrail (ADR-004-R14) now also flags globally routable public IPv4 addresses in Terraform and HCL (allowlisting well-known Google, Cloudflare, and GCP infrastructure ranges and RFC5737 documentation ranges; comments excluded) so operator or participant IPs cannot be re-committed. (#1487)
- Every first-party Django app is now classified as a domain, presentation, support/contracts, or support/composition layer, and `config` and `risk_register` participate in cross-layer import and model-boundary enforcement (`check_layer_imports`, `adr_guard`, `.importlinter`, `check_model_fks`). A new fail-closed `installed-apps-classified` guard rejects an unclassified first-party addition to `INSTALLED_APPS`, a stale classification entry, or an unresolvable dynamic `INSTALLED_APPS` entry (ADR-001-R3). The platform audit vocabulary, event contracts, writer port, trusted request attribution, emission policy, and health now live in a neutral `shared.audit` boundary; `risk_register.AuditLog` is a compatibility persistence adapter bound once at the `config` startup seam, and feature layers no longer import risk-register models to emit audit events. `AUDIT_TRUSTED_PROXY_HOPS` is now declared in the env manifest. (#1523)
- Pull-request quality now validates every Terraform execution root: `platform/terraform/validation-inventory.yaml` classifies each tracked Terraform directory (with a validation owner, toolchain profile, and lockfile-verified provider set), and the `Quality` workflow runs a credential-free, backendless `terraform init` + `terraform validate` per affected root so composition errors are caught before merge instead of at deploy time. (#1528)
- Test tooling now matches CI from a clean checkout and reports trustworthy quality metrics (REV1 Q6/Q7). A repository `Makefile` runs each package's suite with the same dependency sync and environment posture CI uses (`make help` lists the targets), and the platform `conftest.py` establishes `DJANGO_DEBUG`/`TEST_DB_BACKEND` and pins `LOCAL_PROVISIONER` off so a bare `uv run pytest` no longer inherits production HTTPS posture or shells out to a real provisioner. Production coverage now excludes tests (so the number reflects owned code, not tests covering themselves) and enforces per-package `fail_under` floors. Unawaited-coroutine and resource warnings fail the platform suite, and third-party deprecations are baselined as narrow per-message allowances with a removal owner (see `docs/dev/testing.md`) instead of being broadly suppressed. (#1529)
- CI now enforces production-path quality ownership. `.github/quality-path-filters.yaml` is a versioned, machine-readable contract that maps every production path to blocking lint, security, and test jobs, and the `_quality.yml` path-detection job rejects any unclassified changed path before it selects jobs. A new `quality-path-ownership` ADR guard (ADR-004-R24) reconciles the contract against the whole repository for estate completeness, ownership completeness, and routing reachability. (#1530)
- The developer setup guide (`docs/technical/dev/setup.md`) now opens with a consolidated "Before You Start" checklist covering local tooling, accounts and access (domain/DNS, GitHub secrets admin), and the AWS/GCP preconditions that must exist before the first apply (bootstrap, self-hosted runners, seeded range AMIs, engine image), linking the authoritative runbooks. It also adds an "Environments and Terraform Layout" section documenting the current one-directory-set-and-deploy-branch-per-environment model: the `platform/terraform/` layout, the environment-to-branch-to-trigger mapping (`aws-dev`, `aws-proof`, `main`, `gcp-dev`), and the steps to add a new environment. The bootstrap CLI README (`scripts/bootstrap/README.md`) gains a "Fresh GCP Account Order" section bringing GCP to parity with the existing AWS standup order, including building range guest images before deploy. (#1559)
- Narrowed the ACES backend manifest to genuinely realized provisioning terms (account features `groups`/`shell`/`home`/`disabled`/`mail`; content type `directory` only) and added a manifest-independent, evidence-backed gate that rejects an over-claimed account feature at apply time before dispatch. All behind `SHIFTER_ACES_NATIVE_PROVISIONING` (default off). (#1563)
- ACES-native provisioning now publishes an honest `network-address-family = ipv4-only` capability constraint on the provisioner backend manifest and rejects IPv6-only or mixed IPv4/IPv6 authored networks at plan admission (`shared.aces.runtime_target`), before any range is persisted or dispatched. The admission diagnostic and the provisioner backstop no longer echo the authored network CIDR into failure events. IPv6 and dual-stack GCE range cells remain unsupported; see `docs/architecture/aces-gce-network-address-family-preflight-1568.md`. All of this stays behind the default-off `SHIFTER_ACES_NATIVE_PROVISIONING` flag. (#1568)
- GCP bootstrap now sources the first Identity Platform operator credentials from the gcp-dev `local.auto.tfvars` overlay (rendered from GitHub secrets in CI) as the authoritative value, so a rotated operator password persists across redeploys instead of being lost. (#1570)
- Improved the AWS tenant deploy and bootstrap experience. The bootstrap CLI (`scripts/bootstrap/deploy.py`) now accepts `--yes` so its routine confirmation prompts proceed without a TTY instead of auto-aborting, and it forces `AWS_PAGER=""` at the command boundary so `aws` v2 never blocks on its pager under a non-TTY or PTY. A new `account-recovery` subcommand detects (and, with an explicit `--sweep`, deletes) state-absent control-plane residue from an incomplete prior teardown (ECR repos, KMS aliases, EventBridge Scheduler schedules, RDS parameter groups and event subscriptions, Network Firewall rule groups, Portal SSM parameters) up front, so a re-standup no longer fails one collision at a time. Detection is read-only; the sweep is ownership-verified (provider `default_tags`, or canonical name for tagless classes), never touches data-bearing resources, and is never authorized by a non-TTY alone. It refuses entirely when a live tenant is present (a portal ASG with instances or an RDS instance), so it can never treat a running tenant's resources as leftovers, and fails closed when liveness cannot be confirmed. The portal ASG health-check grace, instance-refresh warmup, and health-check type are now environment-owned Terraform variables, and the deploy workflow only cycles the portal fleet when the portal actually changed (a new portal image or a platform Terraform change), so an engine-provisioner-only deploy no longer pays the rolling portal refresh. (#1639)
- Resolved the outstanding SonarCloud new-code findings surfaced on the dev-to-main promotion. Hoisted nested builder calls out of `pytest.raises` and `assertRaises` bodies so exactly one invocation can raise inside each block (S5778) across the provisioner, bootstrap, and platform test suites; split `config/settings.py` and the shifter-ops image-tool registrar back under the file and function size caps; bounded the localhost port probe in the ops database tunnel against an out-of-range port value; collapsed a multi-return provisioner helper into a single boolean return; and corrected one assertion operand order. No runtime behavior changes (issue #1702). (#1702)
- Cleared the accumulated SonarCloud new-code quality gate on the shifter-ops MCP server (`mcp/ops`): switched the `child_process`/`net` builtins to `node:`-prefixed imports, removed an unnecessary regex escape, used `Set#size` instead of a spread-array `length`, marked the `spawnAws` PATH lookup as a reviewed-safe disposition consistent with the existing `gh`/`git` runners, and split every over-length tool registrar (and the oversized `risk.js`) into per-tool factory functions and `tools/risk/*` submodules. No change to the MCP tool surface or behavior. (#1756)
- Reduced the cyclomatic complexity of `_content_ref_from_resource` in the ACES content-delivery prep module by extracting the `spec` field-coercion into a `_spec_str` helper, satisfying the SonarCloud complexity gate. No behavior change. (#1758)
- Corrected the IAM and GitHub Runner sections of the manual-deployment guide. The IAM stack is applied by `scripts/bootstrap/deploy.py bootstrap`, not a manual `terraform apply`, and the runner fleet is the `github-runner-network` module plus persistent EC2 instances provisioned by `scripts/bootstrap/deploy.py runners`. The guide no longer documents the retired `terraform-aws-github-runner` Lambda and webhook module and now links the authoritative AWS runner provisioning runbook.
- Corrected the secrets management doc (`docs/technical/dev/secrets.md`) to reflect the post-#1250 deploy mechanism: real per-environment Terraform values live in the `TF_VARS_*` GitHub secrets and render into a gitignored `local.auto.tfvars` at deploy time, not the committed `terraform.tfvars` baselines. Added the deploy-payload secrets to the GitHub Secrets table and cross-linked the authoritative `deploy-secrets.md` checklist.
- Update the TechVault bake runbook to point at the live `techvault-scenario-bake.yml` workflow as the automated bake path (it previously described the pipeline as a follow-up).
- Add a Vale prose-linting CI gate for Markdown docs. It runs the Google documentation style (`.vale.ini`) at error level against the Markdown files each pull request changes, finishing the previously half-wired Vale setup.

### Removed

- Retired the legacy risk-register API key. The `rr_live_` `X-API-Key` credential no longer authenticates, and its management surfaces (the `/api/v1/api-keys/` endpoints, the `/risk-register/api-keys/` UI, the Django admin minting path, and the OpenAPI security scheme) are removed. The risk-register `/api/v1` surface now authenticates only via a staff/superuser session or a scoped platform `ApiToken` (`risk:read` / `risk:write`), converging the platform on a single token store (PLAT-106, follow-up to #677). The `APIKey` table and the `AuditLog` `APIKEY` enums are retained archival-only so historical comment authorship and audit rows are preserved; no live `rr_live_` key holders exist, so no key migration is required. (#1124)
- Removed the legacy experiments feature. The half-built `cms.experiments` app, Mission Control experiment script/file screens, experiment APIs, websocket routes, queue/runtime wiring, tests, specs, UAT artifacts, and legacy database tables are gone. Future experiment work will start from an ACES-backed design instead of the removed feature flag path. (#1195)
- Removed the unused `cursor-bedrock-agent` IAM service account (`platform/terraform/global/iam/cursor-bedrock.tf`) that minted long-lived static AWS access keys for Cursor IDE Bedrock access. Nothing automated consumed it, so it was standing cruft and a permanent static-credential liability in every account. The corresponding Checkov exception in `docs/adr/exceptions.yaml` is narrowed to the still-required `se-admins` IAM users, and the `cursor-bedrock` references are dropped from the manual-deployment and AWS-teardown docs. (#1473)

### Fixed

- Pre-commit Checkov now passes `--download-external-modules` to match the `security-iac` CI job, and a repo-native parity checker enforces that both surfaces share the same config path, scan directory, and blocking posture. Closes the module inline-skip local/CI divergence tracked in #147. (#147)
- Restore the Mission Control Terminal link in the CTF participant sidebar so participants can reach `/mission-control/terminal/` from CTF pages (#200). (#200)
- Deterministic upload-token expiry tests using freezegun instead of timing-sensitive TTL hacks ([#252](https://github.com/Brad-Edwards/shifter/issues/252)). (#252)
- Range provisioning and teardown ECS task identifiers are stored in separate fields so destroy no longer overwrites provisioning correlation data ([#278](https://github.com/Brad-Edwards/shifter/issues/278)). (#278)
- Engine range status-update handler now refreshes `updated_at` when persisting status changes from pub/sub events, instead of leaving the timestamp stale because `save(update_fields=...)` bypassed Django's `auto_now`. (#293)
- Fixed the Engine NGFW event handler silently losing its audit-log row. `engine.handlers._handle_ngfw_event` passed the NGFW's CMS App UUID as `AuditLog.entity_id` (a `PositiveIntegerField`), so every `ngfw.event` with an associated `app_id` failed the audit write (`Field 'entity_id' expected a number`). The handler now records `entity_id=0` and keeps the `app_id`/`instance_id` UUIDs in the audit state, so NGFW lifecycle events produce an audit row again. Surfaced by the typed event contracts above. (#296)
- Range admission now enforces at most one active range per user per source (Mission Control, CTF) with a database-level partial unique constraint, closing a check-then-create race that let concurrent launches create duplicate ranges. The friendly "you already have an active range" message is preserved, and #450's Mission Control + CTF coexistence is unaffected. Deploy prerequisite: existing duplicate active ranges must be deprovisioned through the normal range lifecycle before this migration is applied (the migration fails loud, listing the offending users, rather than deleting or status-editing rows). (#307)
- Replace the inline shell Service Discovery drain logic with `scripts/handle_sd_replacement/handle_sd_replacement.py`, a tested Python script that drains ECS registrations from Cloud Map before a ForceNew `aws_service_discovery_service` replace and restores desired counts after apply. (#315)
- Packer AMI builds now terminate transient EC2 builder instances after Linux bakes complete, and the GitHub Actions workflow always runs a defensive cleanup step keyed off Packer `run_tags` so orphaned `packer-builder-*` instances cannot keep running and incurring cost. Regression tests lock the template and workflow invariants, and the packer pre-commit hook invokes pytest via `python -m pytest` for uv 0.11 compatibility. (#342)
- Fix XAMPP unattended install in Windows services.ps1: remove unsupported `--launchapps 0` argument and add exit-code guard that fails the Packer build on installer failure. (#372)
- Hydrator failures during NGFW provisioning are now logged at the CMS service boundary, with regression coverage ensuring affected instance and app records are marked failed. (#389)
- Users can now hold a Mission Control range and a CTF range simultaneously; terminals resolve the correct range by instance UUID rather than by a global per-user active-range lookup. (#450)
- Range and experiment state no longer drifts permanently when an event delivery fails. Each correctness-critical event is now recoverable through two complementary layers: a transactional outbox (`RangeEventOutbox`) that commits atomically with the authoritative state write and a drainer (`drain_range_event_outbox`) that publishes with exponential-backoff retry, a dead-letter terminal state after max attempts, and an operator alert; and a DB-authoritative reconciler (`reconcile_range_events`) that re-reads `engine.Range` state and idempotently re-drives stale CMS and experiment projections. Consumer handlers now propagate transient failures so the worker retry and dead-letter paths engage. GCP Pub/Sub messaging gains dead-letter, retry-policy, and Cloud Monitoring alert parity with the existing AWS SNS/SQS posture. (#476)
- Repaired the CTF participant scoreboard "You" row highlight (the view now supplies `participant_id` to the row partial and the auto-refresh script) and added an own-row solve-history drill-down showing a participant's correct solves (challenge, category, points, solve time). (#521)
- Challenge statistics now compute solve rate against the event participant roster instead of only participants who submitted attempts. (#539)
- CTF flag submission cooldown rejections now return retry timing in the JSON API response, and the participant challenge page shows a rate-limit message instead of treating HTTP 429 as an incorrect flag (CTF-114). (#547)
- Restored a blocking provisioner pytest gate inside the Shifter Engine deploy workflow so image validation, image push, and ECS deploy cannot proceed from an untested provisioner commit. (#555)
- Range and NGFW provisioning now keep CMS and engine lifecycle state owned, idempotent, and reversible when cloud task dispatch fails. (#557)
- **Audit logging failures now mark portal audit health degraded instead of only logging and returning `None`.** Non-strict audit calls remain best-effort for the caller, strict audit calls still fail closed, and `/health` exposes degraded audit state through the existing coarse health-check surface. (#559)
- Fixed the GCP GDC bootstrap (`deploy.py gdc-bootstrap`) so a brand-new project reaches a usable Shifter platform end-to-end with no out-of-band steps. First-run fixes span the bootstrap and Helm chart: fresh-project IAM binding races and ETag conflicts, missing service APIs and the Artifact Registry service identity, a decommissioned Identity Platform Node runtime, the default-compute build permissions, the provisioner image build context, and a portable GKE auth-plugin install. The chart now provisions the writable volumes the portal (`/app/media`) and Guacamole client (`/home/guacamole`) need under `readOnlyRootFilesystem`, and binds a least-privilege `ctf-scheduler` workload identity so the CTF scheduler can read platform secrets and publish provisioning requests. Fixed the Identity Platform operator login page, which hung on "Loading authentication…" because the embedded Firebase config was double JSON-encoded (the view pre-serialized a config the `json_script` template filter re-encoded), leaving `config.apiKey` undefined and failing browser auth with `auth/invalid-api-key`. Replaced the page's deprecated FirebaseUI widget with a native email/password sign-in and registration form: FirebaseUI's email-first flow relies on `fetchSignInMethodsForEmail`, which returns nothing once Identity Platform's email enumeration protection (on by default) is enabled, so existing accounts had no sign-in path. The native form uses `signInWithEmailAndPassword` directly and keeps enumeration protection on. Migrated the login page from the Firebase compat SDK to the modular SDK because the compat build does not expose `TotpMultiFactorGenerator`, so first-login TOTP MFA enrollment crashed; the modular SDK provides it, and the email/password inputs are now in a proper form for password-manager support. Lowered the edge Cloud Armor SQL-injection WAF from sensitivity 4 to the recommended sensitivity-1 baseline, which was denying the legitimate session-exchange POST (a JWT body) as `body_denied_by_security_policy` and preventing login after MFA enrollment. Fixed range launch failing with a 400 for scenarios whose victim uses `os_type: from_agent` (e.g. the shipped `basic` and `ad_attack_lab`): both the dashboard agent-requirement detection (`get_agent_requirements`) and the hydrator's OS resolution (`InstanceSpec.from_template`) gated `from_agent` on the `xdr_agent` flag, so a `from_agent` victim authored with `xdr_agent: false` reported no agent requirement (the dashboard then launched agentless) and left `os_type` as the literal `"from_agent"`, which failed `InstanceSpec` validation. A `from_agent` instance now always requires and resolves against the user-provided agent regardless of `xdr_agent`. Fixed range provisioning failing with a Kubernetes `403 Forbidden` (`secrets is forbidden: User "system:serviceaccount:shifter-platform:portal" cannot create resource "secrets"`): the GCP task runner routes sensitive provisioner env vars through a per-Job Secret (creating it, patching the Job ownerReference onto it, and deleting it on the unwind path) and deletes the Job when owner-reference installation fails, but the `job-launcher` Role granted only `batch/jobs` create/get/list/watch and `pods` read. The Role now also grants `create`/`patch`/`delete` on `secrets` and `delete` on `jobs`, so range launch reaches provisioning instead of 403-ing on the Secret. Fixed agent upload (and other presigned-URL flows) failing with `you need a private key to sign credentials`: under Workload Identity the active credentials are compute-metadata credentials that carry only an access token, so the GCS client cannot sign a V4 URL locally. The storage adapter now signs via the IAM credentials `signBlob` API (passing `service_account_email` + `access_token`) when the credentials cannot sign locally, and the portal service account holds `roles/iam.serviceAccountTokenCreator` scoped to its own identity so it can sign for itself. Applied the same fix to the provisioner's storage adapter and service account: range provisioning signs a V4 GCS download URL for each instance's XDR agent so the range VM can fetch it, which hit the identical `you need a private key to sign credentials` failure under the provisioner's Workload Identity. Fixed range provisioning on GCP aborting with `KALI_INSTANCE_TYPE environment variable is required`: the provisioner's instance-type resolver unconditionally required the AWS EC2 `*_INSTANCE_TYPE` env vars, but GDC ranges size VMs from vCPU/memory/disk profiles (`GDC_*_VCPUS`/`MEMORY`/`DISK_SIZE_GIB`) via the VM Runtime asset builder and the EC2 type is consumed only by the AWS `aws_instance` path, so those vars are intentionally unset on GCP. The resolver now returns an explicit per-instance override (or an empty string) on GCP instead of demanding the AWS env contract. Fixed range provisioning never reaching the GDC range cluster: the GKE-hosted provisioner is given a bmctl kubeconfig whose server is the cluster's bundled-LB `controlPlaneVIP`, which lives on the cluster's VXLAN overlay and is unreachable from the platform VPC (the provisioner timed out reading the GDC network inventory). The bootstrap now rewrites the provisioner kubeconfig to a platform-reachable control-plane endpoint (an internal TCP load balancer fronting the control-plane nodes' `:6444` kube-apiserver port on the peered range network). Because the apiserver serving-certificate SANs only cover the overlay VIP and per-node overlay identities — never the load-balancer address — the rewritten kubeconfig sets `insecure-skip-tls-verify: true` and drops the now-unusable CA data; the channel stays TLS-encrypted and client-authenticated, and access is bounded by VPC peering scope, the range-network firewall, and the `shifter-jobs` egress NetworkPolicy. Fixed GDC range provisioning being rejected by the VirtualMachine admission webhook (`vvirtualmachine.kb.io`) with `Spec.CloudInit.noCloud.userData: Forbidden: ... should not be longer than 2048 bytes, please use 'secretRef'`: the provisioner inlined each guest's cloud-init userData directly in the VirtualMachine manifest, but Shifter's rendered userData (SSH key material, hostname, agent bootstrap) exceeds GDC's 2048-byte inline cap. The provisioner now writes userData to a per-VM Kubernetes Secret (data key `userData`) in the range namespace and points `cloudInit.noCloud.secretRef.name` at it, mirroring the existing GCS image-pull secretRef pattern; the Secret is reclaimed with the range namespace on teardown. Fixed GDC range VMs never reaching Ready (stuck in `ErrorConfiguration` with `InvalidCloudInitUserdata`: "Only `cloud config` cloud-init userdata type is supported, please make sure your userdata starts with `#cloud-config`"): the Linux GDC guest user-data templates (`kali.sh.j2`, `victim_linux.sh.j2`) rendered bare `#!/bin/bash` scripts, which AWS EC2 cloud-init runs as scripts but GDC VM Runtime rejects because it accepts only `#cloud-config` user-data. The disk import succeeded but the VirtualMachine sat in `ErrorConfiguration` until the readiness wait timed out and the provisioner tore the range down. The two GDC Linux templates now emit `#cloud-config` that embeds the original provisioning script verbatim via `write_files` and runs it once on first boot via `runcmd`, preserving identical behavior to the AWS user-data path while satisfying GDC. The AWS path is unaffected (it renders separate `terraform/modules/range/templates/*.tpl` files). Fixed GDC range provisioning failing at guest setup with `SSH on 10.200.x.y did not become available within 300s` (Connection timed out): GDC VM Runtime range VMs live on an isolated L2 (macvlan) segment on the bare-metal range cluster, which the platform-plane provisioner (a separate GKE cluster) has no L3 route to, so direct SSH from the provisioner process always timed out. Guest setup now runs from a small "setup-runner" pod created inside the range namespace and attached to the range NAD (whereabouts auto-assigns it a non-reserved IP on the segment), giving it L2 reachability to the guests; the provisioner drives the same ssh invocation via the Kubernetes pod-exec stream (`RangePodSSHExecutor`). The runner is reclaimed with the range namespace on teardown. The runner image is `GDC_SETUP_RUNNER_IMAGE` (falling back to `ENGINE_TASK_IMAGE`). The AWS SSM path is unchanged. Because the isolated GDC range cluster has no native identity for the project's private Artifact Registry (the kubelet pulled anonymously and failed with `failed to fetch anonymous token`, leaving the runner pod in `ImagePullBackOff`), the provisioner now mints a short-lived Artifact Registry access token from its own Workload Identity and plants it as a `dockerconfigjson` `imagePullSecret` on the runner pod when the runner image lives in Artifact Registry or GCR; public-registry runner images are left untouched. The `provisioner` workload identity (under which the provision Job runs) gains `roles/artifactregistry.reader` (the minimal grant that authorizes the minted token). Fixed GDC range guest setup failing host-key verification (`No ED25519 host key is known for <ip> and you have requested strict checking; Host key verification failed`): the in-range setup-runner connects with `StrictHostKeyChecking=yes` but had no `known_hosts` entry for the freshly-booted guest, so strict checking could never pass. Rather than weaken host-key checking, the provisioner now establishes trust over a trusted side channel (the pattern Google's guest-attributes host-key flow and GitHub's published-host-key guidance both prescribe): it generates a per-VM Ed25519 host keypair, installs the private half on the guest via cloud-init `ssh_keys:` (Linux guests only; the Kali and Linux-victim templates), and seeds the runner's `known_hosts` with the matching public key. The runner keeps `StrictHostKeyChecking=yes`, pins `HostKeyAlgorithms=ssh-ed25519`, and ignores the system `known_hosts` (`GlobalKnownHostsFile=/dev/null`), so it validates the guest against a key the provisioner already knows with no trust-on-first-use window. Windows guests (cloudbase-init, no `ssh_keys` module) are unaffected and leave the seam inert; the AWS SSM path is unchanged. To make the injected host key reliably *served* (cloud-init's `ssh_keys` module can run after sshd has already started with a boot-generated key, or after the NoCloud datasource is detected late), the Linux first-boot setup script now also installs the host key directly (`/etc/ssh/ssh_host_ed25519_key`) and restarts sshd, so the guest presents the provisioner-issued key regardless of cloud-init module timing. The guest-setup SSH-ready wait is also raised from 300s to 600s for the in-range (`range-pod-ssh`) transport only: GDC VM Runtime guests boot on bare metal and run a full first-boot cloud-init pass before SSH is ready, which is materially slower than the EC2/SSM path the 300s default was tuned for; the AWS path keeps 300s. Fixed GDC Kali (attacker) range guests rejecting the setup-runner's SSH key (`Permission denied (publickey,password)`) for the entire setup window, failing the range. The runner's `authorized_keys` was installed only by the first-boot `runcmd` script (cloud-init final stage), but the Kali image boots a full graphical desktop and its cloud-init final stage stalls well past the guest-setup SSH-ready window, so the key was never present in time (the host key worked because it is installed by the earlier `ssh_keys`/init-stage module). The Linux GDC templates now also install the runner key via an early `write_files` entry (`cc_write_files` runs in the init stage, before the final-stage `runcmd`), so the runner can authenticate as soon as sshd is up regardless of how long the final stage takes. The ubuntu victim path benefits from the same robustness. (The Kali final-stage stall itself is a separate, non-blocking follow-up.) Made Cortex XDR agent installation best-effort on the GDC in-range transport so a `from_agent` range still provisions end-to-end on GCP. GDC range guests sit on an isolated L2 segment with no egress or DNS (the guest's `curl` of the agent installer fails with `Could not resolve host: storage.googleapis.com`), and the agent's subsequent phone-home to Cortex/PAN-OS would be equally unreachable. The XDR install step previously raised on any failure when an agent URL was present, failing the whole provision. On the GDC `range-pod-ssh` transport the provisioner now logs the failure and continues (the range reaches READY without the agent); the AWS SSM path stays strict and still raises. Functional XDR-on-GDC is tracked separately and requires range-network egress. Fixed GDC range guest setup failing at the `set_hostname` step (`Could not set static hostname: Interactive authentication required`) once SSH connectivity was restored: the `set_hostname` bootstrap plan ran `hostnamectl set-hostname` (a root-only systemd-hostnamed/polkit action) and appended to `/etc/hosts` without escalation. The AWS SSM path runs setup scripts as root so this worked, but the GDC in-range SSH path connects as an unprivileged user (`ubuntu`/`kali`), so both operations were denied. The script now escalates with `sudo -n` when not already root (the same passwordless-sudo entitlement `set_local_password` already relies on) and leaves the AWS root path free of any sudo dependency; `/etc/hosts` is written via `tee -a` so the redirect runs under the escalated command. Fixed GDC range guests silently discarding their entire cloud-init config so none of the injected host key, `authorized_keys`, or first-boot setup script applied (the guest booted with a self-generated host key and range setup failed host-key verification). GDC VM Runtime's VM controller regenerates each guest's cloud-init secret and text-injects its own `write_files` entry (`/var/lib/cloud/scripts/per-boot/google_boot_init.sh`) immediately after the `write_files:` key, as a flush-left (indent-0) block-sequence item. The Linux GDC templates authored their own `write_files`/`runcmd` items indented two spaces (` - path:`), so the merged document mixed indent-0 and indent-2 sequence items under one key, which is invalid YAML (`expected <block end>, but found '-'`). cloud-init logged `Failed loading yaml blob ... empty cloud config` and applied none of the user-data. The two Linux GDC templates now author their `write_files`/`runcmd` list items flush-left (indent 0) so GDC's injected item and ours form a uniform sequence that parses; a regression test renders each template, simulates the GDC `google_boot_init.sh` injection, and asserts the merged document is valid YAML containing both entries. This was the underlying cause behind the host-key-verification failures the earlier host-key fixes targeted (those in-guest steps never ran because the whole config was dropped). The AWS path renders separate templates and is unaffected. Fixed GDC range guest setup still failing host-key verification even after the host key was injected: the Linux first-boot setup script installed the provisioner-issued host key, configured `authorized_keys`, and restarted sshd only *after* an `apt-get update`/`apt-get install -y openssh-server xrdp` block, but GDC range VMs sit on an isolated L2 segment with no egress to apt mirrors, so apt hung (or failed slowly) and — under `set -euo pipefail` — the script never reached the SSH-critical steps. The runner kept seeing the boot-generated host key and `Host key verification failed` never cleared. The SSH-critical block (host-key install, `authorized_keys`, `PasswordAuthentication`, sshd restart) now runs first, before any apt operation, and never depends on apt (the cloud image already ships `openssh-server`). The remaining apt step (xrdp for RDP) is now bounded with `timeout` and made non-fatal so a missing-egress apt can no longer block the already-working SSH path; the AWS path renders separate templates and is unaffected. Fixed GDC range guests applying none of their cloud-init userData (`No instance datasource found! ... Can not apply stage config, no datasource found!` on the guest serial console): the GCP guest images build from the GCE-optimized Ubuntu base (and the GCE Debian->Kali conversion), whose cloud-init is locked to the GCE datasource. GDC VM Runtime instead delivers userData via the NoCloud datasource, and the GCE metadata server (169.254.169.254) does not exist on the isolated range L2 segment, so the guest found no datasource and silently skipped the injected host key, `authorized_keys`, and the first-boot setup script (leaving guest setup unreachable behind a regenerated host key). The GCP Packer builds (`ubuntu`, `kali`) now add a final `gdc-cloudinit-datasource.sh` step that writes a `99-shifter-gdc-datasource.cfg` drop-in forcing `datasource_list: [ NoCloud, ConfigDrive, GCE, None ]` and runs `cloud-init clean --logs --seed` so the range VM performs a full first-boot run against the NoCloud seed. This is GCP-image-only; AWS images keep their Ec2 datasource (the shared cleanup script is untouched). The same step also guards cloud-init's presence: the shared cleanup runs `apt-get autoremove`, which strips cloud-init entirely from the GCE Debian->Kali image (an orphanable dependency there, unlike ubuntu-os-cloud), so the Kali guest had never run cloud-init at all and applied none of its userData; the step now reinstalls cloud-init when missing and pins it as manually-installed so autoremove cannot drop it. (#615)
- Scheduled notifications work end-to-end (CTF-804): organizers can schedule an announcement for future delivery and cancel it before it fires. Previously a scheduled announcement incorrectly delivered a generic reminder instead of its drafted content. (#667)
- Fixed CTF credential emails failing to send: `send_credentials` reversed a nonexistent `ctf:ctf_range` route, so every credentials batch was counted as failed. The email now links to the participant range page (`ctf:participant_range`). Surfaced by converting the notification service tests from internal mocks to behavioral coverage during the #683 god-module decomposition. (#683)
- Mission Control terminal tests now assert the clipboard key-event handler is registered during init. (#706)
- The built-image stack smoke (`scripts/stack-smoke/stack_smoke.sh`) now sets `CLOUD_PROVIDER=aws` in the portal container env. Production settings resolve and validate the active cloud backend at import (PLAT-2005) and fail closed when it is absent, so the smoke (which boots the built image with `ENVIRONMENT=production`) must supply the backend identity explicitly, exactly as a real AWS deploy does. Without it the container failed to start with `ImproperlyConfigured: CLOUD_PROVIDER environment variable is required`. (#726)
- Document and enforce the `[skip tests]` deployment bypass policy: deploy.yml hardcodes `skip_tests: false`, adr_guard rejects commit-message bypasses and architecture jobs gated on `inputs.skip_tests`, and CI/deployment docs describe the contract. (#760)
- Form controls in the scenario editor instance/subnet builder now have associated labels, completing the remaining input-label accessibility coverage for #786. (#786)
- Template accessibility: associate form labels with controls, replace placeholder links with buttons or real URLs, add distinct accessible names on repeated row actions, and replace interactive table rows with explicit links. (#788)
- **First-click RDP through Guacamole is now reliable.** Guacamole auth tokens are minted and served from task-local process memory, so running more than one `guacamole-client` task meant a token minted on one task was rejected when the browser's sticky session reached another, redirecting the first RDP click to the Guacamole login. The client tier is now pinned to a single task/replica on every production surface (AWS prod and GCP prod) and is decoupled from autoscaling, so it can no longer be scaled back up and silently regress; `guacd` remains the horizontally-scaled per-connection capacity tier. The PR #855 token-readiness retry is retained as defense in depth. (#928)
- Portal: the RDP/SSH access path no longer blocks on AWS Secrets Manager. Credential resolution now runs in the bounded Guacamole bootstrap worker (not the request thread), the Secrets Manager client has explicit connect/read timeouts, per-range credentials are cached for a short TTL, and terminal-websocket connect/audit work runs on a dedicated executor. A stalled Secrets Manager or a terminal connect storm no longer head-of-line-blocks `/health` and page renders on an ASGI worker. (#929)
- Long-lived browser terminal, notification, and Guacamole RDP/SSH sessions no longer drop on idle or during a portal deploy. The ALB now sets an explicit `idle_timeout` above a pinned WebSocket keepalive, the portal and Guacamole target groups drain in-flight connections via an explicit `deregistration_delay`, container redeploys stop with `docker stop --time 35` (exceeding the Gunicorn graceful timeout), an ASG termination-drain lifecycle hook holds terminating instances for a bounded window during an instance refresh, and terminal reconnects use jittered backoff so a refresh does not stampede the remaining instances. (#931)
- **AWS Network Firewall delete protection is now an environment toggle.** The range egress firewall and the portal inspection firewall hardcoded `delete_protection = true`, stranding dev `terraform destroy`/rebuild. They now read per-environment `bool` variables (dev `false`, prod `true`) that mirror the existing ALB/RDS deletion-protection convention, so dev teardown completes without manual intervention while production keeps the secure default. (#934)
- **CTF event range spin-up no longer fails itself on the multi-node portal.** A long-running `SPIN_UP_RANGES` task now heartbeats its scheduled-task timestamp, the stale-recovery window is settings-backed (`CTF_SCHEDULER_STALE_TASK_MINUTES`, default 120 min) and well above the legitimate spin-up duration, and stale recovery is a cross-node-safe conditional update, so a scheduler on one portal node can no longer mark an in-flight spin-up on another node FAILED mid-run. Participant range assignment is now serialized with a row lock (`select_for_update`) so concurrent manual and scheduled provisioning cannot double-assign a range to a participant; a benign "already has a range" race loser is skipped instead of poisoning the event spin-up as a failure. (#942)
- Fix mid-event CTF operations: extending event end reschedules auto-end, organizers can repair flags on active events, and range status respects the participant's active event context. (#945)
- **SSH terminal/connection lookups now resolve the user's active range consistently.** `get_ssh_connection_info` and `connect_terminal` previously located the range with a `provisioned_instances__contains` JSON query, diverging from `get_rdp_connection_info` (which uses `Range.get_active_for_user`) and relying on a backend-specific JSON lookup. Both SSH paths now resolve the active range the same way, removing the non-portable query while preserving the connection behavior for a user's single active range. **The NGFW detail page now lists the ranges attached to an NGFW instead of erroring.** `ngfw_detail` resolved linked ranges by coercing the CMS NGFW Instance UUID to a 128-bit integer and matching it against the Engine `Range.ngfw_instance` foreign key (a separate integer id space), so the page raised an error or showed no linked ranges. The NGFW is now correlated to its Engine instance through the shared provisioning request id, and the linked ranges render correctly. (#957)
- Cloning a custom scenario in the CMS scenario editor now copies the full persisted definition payload instead of a hardcoded three-field subset, so new definition fields are not silently dropped on clone. (#996)
- Portal EC2 bootstrap now resolves the Auto Scaling group name at launch-hook completion time with bounded retry (IMDS `aws:autoscaling:groupName` instance tag first, `describe-auto-scaling-instances` fallback) instead of caching a single early lookup. Warm-pool and early instances no longer skip `complete-lifecycle-action` and get stuck in `Pending:Wait` until the ASG ABANDONs them (which broke instance-refresh convergence and the platform Deploy step). A configured launch hook that cannot be completed now fails bootstrap loudly instead of printing a false "bootstrap complete." (#1032)
- Resolved per-environment secrets in the AWS deploy workflows so proof (and any third tenant) deploys end-to-end. `#1087` decoupled the Terraform state backend but read a single repo-level `TF_INFRA_STATE_BUCKET`, which cannot serve the per-account dev/proof/prod buckets; the reusable workflows now select `TF_INFRA_STATE_BUCKET_DEV` / `_PROOF` / `TF_INFRA_STATE_BUCKET` (prod) by environment. The range workflow's `local.auto.tfvars` and shifter.yaml egress-allowlist renders were still keyed on the binary `is_dev`, so proof fell through to prod secrets; they now select `TF_VARS_{DEV,PROOF,PROD}_RANGE` / `SHIFTER_CONFIG_{DEV,PROOF,PROD}_RANGE` by environment and fail loud when the active secret is unset, and `deploy.yml` passes the proof range tfvars plus all three `SHIFTER_CONFIG_*_RANGE` secrets through (the latter were never forwarded before). (#1096)
- Compressed the portal EC2 `user_data` with Terraform's `base64gzip()` so it stays under EC2's 25,600-byte encoded limit. The ~20 KB bootstrap script rendered to ~27 KB base64 and failed the platform apply with `InvalidParameterValue: Encoded User data is limited to 25600 bytes`; cloud-init transparently decompresses gzip user_data, dropping it to ~7.6 KB with no behavior change. (#1103)
- Fixed the portal inspection wiring assertion to recognize firewall-endpoint routes. EC2 reports a route targeting the Network Firewall (Gateway Load Balancer) endpoint under `GatewayId` as `vpce-...`, but the assertion only read `VpcEndpointId`, so a correctly-wired inspection deploy was rejected as "would blackhole egress". `_route_endpoint()` now accepts the endpoint from either field. (#1107)
- Refined the portal inspection assertion to ignore S3 / DynamoDB gateway VPC endpoint routes. After #1107 taught it to read `vpce-` targets under `GatewayId`, it also matched the S3/DynamoDB gateway-endpoint routes (managed prefix list, no CIDR destination) and rejected the deploy as pointing at the wrong firewall endpoint; `_check_endpoint_routes` now only considers CIDR-destination routes. (#1109)
- Fixed the portal deploy script not setting `ENVIRONMENT` on the container. The instance user_data set it, but `deploy_portal.sh` (deploy-time migrate and app run) did not, so `config.settings.require_environment()` (#948) failed closed with `ENVIRONMENT is required`. The `portal/ssm` module now publishes the mapped Django environment as an SSM parameter and the deploy script reads it, matching the boot path. (#1114)
- Fixed the portal target group health check failing closed (504) on non-dev tenants. `deploy_portal.sh` set `DJANGO_ALLOWED_HOSTS` to domain-only for non-dev, but the path-scoped `HealthCheckMiddleware` (#477) rewrites `/health` probe Host to `localhost`, so `localhost`/`127.0.0.1` must be allowed in every environment; without them the probe is rejected (`DisallowedHost` -> 400) and the ALB drops the portal target. Now always included, matching the GCP renderer. (#1117)
- Made portal redeploys idempotent. `deploy_portal.sh` removed old containers with a plain `docker rm` that fails for any container `docker stop` did not fully stop; the failure was swallowed and the next `docker run --name` aborted with "name already in use" (seen as ctf-scheduler on proof redeploys). Now `docker rm -f`, after the graceful `docker stop` drain. (#1127)
- Disabled portal east-west inspection on proof. proof runs a single-AZ portal but the ALB spans two AZs; per-AZ Network Firewall inspection makes the cross-AZ ALB->portal flow asymmetric, so the stateful firewall drops it and the cross-AZ ALB node returns 504. Inspection needs the portal in every ALB AZ; re-enable only with a multi-AZ portal. (#1130)
- Fixed a CTF flag-submission race: concurrent submissions could double-score a challenge and bypass the per-challenge attempt cap, because the already-solved / attempt / cooldown checks ran outside the write transaction with no row lock. Submissions now serialize per participant under `select_for_update`, backed by a partial unique constraint on a correct (participant, challenge) submission (#1135, #1137). (#1135)
- Fixed CTF team scores double-counting a challenge solved by more than one teammate. The team aggregation summed every correct submission rather than counting each challenge once, so two teammates solving the same challenge inflated the team score. Both the materialized leaderboard and the frozen/bracket scoreboard now count each challenge once, at its best (max) points (#1138). (#1138)
- Fixed CTF participant range stop/start/restart/destroy hitting the wrong range or failing with "Range not found". The CMS lifecycle entrypoints resolved the range by the legacy, nullable `RangeInstance.range_id` engine field while CTF (and the status path) identify ranges by primary key; lifecycle now resolves by PK too, so participant ranges are reliably paused/resumed/destroyed and no longer leak (#1139). (#1139)
- Fixed a CTF team-join race: concurrent joins using the same invite code could push a team past `team_size_limit` because the capacity check and the membership write were not atomic. The join now locks the team row (`select_for_update`) and re-checks capacity before adding the participant (#1140). (#1140)
- Fixed disqualifying or deleting a CTF participant stripping the platform-wide CTF Participant group and locking the user out of OTHER events they still belong to. The group is now removed (and `active_ctf_event` cleared) only when the user has no other eligible participation; otherwise the active event is re-pointed to a remaining one and the group is kept (#1142). (#1142)
- Fixed the CTF scoreboard freeze being lifted when an event is paused. `is_scoreboard_frozen` only held while the event was ACTIVE, so pausing during the freeze window revealed the live board (including post-freeze solves) before the official reveal. The freeze now also holds while PAUSED (#1143). (#1143)
- Fixed a CTF prerequisite-cycle race: concurrent "A requires B" and "B requires A" edits each passed the cycle check against the pre-write graph and together created a circular dependency, which made `assert_challenge_available_for_participant` permanently block both challenges. Prerequisite writes for an event now serialize under a row lock so the cycle check and insert are atomic (#1144). (#1144)
- Fixed a CTF participant-cap race: concurrent invites or imports could push an event past `max_participants` because the capacity check and the participant create/insert were not atomic. Both `invite_participant` and `bulk_import_participants` now lock the event row and re-check capacity inside the transaction (#1145). (#1145)
- Fixed a multi-flag CTF challenge becoming silently unsolvable when all its flag rows are removed. `verify_flag` fell back to the challenge `flag_hash`, which holds a non-hash sentinel ("multi-flag") for such challenges, so every submission was rejected with no diagnostic. The fallback now detects a non-hash flag_hash and logs a clear error instead of failing quietly (#1146). (#1146)
- Fixed a CTF challenge-file cap race: concurrent uploads could exceed `MAX_FILES_PER_CHALLENGE` and assign duplicate `order` values because the count check and the record create were not atomic. The cap re-check and order assignment now run under a challenge row lock after the S3 upload, with best-effort cleanup of the uploaded object on a lost race (#1147). (#1147)
- Fixed `api_participant_import` returning HTTP 500 when a participant array element was not an object (e.g. `{"participants": ["x"]}`). Non-object elements are now reported as per-item errors in the normal import-result envelope instead of raising an uncaught AttributeError (#1149). (#1149)
- Unblock the platform Terraform apply in environments that enable the optional RDS backup-alerts and Cognito client-secret rotation features (`alarm_email` set). The RDS backup-event subscription failed to create with `SNSNoAuthorization` because `CreateEventSubscription` runs a connectivity test-publish authorized with the *caller's* IAM identity, and the GitHub Actions deploy role lacked `sns:Publish` on the managed topics; grant it (scoped to `*-portal-*`/`*-range-*`). Also remove the confused-deputy `aws:SourceArn`/`aws:SourceAccount` conditions from the backup-alerts SNS topic and KMS key policies, which are unsatisfiable at create time (the `es:` subscription ARN does not exist yet), leaving the grants bounded by a single service principal scoped to the one topic and the one CMK. Grant the deploy role the EventBridge Scheduler permissions (plus `scheduler.amazonaws.com` in the `iam:PassRole` allow-list) the rotation reminder needs, and allow attach/detach of account-owned customer-managed IAM policies. Run database migrations as the password-authenticated master user during deploy. The portal image entrypoint switches the connection to the `rds_iam` runtime user (`portal_runtime`) before exec'ing the deploy's one-off `manage.py migrate`, but that user is created by a migration and holds only DML grants, so on a fresh database the migrate failed with `password authentication failed for user "portal_runtime"`. The deploy now sets the entrypoint's `DB_IAM_AUTH_RUNTIME=false` escape hatch for the migrate step so schema changes run as the owner; the long-running containers still switch to IAM auth. (#1168)
- Exclude the dev dependency group from the production portal image build (`uv export --no-dev`). Dev/test tooling—and the dev-only `aces-sdl` git dependency, which uv cannot emit a hash for—no longer leak into the image, so the hash-pinned `--require-hashes` install (and the `Stack smoke (built image)` CI job) no longer fails. (#1182)
- `scripts/iam-deploy.sh` now renders the Terraform backend automatically via the canonical `scripts/terraform/render_aws_backend_configs.py --stack global/iam`, resolving the real state bucket from the same per-environment variables CI uses (`TF_INFRA_STATE_BUCKET_DEV` / `TF_INFRA_STATE_BUCKET_PROOF` / `TF_INFRA_STATE_BUCKET` for prod). Previously it passed the committed `<env>.s3.tfbackend` files straight to `terraform init`, but those carry a `REPLACE_AT_BOOTSTRAP` placeholder bucket, so every run required a manual backend edit. The script also now accepts `proof` as a first-class environment alongside `dev`/`prod`. (#1218)
- Added `timeout-minutes` to the `self-hosted` jobs in the reusable deploy workflows (`_core.yml`, `_range.yml`, `_shifter-platform.yml`, `_shifter-engine.yml`) so a hung Terraform step can no longer hold a self-hosted runner for GitHub's 6-hour default and stall the (non-cancel-in-progress) deploy queue. Values are deliberately generous backstops (plan 45m, apply 120m, build/deploy 90m, push/verify/smoke 60m) chosen well above real cold-deploy durations so they never trip a legitimate long apply. This is defense-in-depth only; it does not replace fixing the underlying cause of a hang. Fixed the stack-smoke harness (`scripts/stack-smoke/stack_smoke.sh`), which booted the built portal image with `ENVIRONMENT=production` but did not supply every env var that production settings require. Under `ENVIRONMENT=production` the settings refuse dev defaults, so `required_runtime_env` raised on the first missing value and the smoke container died at `manage.py migrate` with `ImproperlyConfigured`. The harness now also passes `EMAIL_BACKEND` (console backend, since the smoke sends no mail) and `OIDC_RP_CLIENT_SECRET`, the two production-required runtime vars its `common_env` was missing, mirroring how a real deploy supplies them and without adding any ESP/SES dependency. (#1220)
- Fixed the root cause behind the self-hosted runner CI wedge (#1220's `timeout-minutes` was only a backstop): the GitHub Actions deploy runner could be deployed into the account default VPC, where a range's `private_dns_enabled` interface VPC endpoints hijacked the runner's AWS API resolution and stalled CI for ~107 minutes. The runner Terraform (`platform/terraform/global/github-runner`) now fails closed at plan/apply time if `vpc_id` is the account default VPC (or if `subnet_id` does not belong to that VPC), enforced by a `lifecycle.precondition` and pinned by a new `check_tf_runner_network` guardrail (ADR-004-R20). Valid placements are a dedicated runner VPC or the portal VPC private tier. (#1222)
- Grant the portal EC2 instance role `kms:GenerateDataKey`/`kms:Decrypt`/`kms:DescribeKey` on the user-storage S3 bucket CMK (scoped via `kms:ViaService = s3`). The bucket is SSE-KMS encrypted and its policy enforces the CMK, but the instance role was only granted the Secrets-Manager and SQS keys, so every challenge file-attachment upload and download failed with `AccessDenied` on `kms:GenerateDataKey`. Adds an `s3_kms_key_arn` variable and grant to `modules/portal/ec2`, wired from each environment's `aws_kms_key.portal_s3`. (#1258)
- Fixed the in-repo MCP servers' advertised JSON Schema dialect so Vertex-backed tool registration accepts their tool schemas without changing runtime validation. (#1306)
- Publish the range-events SNS topic ARN to the `${ssm_prefix}/range-events-topic-id` SSM parameter so portal instances wire `RANGE_EVENTS_TOPIC_ID` into the outbox drainer and reconciler. The parameter was never created, so `worker-outbox-drainer` crash-looped with `RANGE_EVENTS_TOPIC_ID is not configured` and range-event delivery via the outbox was down. (#1394)
- Fix `reconcile_range_events` crash-looping on PostgreSQL with `NotSupportedError: FOR UPDATE cannot be applied to the nullable side of an outer join`. The stale-instance query `select_related("request")`-joins a nullable FK and then locks rows; scope the lock to the base table with `select_for_update(of=("self",))` so range-event reconciliation stays running. (#1395)
- Add an `apply_immediately` input to the portal Redis module (wired into both the HA replication group and the single-node cluster) and set it per environment (dev/proof true, prod false), mirroring `db_apply_immediately`. Without it, ElastiCache defaulted to deferring node-type/engine changes to the maintenance window, so Redis sizing changes silently did not take effect at deploy time. (#1396)
- Make the post-refresh "Verify ASG image digest" deploy step tolerant of the readiness window: the image-check script now waits (bounded) for the portal container to exist before inspecting, and the verification retries with backoff instead of failing the deploy on a single transient non-Success SSM status. Previously a just-in-service instance whose container/agent was still starting failed the whole deploy even though the deployed digest was correct. (#1397)
- Fix the deploy's database-migration step timing out on a cold-instance image pull. It waited with `aws ssm wait command-executed` (a fixed ~100-second waiter) while the migrate command docker-pulls the new portal image first, which can exceed 100 seconds, failing the deploy even though the migration succeeds. Poll the command status up to its 900-second budget instead. (#1410)
- Fix the deploy's ASG verification (image digest, worker health) and run-manage-on-portal passing their multi-line SSM scripts via `--parameters` shorthand, which does not interpret `\n`, so the script arrived on one line with literal `\n` and broke (for-loop/case syntax error), failing the deploy even when the digest was correct. Pass the parameters as JSON instead, preserving real newlines. (#1413)
- Forward the post-deploy smoke's `SMOKE_*` environment into the portal container. `run-manage-on-portal` now accepts repeatable `--env KEY=VALUE` flags and renders them as `docker exec -e KEY=VALUE`, and `smoke-test.sh` forwards `SMOKE_TEST_USER_EMAIL` plus the per-variant `SMOKE_LINUX_AGENT_ID` / `SMOKE_WINDOWS_AGENT_ID` agent IDs. The container runs `run_post_deploy_smoke` under `docker exec`, which does not inherit the job environment, so those values previously arrived unset and the smoke failed on a required variable. (#1417)
- Fixed the Linux range bootstrap `verify_hostname` check to compare hostnames case-insensitively. Hostnames are case-insensitive (RFC 4343) and cloud-init on some AMIs re-applies the instance Name tag verbatim (for example `Workstation`) after `set_hostname` runs, so the live hostname could differ only in case from the value set. That failed the whole range provision for any scenario with a mixed-case instance name (such as the `Workstation` victim in `basic`/`ad_attack_lab`). Surfaced by the agent-free post-deploy smoke. Fixed self-hosted runner provisioning so it registers end-to-end without manual steps. `scripts/bootstrap/runner.py` now drives `config.sh` under `expect` (a PTY): current runner releases read the registration-token prompt through a console-only masked reader and fail (`Cannot read keys ... console input has been redirected`) when fed over redirected stdin. `expect` waits for the prompt and sends the token read from a root-owned temp file, so the token stays off `config.sh`'s argv (per the #1433 preflight) while registration actually completes. The runner user_data now also installs `expect` and the GitHub CLI (`gh`), which deploy jobs invoke on the runner (such as `_shifter-engine.yml` Deploy) and which is not in the AL2023 default repos. (#1422)
- A fresh non-prod AWS bootstrap now sets the env-suffixed Terraform state-bucket secret the deploy workflows actually read. `scripts/bootstrap` previously wrote the unsuffixed `TF_INFRA_STATE_BUCKET` for every environment, but `_core.yml` / `_range.yml` / `_shifter-platform.yml` read `TF_INFRA_STATE_BUCKET_DEV` / `_PROOF` for dev/proof (only prod reads the unsuffixed name), so a de-novo dev standup left the dev backend-render step failing on a missing secret. Bootstrap now derives the state-bucket secret name per environment exactly like the IAM role secret (`TF_INFRA_STATE_BUCKET` for prod, `TF_INFRA_STATE_BUCKET_DEV` / `_PROOF` otherwise). The CI deploy role (`platform/terraform/global/iam`) also gains Route53 hosted-zone permissions (`route53:CreateHostedZone` and the related zone/record actions) it was missing: Cloud Map / Service Discovery private DNS namespaces create a backing hosted zone, which only surfaces on a from-zero standup because established accounts already have the namespace. The operator-local deployment `shifter.yaml` is now gitignored so it is never committed. `docs/dev/deploy-secrets.md` and `scripts/bootstrap/README.md` are corrected to match, `docs/dev/deploy-secrets.md` gains a single authoritative "secrets required to stand up an AWS environment" checklist and a post-deploy-smoke (`SMOKE_*`) secrets section, and `scripts/sync-deploy-secrets.sh` gains the missing proof range / range-config records so `--env proof` can populate every secret `deploy.yml` forwards. (#1425)
- The portal image build no longer fails on the `aces-sdl` runtime dependency. When the ACES cutover (#1262) promoted `aces-sdl` from a dev-only slice to a runtime dependency it left it declared as a `git+https://` source, which `uv` cannot emit a hash for, so the hash-pinned image build (`uv export --no-dev` + `uv pip install --require-hashes`) rejected it and every AWS deploy skipped Core/Range/Engine/Platform. `aces-sdl` is now installed from its published PyPI wheel (`aces-sdl>=0.19.1`), which exports with hashes like every other dependency, so the portal image builds under `--require-hashes` again and a clean `dev` is deployable. (#1445)
- The CI permissions boundary (`shifter-<env>-ci-role-boundary`) no longer blocks the scoped `iam:PassRole` that runtime roles need. Its `DenyIamEscalation` statement denied `iam:*` unconditionally, which nullified the `iam:PassRole` the portal EC2 role uses to hand the provisioner's ECS execution role to `ecs:RunTask`, so no range could launch on AWS (`AccessDeniedException ... explicit deny in a permissions boundary`). The deny now carries an `iam:PassedToService` condition permitting only `iam:PassRole` to the platform's known services (`ec2`, `ecs-tasks`, `lambda`, `monitoring.rds`, `vpc-flow-logs`, `firehose`, `logs`, `bedrock`, `scheduler`, the same list the deploy role's own `IAMPassRole` grant uses); every other IAM action, including PassRole to any other service, stays denied. (#1452)
- Range provisioning no longer fails on a fresh database with `permission denied for table engine_range_event_outbox`. The transactional outbox table (added for #476) was never granted to the `provisioner_lambda` role, so the provisioner's status-event INSERTs were denied and every provision/teardown rolled back. A new engine migration grants `provisioner_lambda` INSERT on `engine_range_event_outbox` plus USAGE on its sequence (INSERT only; the portal-side reconciler and drainer read and update the outbox under the portal runtime role). (#1453)
- Range provisioning on a fresh database now writes the event outbox successfully. Two gaps beyond the initial outbox INSERT grant blocked the provisioner: the enqueue uses `INSERT ... ON CONFLICT DO NOTHING`, which also requires SELECT on `engine_range_event_outbox`, and `RangeEventOutbox.last_error` is NOT NULL with only a Django app-level default (no DB default), so the provisioner's raw-SQL enqueue hit a NOT-NULL violation. Engine migration `0026` grants `provisioner_lambda` SELECT on the outbox and adds a server-side `''` default on `last_error`. (#1454)
- The portal can now send SES email (CTF magic-link invites, alarm notifications) from the locked-down private tier. `django_ses` uses the SES API, but the private tier has no internet egress to the public SES endpoint, so every outbound email silently hung until timeout. A VPC interface endpoint for the SES API (`com.amazonaws.<region>.email`) is added to the portal endpoint set, keeping SES traffic on the VPC-local path like the other 18 service endpoints; no SMTP switch or credentials are required. (#1460)
- CTF magic-link registration now lands participants on their range page (`ctf:participant_range`) instead of the Mission Control dashboard, where a CTF participant would see no active range (MC ranges are separate from CTF ranges). The portal ASG also no longer fails `terraform apply` on large scale-ups: `wait_for_capacity_timeout` is set to `0` so the apply does not block on the ASG reaching capacity (new instances sit in Pending:Wait through their launch lifecycle hook, and warm-pool churn compounds it, exceeding Terraform's default 10-minute wait); readiness is gated by the instance refresh and the deploy's verify steps instead. (#1462)
- The engine deploy `validate` job now runs on the self-hosted runner class instead of `ubuntu-latest`. A GitHub-hosted runner-acquisition stall could previously cancel the job with zero steps started, which skipped the whole AWS Platform deploy stage through the fail-closed dependency chain. `validate` is fail-closed on `pull_request` (ADR-003-R5), keeps `contents: read` permissions only, and has a `timeout-minutes` backstop. (#1474)
- Dropped the unused `chat.<domain>` subject-alternative name from the portal ALB's ACM certificate. No listener rule, DNS record, or app configuration ever served `chat.<domain>`, but the extra SAN forced a second ACM DNS-validation record that silently blocked certificate issuance until the record was added by hand (hit at the proof DNS gate). The certificate now validates against the portal domain alone. (#1475)
- Fixed the TechVault scenario bake failing at `aptl lab start` "Preparing Suricata runtime volumes" with a `BackendSeedError`. The bake installs Docker as root but runs the stack (and aptl's first docker operation, the Suricata named-volume seed) as the `ubuntu` user, which was not in the `docker` group, so the seed hit a `docker.sock` permission-denied. The bake toolchain now adds `ubuntu` to the `docker` group. (#1495)
- Fixed the TechVault bake's container-count gate, which required 31 running `aptl-*` containers. The `techvault-operational` stack on aptl-labs 4.1.2 settles at 30 long-running containers plus a one-shot `aptl-cortex-index-init` that exits 0, so the bake-wait and golden-verify never reached 31 and timed out. Both checks now require 30. (#1497)
- Fixed the TechVault bake timing out at `create-image`. The bake used `aws ec2 wait image-available` (10-minute default), but the large TechVault AMI (100 GB root plus the full baked stack) takes 30-60 minutes to snapshot, so the wait failed with `Max attempts exceeded` and skipped recording the AMI in SSM even though it was finalizing normally. The bake now polls for availability with a 60-minute deadline and fails fast on a terminal image state. (#1502)
- Account bootstrap now enables EBS encryption-by-default in the deploy region. The range provisioner requires encrypted root volumes (`ec2:Encrypted=true`), and the base and scenario AMIs are unencrypted, so without account-default encryption every range launch was denied and no range could provision in a freshly bootstrapped account. The step is idempotent (enables only when currently disabled). (#1533)
- Granted the portal EC2 role `sns:Publish` on the range-events SNS topic (plus KMS on the topic's CMK). The range-event outbox drainer and reconciler run under this role and publish range status events; without the grant every publish failed with `AuthorizationError`, so ranges provisioned but stayed stuck `provisioning` in the portal forever with no connection surfaced. Wired the topic ARN into the portal EC2 module across all environments. (#1535)
- Render the TOTP MFA enrollment QR as a scannable image on the Identity Platform login page instead of showing the raw `otpauth://` URL as text. The QR is generated entirely client-side (the TOTP secret never leaves the browser) via a vendored MIT QR library, with a text fallback if the library fails to load. (#1549)
- Add a CORS rule to the GCP assets bucket scoped to the deployment's public hostname so browser signed-URL uploads/downloads (XDR agent MSIs, experiment artifacts) pass preflight; previously the bucket returned no Access-Control-Allow-Origin and portal agent uploads failed. (#1551)
- Guard the default `ACES_PACKAGE_ROOT` path computation so it no longer raises `IndexError` in the deployed container (where the app tree is flattened to `/app`); the settings import and image build previously failed. Falls back to the app root when the source-tree depth is unavailable. (#1557)
- Removed the dead `ctf-*` (`ctf-webshell`, `ctf-mailroom`, `ctf-helpdesk`, `ctf-devbox`, `ctf-vault`) `ami_type` choices from the `Packer AMI Build` workflow and the matching usage text in `scripts/ami.sh`. No `*.pkr.hcl` source backed them, so dispatching one ran `packer build -only='*.ctf-<x>'`, matched no build, and failed. (#1628)
- Fixed range provisioning intermittently failing when a Linux range guest could not register with SSM. On some boots the guest's `systemd-resolved` came up with no upstream DNS (the DHCP-provided VPC resolver was not registered), so the system resolver returned SERVFAIL, the SSM agent looped on "server misbehaving," and the guest never came online, which failed the whole range provision. The provisioner now pins the link-local AmazonProvidedDNS (169.254.169.253) in the Linux range-guest boot user_data so the agent resolves the SSM endpoint and registers. Defined once in the range Terraform and injected into both Linux guest templates. Surfaced by the agent-free post-deploy smoke. (#1632)
- Made range-guest DNS deterministic at the AMI build level so guests reliably register with SSM (issue #1633, the durable follow-up to the #1632 boot-time mitigation). The Kali and Ubuntu builds now bake a systemd-resolved `FallbackDNS=169.254.169.253` (link-local AmazonProvidedDNS) drop-in that keeps DHCP per-link DNS as the primary and only takes over when no upstream registers, exactly the boot race that made the SSM agent SERVFAIL and never come online. The Windows victim build adds a one-shot EC2Launch v2 first-boot task that resets the active adapter to its DHCP-provided DNS before the SSM agent starts. The resolver change lives in AWS-only scripts so it never leaks into the GCP or pre-promoted DC images. The Packer build workflow now gates every `/shifter/ami/*` publish behind a fresh-boot validation of the exact candidate AMI (register with SSM, resolve the regional SSM endpoint, reboot, and confirm again), and `ami_type=dc` publishes the pre-promoted `internal.shifter` id from `dc-amis.json` instead of the generalized `dc.pkr.hcl` build. The #1632 user_data pin is retained as defense in depth. (#1633)
- Fixed portal ASG instance refreshes intermittently wedging on a transient instance reporting "insufficient data to evaluate its health with Amazon EC2." The ASG health-check type was `EC2`, so refresh readiness tracked EC2 status checks rather than real application readiness. It now defaults to `ELB`, tying instance and refresh health to the ALB target group so a refresh converges when the portal is actually serving. (#1639)
- Wired the `--yes` flag into the `gdc-bootstrap` subcommand so the sole documented GCP standup entrypoint can run headlessly. `gdc-bootstrap` calls `confirm()` before creating the GDC substrate but, unlike `bootstrap`/`terraform`/`full`/`account-recovery`, never defined the `--yes` flag added in `#1639`; under any non-TTY invocation (nohup, CI) `confirm()` read EOF and the command printed `Aborted by user` and exited 0 without doing any work. The existing `set_assume_yes` dispatch already threads the flag through. (#1713)
- `gdc-bootstrap` now builds the ABM/GDC VM-Runtime substrate only for the `gdc` range backend; the default `gce` backend deploys the keyless GKE control plane straight through. The substrate created a `baremetal-gcr` service-account JSON key, which fails under orgs that enforce `constraints/iam.managed.disableServiceAccountKeyCreation` and blocked the sole documented GCP standup entrypoint even for `gce` deployments that never use the substrate. A new `--range-backend {gce,gdc}` flag (default resolved from `GCP_RANGE_BACKEND`, else `gce`) selects the path; the `gce` path creates no service-account keys. (#1716)
- `gdc-bootstrap` can now run the control-plane Terraform under the caller's Application Default Credentials via `--terraform-identity operator-adc` (default `bootstrap-sa`, overridable with `SHIFTER_GCP_TERRAFORM_IDENTITY`). The default path impersonates a dedicated tf-bootstrap service account granted `roles/owner` and mints a service-account JSON key for it; both are blocked on orgs that enforce `custom.preventPrivilegedBasicRolesForServAccounts` (no owner-on-SA) or `iam.managed.disableServiceAccountKeyCreation` (no SA keys), which made the platform apply impossible even for an operator who already holds `roles/owner`. The `operator-adc` identity skips that SA and key entirely and runs `terraform init`/`apply` directly under the operator's ADC. (#1718)
- Fixed the GCP platform-core Terraform apply failing with `"account_id" ... must be between 6 and 30 characters long` for the `provisioner-launcher` workload service account. The account_id was `${replace(name_prefix, "-", "")}-${key}`, which for `name_prefix="shifter-gcp-dev"` produced `shiftergcpdev-provisioner-launcher` (34 chars, over GCP's 30-char limit; it also overflowed in prod at 32). Long workload keys now map to a bounded account_id suffix (`provisioner-launcher` -> `prov-launcher`); the logical key still names the GKE Kubernetes service account and the output entry, and every reference resolves through the SA's `.email`, so nothing downstream changes. (#1719)
- Hardened the GCP GKE control plane and range nodes, secure-by-default for every GCP environment. The control plane is now private (`enable_private_endpoint = true`, no public IP endpoint) and reached over Connect Gateway (the cluster's fleet membership; `gcloud container fleet memberships get-credentials`) instead of a public or DNS endpoint. The provisioner node pool now runs private nodes (no external IP; egress via Cloud NAT) like the web/workers pools. `master_authorized_networks_config` is always enabled (a private endpoint requires it) and `gke_master_authorized_cidrs` may be empty, since remote access is IAM-gated via Connect Gateway rather than a network allowlist. This also fixes a fresh-project deploy deadlock: `portal_gke` no longer depends on the whole `portal_iam` module (whose `svc.id.goog` workload-identity bindings need the cluster that was waiting on them), and it adds an `enable_cicd_github_oidc` toggle (default on) so tenants whose org blocks the GitHub OIDC issuer can opt out. Together these satisfy common CIS-style org policies (disable public GKE control plane, disable the GKE DNS endpoint, forbid external VM IPs) and are strictly more secure on unrestricted orgs too. The gcp-dev CI deploy (`.github/workflows/_gcp-dev.yml`) is converted to match: it reaches the cluster over Connect Gateway (`gcloud container fleet memberships get-credentials`) instead of allowlisting the runner IP into the public control plane, pins `gke_master_authorized_cidrs` empty, enables the `connectgateway`, `gkeconnect`, and `gkehub` APIs, and grants the CI service account `roles/gkehub.gatewayEditor`, `roles/gkehub.viewer`, and `roles/container.admin` (kubectl authorizes through GKE's IAM-to-RBAC mapping). (#1723)
- Defaulted the `gdc-bootstrap` control-plane Terraform identity to `operator-adc`, which runs Terraform directly under the operator's Application Default Credentials and mints no service account and no key. This is secure-by-default: the operator already holds the project roles Terraform needs, so the previous `bootstrap-sa` default added a standing `roles/owner` service account (and a JSON key) with no capability gain, and could not run at all on orgs that enforce `custom.preventPrivilegedBasicRolesForServAccounts` or `iam.managed.disableServiceAccountKeyCreation`. `bootstrap-sa` remains available as an explicit opt-out (`--terraform-identity bootstrap-sa` or `SHIFTER_GCP_TERRAFORM_IDENTITY=bootstrap-sa`) for operators who cannot run Terraform under their own ADC. The gcp-dev CI deploy is unaffected: it authenticates via workload-identity federation and never passes this flag. The `operator-adc` path also now sets `USER_PROJECT_OVERRIDE` and `GOOGLE_BILLING_PROJECT` so Identity Platform resources apply under a user credential instead of failing with a missing-quota-project error. (#1738)
- Fixed CTF participant range access, which was broken for every isolated participant account (introduced with account isolation in `#1206`). Three defects blocked a participant from reaching their provisioned range box. First, the `CTFAccountBoundaryMiddleware` confined temporary accounts to `/ctf/*` and `/api/v1/ctf/*`, returning a 403 for the Mission Control Guacamole endpoints the range page depends on. Second, the Guacamole JSON-auth username used the account's blank email, so Guacamole rejected the token exchange with `400 "The username must not be blank."`. Third, the SPA range page pointed at a stub endpoint that could never open a box. The boundary now admits exactly the `/api/v1/mission-control/guacamole/` prefix for live participants (still gated on live participation and the forced-password-change step, still authorized per user by the underlying resolvers, and with NGFW, range lifecycle, credentials, and uploads still blocked). The Guacamole identity falls back to the account's unique `range-<hex>` username when the email is blank, and both the classic range page and the SPA workspace open each target box over RDP through the shared Guacamole bootstrap flow. The published `/api/v1/ctf/range/access/` operation is deprecated (retained for API compatibility) in favour of the per-box flow. (#1740)
- Fixed GCP range provisioning being blocked at the Kubernetes admission boundary. The `restrict-provisioner-jobs` ValidatingAdmissionPolicy validates every literal env var on a provisioner Job against the `platform-runtime` ConfigMap, but the runtime-env renderers omitted four literals the provisioner-launcher emits: `DB_NAME`, `DB_USER` (the policy lists both in `requiredLiteralEnv`; they were hydrated into the pod env from the DB secret bundle but never written to the ConfigMap), `AWS_REGION` (Django aliases it to `CLOUD_REGION`, so it is always non-empty and emitted even on GCP), and `CLOUD_PROJECT_ID` (a launcher settings fallback). Because those keys were absent from the ConfigMap the policy denied every range Job, so no GCP range could provision. `scripts/gcp/render_runtime_env.py` now emits `DB_NAME`/`DB_USER` from the `control_plane_database` output and `CLOUD_PROJECT_ID` from the real project, and the bootstrap runtime contract emits `AWS_REGION` from the region, so the ConfigMap, the launcher's forwarded env, and the admission-policy allowlist agree. (#1742)
- Fixed the AWS portal Terraform apply, which failed with `LimitExceeded: Maximum policy size of 10240 bytes exceeded` on the engine-provisioner ECS task role and blocked every `Shifter Platform` deploy. Recent Gateway Load Balancer and OpenVPN-gateway work pushed the role's aggregate inline-policy size past AWS's 10,240-byte per-role ceiling. The two largest inline policies (EC2 provisioning and GWLB provisioning) now attach as customer-managed policies, which do not count toward the inline aggregate; the granted permissions are unchanged. Applies to all AWS environments. (#1749)
- **AWS range provisioning now grants the narrowly scoped IAM and load balancer permissions required to create per-range OpenVPN gateways.** Policy guardrails also reject broader permission variants, and post-deploy smoke tests stop immediately when a range reaches a terminal failure state. (#1755)
- Update the CTF register-exchange redirect tests to expect the participant range page (`/ctf/range/`), matching the behavior change in #1462.
- **Direct pushes to `dev` and `main` now force the full quality test matrix so every package's coverage report is regenerated.** The `dev`/`main` SonarCloud analyses measure `new_coverage` over the accumulated dev-vs-main new-code period (spanning every package), but a push previously only re-ran the test jobs for packages the last-merged change touched. Packages whose `coverage.xml` was absent read as 0% covered, sinking the branch `new_coverage` gate and failing the `dev`->`main` promotion PR even though those packages are well tested. Pull-request analyses remain path-gated because their new code is only the PR's own diff.
- The platform Deploy "Run database migrations (ASG mode)" step now polls for an in-service Auto Scaling group instance for up to 10 minutes instead of failing a one-shot check. A first deploy to a fresh Auto Scaling group has no pre-existing in-service instance, so the previous immediate check raced the newly launched instances (which still needed to pull the image by digest, bootstrap, and reach InService) and aborted with "No healthy in-service instance found."
- Fixed GCE range VPC/instance creation failing with `Unknown field for Network: autoCreateSubnetworks`. The Compute resource bodies used REST/JSON camelCase field names, but they are passed to the google-cloud-compute (proto-plus) clients, which require the proto field names (snake_case, including `I_p_protocol` and `network_i_p`). Converted all range-cell resource bodies and made `disk_size_gb` an int.
- Fixed GCE range auto-cleanup failing when a provision errored before subnet-CIDR allocation. The destroy plan (`require_images=False`) now tolerates a subnet with an empty CIDR (subnets are deleted by resource name), instead of raising and leaving auto-cleanup unable to run.
- Fixed GCE range provisioning failing at subnet-CIDR allocation with a 404 on the control-plane project placeholder. The range subnet inventory now derives the project from the range VPC network self-link (the range project) instead of the control-plane `GCP_PROJECT_ID`, so ranges provision into the correct project even when the control-plane project is a deploy-overlay placeholder.
- Fixed GCE range provisioning failing at the per-range Vertex credential step with `PERMISSION_DENIED on resource project shifter-gcp-dev`. The Vertex key/secret operations now run in the range project (passed from the range plan) instead of falling back to the control-plane project, which may be a deploy-overlay placeholder.
- Fixed the gcp-dev deploy's Identity Platform bootstrap step, which failed with `KeyError: 'bootstrap_deploy'` because it loaded `scripts/bootstrap/deploy.py` by file location without registering it in `sys.modules` before executing it.
- Fixed a set of bugs that blocked a clean GCP control-plane deploy into a fresh project: the portal `/health/` storage probe and the Guacamole client both failed under `readOnlyRootFilesystem` (now backed by writable ephemeral volumes; Guacamole also gets an empty `GUACAMOLE_HOME` so its startup rebuild is not self-referential), the `ctf-scheduler` Kubernetes ServiceAccount was missing its Workload Identity annotation, and the ACES operation-record prune worker let its liveness heartbeat go stale during an idle poll interval.
- Fixed GCP range provisioning failing with `CONSUMER_INVALID` / `PERMISSION_DENIED on resource project shifter-gcp-dev`. `GCP_PROJECT_ID` and `GOOGLE_CLOUD_PROJECT` were hardcoded to a deploy-overlay placeholder in the static runtime env, so Google client libraries billed an invalid quota/consumer project. They are now rendered from the real deploy project.
- Fix Cognito/OIDC login being rejected at claims verification. AWS Cognito's UserInfo endpoint returns `email_verified` as the string `"true"` (the ID token returns a JSON boolean), but the portal required a strict boolean `True`, so every Cognito login was refused (no session created; the browser bounced to the public landing page). `email_verified` is now accepted as boolean `True` or the string `"true"` (case-insensitive) while still failing closed on `false`, `"false"`, or a missing value.
- Added the `proof` environment key to the prebaked Domain Controller AMI manifest (`shifter/packer/dc-amis.json`) so the proof account has a recorded DC AMI for the `/shifter/ami/dc` SSM parameter. The manifest previously listed only `dev` and `prod`, leaving proof standup without a prebaked DC AMI value.
- Add a private VPC interface endpoint for the EC2 Auto Scaling API in the portal VPC. The ASG launch lifecycle hook requires each booting instance to call `autoscaling:CompleteLifecycleAction` from `user_data`; without the endpoint that call egressed via NAT and timed out intermittently, leaving instances stuck in `Pending:Wait` until the hook ABANDONed them and the platform Deploy instance-refresh never converged.
- Pass `CLOUD_PROVIDER` to the portal deploy script's migrate and container runs. `config._cloud.resolve_cloud_provider` (PLAT-2005) made `CLOUD_PROVIDER` a required setting at import time and wired it into the ASG boot path (`user_data.sh`) and the engine provisioner task, but not the AWS deploy path. `deploy_portal.sh` built the migrate and run-container env without it, so any deploy of the new image aborted at the migrate step with `CLOUD_PROVIDER environment variable is required`. The deploy now publishes the backend identity to Parameter Store (`/shifter/<env>/portal/cloud-provider`) and reads it into the shared container env, matching the boot path. GCP is unaffected: it injects `CLOUD_PROVIDER` through the rendered `platform-runtime` ConfigMap.
- Portal VPC now provisions a NAT gateway per availability zone when network-firewall inspection is enabled, so each AZ's firewall endpoint egresses through a same-AZ NAT. A single shared NAT black-holed internet egress (including the Cognito OIDC token exchange in the login callback) from every AZ except the NAT's own, causing intermittent HTTP 504 errors on login.
- Made the EC2 `user_data.sh` portal redeploy force-remove containers (`docker rm -f`), matching `scripts/portal-deploy/deploy_portal.sh` (#1127), so both deploy paths are idempotent on redeploy.
- Fixed the provisioner ECS image crashing at startup with `ModuleNotFoundError: No module named 'shared.range_instantiation_policy'`, which blocked all range provisioning. The image copied only `shared/__init__.py` and `shared/range_cells.py` into `/opt/shifter-libs/shared/`, but the #1348 refactor added imports of `shared.range_instantiation_policy`, `shared.range_escape`, and `shared.log_sanitize`. The Dockerfile now copies the whole `shared` package (matching the cyberscript and installation whole-directory pattern); the package imports only from cyberscript and the standalone contract modules, so no Django dependency is pulled into the provisioner runtime.
- **Vendored minified JavaScript (`static/js/vendor/**`, such as Chart.js) is no longer measured for SonarCloud coverage.** These third-party bundles were already excluded from issue analysis via `sonar.exclusions`, but the shifter_platform jest lcov still reported their thousands of minified branch conditions as uncovered new code, which sank the `dev`->`main` promotion's `branch=main` `new_coverage` gate (chart.umd.min.js alone contributed ~4,590 uncovered conditions). Mirroring the vendor glob into `sonar.coverage.exclusions` keeps the new-code coverage gate measuring only first-party code. Genuine first-party coverage gaps surfaced during this work are tracked in #1768.
- Deflake the built-image stack-smoke job's `SKIP_MIGRATIONS` assertion. The web container's "Skipping migrations" log line is emitted by `entrypoint.sh` before it execs the server, but docker log delivery for that early output can lag the readiness probe on a busy runner, so the single-shot `docker logs | grep` check raced and intermittently failed (`SKIP_MIGRATIONS contract broken`). The assertion now polls with a bounded deadline (`SMOKE_LOG_ASSERT_TIMEOUT`, like the script's other `wait_for` checks); a genuine contract break still fails because the entrypoint logs "Running migrations" instead.
- Fixed GCE range provisioning failing when recording a subnet allocation (`value too long for type character varying(30)`). The `SubnetAllocation.vpc_id` column was sized for AWS `vpc-` ids; widen it to 255 so it holds a GCE network self-link (`projects/<project>/global/networks/<name>`).

## [3.102.0] - 2026-06-07

### Security

### Security

- **Cloud SQL SSL enforcement enabled (MEDIUM-03).** Added
  `ssl_mode = "ENCRYPTED_ONLY"` to the `ip_configuration` block of
  `google_sql_database_instance.platform` in
  `platform/terraform/gcp/modules/platform-core/main.tf`. Database connections
  over the private network that do not negotiate TLS are now rejected by Cloud
  SQL, preventing cleartext capture via compromised pods or VPC flow logs. The
  google provider (>= 6.0) removed the legacy `require_ssl` argument in favor
  of `ssl_mode`; `ENCRYPTED_ONLY` is the server-TLS-required mode that pairs
  with client `sslmode=verify-ca` against the Cloud SQL server CA (no mTLS).

## [3.101.4] - 2026-05-10

### Security

- **GCP portal runtime no longer derives its Django security posture from
  managed-TLS readiness, and now fails closed (#966).**
  `scripts/gcp/render_runtime_env.py` previously used a single
  `secure_portal_mode` flag — set by the `gcp-dev` deploy workflow only
  once the GKE `ManagedCertificate` was `Active` — to switch
  `DJANGO_DEBUG`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and
  `AUTH_PROVIDER` together, so until the certificate activated the portal
  ran with `DJANGO_DEBUG=true` (full Django debug pages) and session/CSRF
  cookies sent over plaintext HTTP. The renderer now:
  - emits the production runtime security profile unconditionally —
    `DJANGO_DEBUG=false`, `SESSION_COOKIE_SECURE=true`,
    `CSRF_COOKIE_SECURE=true`, `AUTH_PROVIDER=identity_platform`;
  - **fails closed**: a configured public hostname and managed TLS are
    mandatory; the renderer raises rather than emitting an
    `http://<ingress-ip>` runtime, so `SITE_URL` is always
    `https://<public_hostname>` (`ADR-008-R1`, `ADR-008-R3`). The
    `secure_portal_mode` / `--secure-portal-mode` switch and the
    re-render-on-promote step in `_gcp-dev.yml` are removed; the deploy
    renders once, rolls out the production-secure workload (new runtime
    ConfigMap + restart) first so the public Ingress never routes to pods
    on an older runtime, then (re-)applies the edge manifest and hard-gates
    on a load-balancer IP and on the `ManagedCertificate` becoming `Active`
    for the hostname (verifying `.spec.domains` so a stale `Active`
    certificate for a previous hostname is not trusted). The certificate
    gate can be relaxed to a warning only via a manual `workflow_dispatch`
    input (`gcp_require_active_certificate=false`) for first-time bootstrap
    before DNS is pointed at the ingress IP, and in that mode the deploy
    does a short readiness check instead of the full 60-minute Active wait;
  - drops the ingress IP from `DJANGO_ALLOWED_HOSTS` — the public hostname
    is the only externally addressable host and health-check probes hit
    `/health/`, which bypasses host validation;
  - renders the Identity Platform allow-list (`IDENTITY_ALLOWED_EMAIL_DOMAIN`,
    `IDENTITY_ALLOWED_EMAILS`) from new Terraform outputs
    (`identity_allowed_email_domain` / `identity_allowed_emails` on the
    `platform-core` module and the `gcp-dev` environment) — the same
    source the provider-side blocking function uses — instead of a literal
    and the runner environment, so both enforce one policy.

  The `gcp-dev` Terraform environment now `validation`-checks `public_hostname`
  (non-empty) and `enable_managed_tls` (`true`), so bad security inputs fail at
  `terraform apply` variable evaluation, before any infrastructure side effects.
  `scripts/gcp/` gained its own `pyproject.toml` plus `Lint (gcp scripts)`,
  `Tests (gcp scripts)`, and `SAST (gcp scripts)` CI jobs and matching
  pre-commit hooks, so `scripts/gcp/tests/` (previously run in no CI job)
  is now a real gate. The committed
  `platform/k8s/gcp/overlays/gcp-dev/platform-runtime.generated.env`
  snapshot was regenerated to match.

## [3.101.3] - 2026-05-10

### Security

- **Added default-deny Kubernetes NetworkPolicies for the GCP control plane
  (#958).** The Helm chart and static GCP base manifests now isolate
  `shifter-platform` and `shifter-jobs` by default, with explicit allow rules
  for GCLB ingress, DNS, Guacamole-to-guacd traffic, Google APIs, and generated
  private service CIDRs.

## [3.101.2] - 2026-05-10

### Security

- **Expanded Terraform-generated credential character sets in GCP platform-core
  module (MEDIUM-08).** `platform/terraform/gcp/modules/platform-core/main.tf`
  now sets `special = true` for `random_password.db_password`,
  `random_password.django_secret_key`, and `random_password.guacamole_db_password`
  to avoid alphanumeric-only generated secrets.

## [3.101.1] - 2026-05-10

### Security

- **Enabled Binary Authorization enforcement on the GKE control-plane cluster
  (MEDIUM-07).** `platform/terraform/gcp/modules/platform-core/main.tf` now
  enables the Binary Authorization API and sets
  `google_container_cluster.platform.binary_authorization.evaluation_mode =
  "PROJECT_SINGLETON_POLICY_ENFORCE"`, preventing unrestricted image admission
  and requiring cluster image verification to follow the project's Binary
  Authorization policy.

## [3.101.0] - 2026-05-10

### Added

- **Backend bundle contract and registry (#1113, PLAT-2002 / PLAT-2003).**
  New `installation.contract` and `installation.registry` modules in the
  Django-free `installation` package (`shifter/installation/`):
  - `installation.contract` defines the typed, machine-readable contract every
    backend bundle exposes (PLAT-2003) — `BackendBundle` with its
    `contract_version` (versioned independently of `shifter.yaml`'s `version`,
    fails closed on an unknown version), identity/metadata (`name`, `title`,
    `maturity`, `description`), `supported_profiles`, a per-backend
    `settings_model`, `required_tools`, `required_secrets` (logical name, the
    human-readable reference grammar, and an optional `reference_pattern` regex
    for machine validation — the root config holds references, never values),
    `generated_outputs` (the runtime/infra/CI values the backend renders, each
    tagged with owner, source, a typed `OutputDestination` — `runtime-env`,
    `kubernetes-secret`, `provider-secret-store`, `terraform-variables`,
    `helm-values`, `generated-file` — a sensitivity — `public` /
    `secret-reference` / `secret-value` — and the process roles that consume it;
    a `secret-value` output may only be placed in a secret store, never a
    ConfigMap), `validation_checks` (argv command specs — PATH-resolved
    executable name, repo-relative path arguments, no internal whitespace, shell
    metacharacters, or absolute host paths), `health_checks` (read-only probes),
    `capabilities` (which cloud-neutral `shared.cloud` / `engine/provisioner/cloud`
    protocols the backend satisfies), and `owned_files` / `docs` (repository-relative
    path roots, so validation and docs generation find a backend's files without a
    branch router). All contract models are frozen and reject unknown fields; a
    `BackendBundle` additionally rejects a `settings_model` that does not set
    `extra="forbid"`, an `argv[0]` / `RequiredTool.name` that is not a bare
    executable name, a `validation_checks` executable that is not in the same
    bundle's `required_tools`, and duplicate `name` / `logical_name` across any of
    its `RequiredTool` / `RequiredSecret` / `GeneratedOutput` / `ValidationCheck` /
    `HealthCheck` records. The contract also exposes
    `BackendBundle.validate_settings` (returns the normalized settings or raises a
    sanitized `InstallationConfigError`) / `settings_issues` /
    `secret_reference_issues` (and `RequiredSecret.matches_reference`) so consumers
    can check a `RootConfig` against the selected bundle without the rejected input
    ever appearing in an error.
  - `installation.registry` is the single registry of known backend bundles
    (`BACKEND_BUNDLES`, `get_backend_bundle`) — the OSS unit of backend
    selection (PLAT-2002). It supersedes the provisional `installation.backends`
    list; `KNOWN_BACKENDS`, `KNOWN_PROFILES`, and `ALLOWED_PROFILES` are now
    derived from it, so adding a backend or a profile is a registry entry, not a
    schema change or a branch router. The shipped `aws` and `gcp` entries are
    intentionally provisional: each pins `contract_version` and an explicit
    capability set, and carries its identity, supported profiles, owned repo
    roots, required Terraform/CLI tools (including `uv`, the executable the
    root-config check runs), the root-config validation check, a portal health
    probe, and the `CLOUD_PROVIDER` plus app/database secret-reference runtime
    bindings the platform actually consumes today (GCP's canonical `*_SECRET_ID`
    names; AWS's `*_SECRET_ARN` aliases) — but `settings_model` and each
    `reference_pattern` are left unset (any `settings` mapping and any reference
    are accepted), and the per-backend renderer / validation-check /
    infrastructure-entrypoint detail is filled in by the AWS and GCP backend
    bundle migration issues (#1116/#1117). The `local` backend is #1119.
  - `installation.schema.RootConfig` now derives backend and profile validation
    from the registry; the loader (`installation.loader.load_root_config` /
    `validate_root_config_file`) then runs the selected backend bundle's
    `settings` and secret checks and returns the bundle's normalized settings. The
    secret checks flag a `RequiredSecret` the backend declares with no `secrets:`
    entry (the value may be `PROMPT_REFERENCE` — the literal `prompt` — to collect
    it at deploy time, or a provider secret name / GitHub Actions secret name / env
    var), a `secrets:` entry for a logical name the backend does not use (catches
    typos before deploy), and a reference that does not match the backend's
    `reference_pattern` when one is declared. Root-shape and backend-specific
    problems are aggregated into one `InstallationConfigError`, each as a
    path-anchored `ConfigIssue` (e.g. `settings.region`, `secrets.django_secret_key`)
    that never echoes the rejected input — a backend setting or secret reference
    could be sensitive. Behavior is unchanged for the shipped `aws`/`gcp` backends'
    *settings* (still any mapping), but each of those backends now requires its
    declared secrets (`aws`: `django_secret_key`, `db_password`; `gcp`:
    `django_secret_key`) to have a `secrets:` entry.
  - The provisional `installation.backends` module is removed; import the
    registry constants from `installation` (or `installation.registry`) instead.

## [3.100.4] - 2026-05-10

### Changed

- **GCP Cloud SQL availability is now configurable with regional HA as
  the module default.** The GCP platform-core Terraform module exposes
  `cloud_sql_availability_type`, defaults it to `REGIONAL`, validates
  accepted Cloud SQL values, and keeps the `gcp-dev` environment on
  `ZONAL` for lower-cost development deployments.

## [3.100.3] - 2026-05-10

### Security

- **Hardened GCP Terraform state bucket bootstrap in CI.** The
  `.github/workflows/_gcp-dev.yml` deploy path now sets a 30-day GCS retention
  policy for the Terraform backend bucket, enforces public access prevention on
  creation, and configures bucket IAM so the configured CI service account gets
  the required backend roles while broad/public bucket bindings are removed.

## [3.99.3] - 2026-05-10

### Changed

- **Quality workflows now use GitHub-hosted runner capacity instead of
  queueing entirely on the custom EC2 runner pool.** Portable lint,
  architecture, SAST, security, and test jobs in
  `.github/workflows/_quality.yml` now run on `ubuntu-latest`; deploy,
  image-build, Packer, and environment-mutating workflows remain on
  `self-hosted`. Runner docs now record the GitHub Actions limitation
  that `ubuntu-latest` and self-hosted runners cannot be combined into a
  native priority/fallback pool, so Shifter balances capacity by routing
  job classes to different runner pools.

## [3.99.2] - 2026-05-10

### Changed

- **DC domain password secret is now Terraform-managed end to end (#760
  follow-up).** `platform/terraform/modules/engine-provisioner/secrets.tf`
  replaces the `data "aws_secretsmanager_secret"` reference (which required a
  manual, per-environment `aws secretsmanager create-secret` +
  `put-secret-value`) with the same pattern the portal RDS credentials and
  Django-app secret use: a `random_password` generated at apply time, stored
  in `aws_secretsmanager_secret.dc_domain_password` via an
  `aws_secretsmanager_secret_version`. `terraform apply` for the portal stack
  now creates the secret with a live `AWSCURRENT` value — no out-of-band
  bootstrap step — and the `iam.tf` / `outputs.tf` / `task_definition.tf`
  references switch from the data source to the resource. The DC-secret
  "is it populated yet?" preflight is removed from
  `platform/terraform/modules/portal/ec2/user_data.sh` and the
  `_shifter-platform.yml` deploy job (the secret always carries a value now).
  Docs updated: `dev/secrets.md` (Provisioning / rotation runbook),
  `platform_infrastructure/ami-management.md` (the DC AMI build reads the
  Terraform-seeded value rather than choosing one). Rotation is now one
  `terraform apply -replace='module.engine_provisioner.random_password.dc_domain_password'`.

## [3.99.1] - 2026-05-10

### Security

- **Removed hardcoded prebaked Domain Controller Administrator password
  from committed sources (#760).** The literal `dc_domain_password`
  value previously committed in
  `platform/terraform/environments/{prod,dev}/portal/terraform.tfvars`,
  the matching Python fallback in
  `shifter/shifter_platform/engine/services._get_windows_rdp_fallback`,
  and the GDC VM Runtime DC fallback in
  `shifter/engine/provisioner/gdc_vmruntime_assets._get_windows_admin_password`
  have been removed. The engine-provisioner Terraform module now
  references an out-of-band-managed `aws_secretsmanager_secret` named
  `shifter-{env}-portal-dc-domain` via a `data` source; operators
  create AND populate the secret with `aws secretsmanager create-secret`
  before the first `terraform apply` (see `secrets.md` "Bootstrap (fresh
  environment)"). The engine ECS task injects the value via the task
  definition's `secrets = [...]` block; the portal Django container
  reads the same secret at startup through `entrypoint.sh` and the
  `DC_DOMAIN_PASSWORD_SECRET_ARN` env var plumbed through the
  `portal/ssm` and `portal/ec2` modules. The Windows-DC RDP credential
  lookup in `engine.services` is provider-scoped via the portal's
  `CLOUD_PROVIDER` env, fail-loud (raises `ValueError` mapped to HTTP
  400 by mission_control) when the secret is unconfigured or when an
  instance's provider does not match the portal's deployment provider
  (closes the cross-provider leak). The GDC VM Runtime DC provisioner
  requires the same `DC_DOMAIN_PASSWORD` env (no literal fallback for
  the DC role; non-DC Windows victim fallback remains pending separate
  follow-up). Adds an `adr_guard` check `no-plaintext-secrets-in-tfvars`
  (ADR-004-R7) that scans
  `platform/terraform/environments/**/*.tfvars` for string-literal
  assignments to `*_password` / `*_secret` / `*_token` / `*_key` /
  `*_credentials` variables (with multi-line wrapper, HCL `#`/`//`/`/* */`
  comment, and object/array detection) and fails the architecture gate
  if any re-appear; complements gitleaks (which catches high-entropy
  random strings) by catching low-entropy committed credentials
  gitleaks ignores. Variables whose name ENDS WITH a public-material
  suffix (`public_key`, `public_cert`, `pubkey`, `authorized_keys`,
  etc.) are exempt; `public_key_password` and similar names that mix
  a public-material fragment with a secret suffix stay flagged.
  `*.tfvars.example` files are skipped. The previously exposed value
  must be rotated operationally; the prebaked DC AMI Administrator
  password and the Secrets Manager value must match.

## [3.99.0] - 2026-05-10

### Added

- **Root installation config schema (#1112, PLAT-2001 / GEN-2001 /
  GEN-2002).** New `installation` package (`shifter/installation/`)
  defining `shifter.yaml` — the single authoritative root file an OSS
  deployment edits to choose and configure a backend bundle. It ships:
  - Typed Pydantic v2 models (`installation.schema.RootConfig`,
    `DeploymentConfig`) for the root keys `version`, `backend`,
    `deployment` (`name`, `domain`, `profile`), `secrets`, and
    `settings`. The schema validates the *shape* of the root config:
    unknown top-level keys, unknown `deployment` keys, missing required
    keys, an unknown backend, an unsupported profile/backend
    combination, a malformed deployment name or domain, duplicate YAML
    mapping keys at any level (which PyYAML would otherwise silently
    collapse), and `secrets` values that are clearly raw key material
    (multi-line, PEM-headered, or implausibly long — capped at 1024
    characters, well above the longest realistic provider reference) are
    all rejected — and every problem is reported together — *before*
    Terraform, Helm, Django startup, workers, or deployment scripts run.
    `secrets` holds *references* (a provider secret name, a GitHub
    Actions secret name, an env var, or `prompt`), never values; the
    schema cannot tell a short secret value from a secret *name*, so the
    precise per-provider reference grammar — and the contents of
    `settings`, and which settings each backend requires — are validated
    by the selected backend bundle's contract (#1113), not by the root
    schema. The schema models exactly one standalone deployment (no
    fleet / install registry / cross-install orchestration keys). The
    known backends and the profiles each allows live in
    `installation.backends` as a provisional registry that #1113
    supersedes; the `local` backend is #1119.
  - `installation.loader.load_root_config` /
    `validate_root_config_file` — load and fail-fast validate a config
    file, aggregating all problems on `InstallationConfigError.issues`.
    The error model (`installation.errors.ConfigIssue` /
    `InstallationConfigError`) never carries the rejected input, so a
    mistyped secret cannot leak through an error message; YAML parse
    errors are reported from the parser's own position/description only,
    not from the file content.
  - The `shifter-config validate [PATH]` CLI (also `python -m
    installation validate`), run from the repo root via `uv run
    --project shifter/installation`: exits `0` with `OK — root config
    shape is valid (backend=…, profile=…)` for a valid config, or `1`
    with each problem on stderr; defaults to `./shifter.yaml`.
  - Worked, machine-validated example configs for the AWS and GCP
    backends under `shifter/installation/examples/` (the test suite
    loads every file there through the same parser, so an example cannot
    drift from the schema).

  Wired into the standard per-package CI jobs (`installation-lint`,
  `installation-sast`, `installation-tests` in
  `.github/workflows/_quality.yml` — on GitHub-hosted ephemeral runners,
  since they execute PR-controlled Python), pre-commit (ruff /
  ruff-format / bandit / pytest hooks scoped to `shifter/installation/`),
  SonarCloud (`sonar.sources` / `sonar.tests` / coverage report path),
  and recorded as ADR-011 evidence in `docs/adr/index.yaml`. The package
  is built into the Shifter Platform Docker image alongside `cyberscript`
  (so the Django app, workers, and provisioner can `import installation`
  when #1114 derives runtime config from the root config). The
  architecture note `docs/architecture/root-configured-backend-bundles.md`
  records the resolved root-config filename. Django-free (pydantic v2 +
  PyYAML only) so scripts, CI, and the Django app can all use it.

## [3.98.1] - 2026-05-10

### Fixed

- **Git worktrees now symlink the repo-root `.env`.**
  `scripts/setup-worktree.sh` only linked the platform `.env` and the
  venvs, so a worktree had no repo-root `.env`. The `ground-control` MCP
  server forwards `GROUND_CONTROL_API_TOKEN` from that file as a bearer
  token, so every Ground Control backend call returned `401` in any
  worktree. The setup script now also links `$MAIN_REPO/.env` to the
  worktree root.

## [3.98.0] - 2026-05-10

### Security

- **Locked Pod Security Standards on K8s Deployments via a new ADR
  guard check (#951).** Added the
  `k8s-deployment-security-context` check to
  `scripts/adr_guard/adr_guard.py`, wired into ADR-006-R2 in
  `docs/adr/index.yaml`, the ADR guard's `ci` level (kept out of
  `fast` so the system-Python `adr-guard-fast` hook stays
  dependency-free), and a dedicated `adr-guard-k8s` pre-commit hook
  scoped to `platform/k8s/gcp/base/*.{yaml,yml}` and
  `platform/charts/shifter/`. The check validates two enforcement
  sources:
  - **Base manifest snapshots**: PyYAML's `safe_load_all` parses every
    `.yaml`/`.yml` document under `platform/k8s/gcp/base/` (recursive)
    and applies the rule to every document whose `kind` is
    `Deployment` (kind-based filtering rather than filename-based, so
    a Deployment shipped under any filename or extension is scanned).
  - **Helm chart rendered output** (per ADR-007, the chart is the
    authoritative deployment contract; base manifests are supporting
    snapshots): the check shells out to `helm template
    platform/charts/shifter -f <values-file>` for each entry in
    `HELM_VALUES_FILES` (`values-gcp-dev.yaml`, `values-gcp-prod.yaml`)
    and applies the same rule to every Deployment in the rendered
    output. Catches regressions where a chart template or values file
    removes a required securityContext field even when the base
    snapshots remain compliant. Multi-document files and
  indentless YAML sequences are supported; non-mapping
  `spec`/`spec.template`/`spec.template.spec` shapes produce
  actionable violations rather than crashing the guard. The check
  fails CI if any pod template is missing
  `seccompProfile.type: RuntimeDefault`, or if any container OR
  initContainer's *effective* context (after pod-level inheritance
  for `runAsNonRoot`/`runAsUser`/`runAsGroup`) is missing
  `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`
  (with no `capabilities.add` key at all — empty list is also
  rejected), `readOnlyRootFilesystem: true`, `runAsNonRoot: true`,
  a positive integer `runAsUser`/`runAsGroup` (booleans rejected;
  Python's `bool` is a subclass of `int`), or sets `privileged:
  true` or a container-level `seccompProfile.type` other than
  `RuntimeDefault`. PyYAML (`pyyaml>=6.0`) and Helm (`v3.15.4`) are
  the new ADR-guard runtime dependencies: the `adr-conformance` job
  in `.github/workflows/_quality.yml` installs both **hermetically
  per job** — pip is bootstrapped via the stdlib `ensurepip` module
  (the self-hosted Amazon Linux runner's system Python ships without
  pip and does not have Python 3.12 available for
  `actions/setup-python`), then PyYAML via
  `pip install --no-deps --target ${RUNNER_TEMP}/py-deps` with
  `PYTHONPATH=${RUNNER_TEMP}/py-deps` on the run step, and Helm via
  the official `get.helm.sh` release tarball extracted to
  `${RUNNER_TEMP}/helm-bin/` and added to `$GITHUB_PATH` (no
  `pip install --user`, no `sudo mv` to system paths, no mutable
  host state that can leak between jobs on the self-hosted runner).
  The `adr-guard-tests` job installs PyYAML the same way; the
  chart-rendering test uses a fake helm shim, not real helm.
  Locally the dedicated `adr-guard-k8s` pre-commit hook
  (`language: python`, `additional_dependencies: pyyaml>=6.0`)
  provisions PyYAML in an isolated venv so the system-Python
  `adr-guard-fast` hook stays dep-free; helm is a developer
  prerequisite shared with the existing `helm-lint-shifter-chart`
  hook. Robustness extras: empty or missing `containers` lists are
  explicit violations (preventing chart regressions that drop the
  container list from silently passing as long as pod-level seccomp
  is set), and a configured Helm values file that is deleted or
  renamed produces a violation rather than being silently skipped.
  The k8s check is wired into the ADR guard's `ci` level only;
  `fast` stays PyYAML- and helm-free. Documented in
  `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md`.
  Tests in `scripts/adr_guard/tests/test_adr_guard.py` cover the
  negative paths (missing/wrong seccomp, allowPrivilegeEscalation
  true, partial capability drop, capability re-grant, container-level
  seccomp override, privileged true, missing fields, UID 0, boolean
  UID/GID, unsafe initContainer), the robustness paths (`---`
  separator, indentless sequences, empty flow `securityContext: {}`,
  non-mapping `securityContext`, multi-document files, kind-based
  filtering of unsuffixed Deployment files, non-Deployment kinds
  ignored, pod-level inheritance honored, container override beats
  pod default), and the real-repo regression. Removed the
  now-redundant `ADR-006-R2` exception from
  `docs/adr/exceptions.yaml` (filed when the manifests lacked
  security contexts; the manifests have since been hardened to
  1000/1000 for app/guacd and 1001/1001 for guacamole-client via
  `platform/charts/shifter/templates/_helpers.tpl`, and the new
  check now enforces the structural fields). Existing kube-linter
  checks (`run-as-non-root`, `no-read-only-root-fs`,
  `privilege-escalation-container`) continue to run as
  defense-in-depth. The unrelated ADR-006-R3 NetworkPolicy exception
  remains.
- **Provisioner container now runs with read-only root filesystem and a dedicated
  writable workspace volume (#1103, follow-up to #950).** `shifter/engine/provisioner/Dockerfile`
  no longer chowns `/app` or copies source with `--chown=appuser`; application code
  stays root-owned and immutable. Terraform writes are redirected to
  `${TERRAFORM_WORKSPACE_DIR}` (default `/var/run/provisioner/workspace`):
  `shifter/engine/provisioner/terraform_base.py` adds `_stage_workspace()` /
  `_cleanup_workspace()` so each Terraform apply/destroy call copies the read-only
  module source from `/app/terraform/modules/<name>` into a per-request workspace,
  runs `terraform init`/`apply`/`destroy` from the staged path, and removes the
  staged tree (with any `terraform.tfvars.json` that may carry secrets) on both
  success and failure paths. The dynamic GCP Job factory at
  `shifter/shifter_platform/shared/cloud/gcp/task_runner.py` now sets
  `securityContext.readOnlyRootFilesystem=true`, `runAsNonRoot=true`,
  `runAsUser=runAsGroup=1000`, `allowPrivilegeEscalation=false`,
  `capabilities.drop=["ALL"]`, and `seccompProfile=RuntimeDefault`, plus four
  explicit `emptyDir` volumes (the workspace memory-backed) for
  `/var/run/provisioner/workspace`, `/tmp`,
  `/home/appuser/.terraform.d/plugin-cache`, and `/home/appuser/.pulumi`. The ECS
  task definition under `platform/terraform/modules/engine-provisioner/`
  enables `readonlyRootFilesystem` and adds matching ephemeral `volume`/`mountPoints`
  entries. Tests under `shifter/engine/provisioner/tests/test_dockerfile.py` and
  `shifter/engine/provisioner/tests/test_terraform_base.py` lock in the structural
  contract; the opt-in (`RUN_DOCKER_TESTS=1`) Docker smoke test now launches the
  container with `--read-only` and tmpfs mounts and asserts `/app` is not writable
  while the workspace path is. Dead `_get_working_dir()` helper in
  `shifter/engine/provisioner/main.py` (never called, misleading) removed.
  Source: codex review of #950 (cycle 2).
- **Provisioner container now runs as non-root (#950).** `shifter/engine/provisioner/Dockerfile`
  creates `appuser:1000 / appgroup:1000` (matching the existing pattern in
  `shifter/shifter_platform/Dockerfile`) and drops privileges via
  `USER 1000:1000` before `ENTRYPOINT` (numeric form so Kubernetes
  `runAsNonRoot` admission can verify it). Terraform/Pulumi binary installs
  and `pip install` still run as root during build. This reduces the blast
  radius of a container compromise — an attacker who exploits the running
  process no longer has root inside the container — but does not eliminate
  the risk of host root via a kernel-level container escape. `/app` is
  chowned to the runtime user, `HOME` / `TF_PLUGIN_CACHE_DIR` /
  `PULUMI_HOME` are set explicitly, and the corresponding cache
  directories under `/home/appuser` are pre-created so Terraform/Pulumi
  can write under the non-root identity. Added
  `shifter/engine/provisioner/tests/test_dockerfile.py` as a structural
  regression gate plus an opt-in (`RUN_DOCKER_TESTS=1`) Docker smoke
  test that verifies the running container's UID, HOME, and writable
  cache paths. Source: GCP Red Team Report (CRITICAL-01).

### Changed

- **Stripped Cortex/Palo branding from UI surfaces (#1101).** Renamed
  `static/css/xdr-theme.css` / `xdr-sidebar.css` / `xdr-dropdown.css` to
  neutral `theme.css` / `sidebar.css` / `dropdown.css`; renamed
  `static/js/xdr-dropdown.js` to `dropdown.js`, the `XdrDropdown` class
  to `ShifterDropdown` (with `globalThis.ShifterDropdown` and
  `_shifterDropdown` element marker), and the `.xdr-dropdown*` selectors
  to `.shifter-dropdown*`; renamed `--xdr-*` CSS custom properties and
  `.xdr-dark-theme` to `--theme-*` and `.theme-dark`; replaced Cortex
  green (`#00d26a` / `#0c6`) and Palo blue (`#128df3`) accents with
  desaturated slate (`#94a3b8`) on a dark neutral palette (WCAG AA on
  dark) — system-state indicators (active/online dot, success metrics)
  use neutral system green `#22c55e` rather than Cortex green; replaced
  the Cortex-derived logo SVGs and the "CORTEX SHIFTER / by palo alto
  networks" wordmark in `partials/icon_sidebar.html` and
  `partials/ctf_participant_sidebar.html` with a plain text "SHIFTER"
  wordmark + interim slate "S" mark; replaced the Cortex-style green
  favicon PNG with a neutral SVG favicon; rebuilt `coming_soon.html`
  with CSS-styled text instead of the cyberpunk-green Shifter PNG
  marks. Functional product references (XDR/XSIAM in instructional
  copy, the `xdr_agent` scenario schema field, VM-Series authcode flow,
  "Cortex BYOT" scenario name, NGFW-to-XDR/XSIAM data source setup) are
  preserved per #1101 scope. Final visual identity remains tracked under
  #1097 / UX-002 (still DRAFT).

### Fixed

- **Dev RDS class/storage/engine changes now apply during the deploy.** Both
  the portal RDS module (`platform/terraform/modules/portal/rds/`) and the
  Guacamole RDS module (`platform/terraform/modules/guacamole/`) now expose
  an `apply_immediately` input. Dev environments set it to `true`; prod
  keeps it `false` so prod RDS changes continue to land through the
  configured maintenance window. The May 2026 `db.t3.small → db.m5.xlarge`
  bump for `dev-portal-guacamole-db` was accepted by `terraform apply` but
  queued in `PendingModifiedValues` for the maintenance window — the live
  class never changed during the event (#1085). Note: `apply_immediately`
  covers changes AWS can perform during the apply (class, storage, engine
  version, dynamic parameter-group fields). Static parameter changes and
  major version upgrades still require an explicit reboot.
- **Post-apply RDS gate in CI (dev only).** A new check
  (`scripts/check_rds_pending_modifications/`) runs after `terraform apply`
  in the dev branch of `_shifter-platform.yml`. It reads the portal env's
  Terraform outputs (every `*_db_instance_id` output), calls
  `aws rds describe-db-instances`, and fails the deploy job if any managed
  RDS instance still has non-empty `PendingModifiedValues`. A successful
  apply that leaves pending mods is treated as an incomplete deploy. Prod
  is exempt by design.

## [3.97.0] - 2026-05-07

### Changed

- **In-browser terminal copy/paste**. xterm.js shows selection highlighting but
  never wired the system clipboard. Added a custom key handler:
  Ctrl+Shift+C copies the current selection via `navigator.clipboard.writeText`,
  Ctrl+Shift+V pastes via the existing `sendInput`. Both fall through silently
  on permission denial.
- **Dev guacamole DB instance class** bumped from `db.t3.small` to
  `db.m5.xlarge` (`platform/terraform/environments/dev/portal/terraform.tfvars`).
  The t3.small was undersized at BSides Ottawa — sessions took 4–5 retries
  under sustained load. m5.xlarge gives 4 vCPU / 16 GiB and no burst-credit
  cliff. Note: rds module's `apply_immediately` defaults to false, so the
  class change is queued behind RDS's next maintenance window.

## [3.96.0] - 2026-05-07

### Added

### Fixed

- **Engine DC SSM-wait timeout 600s → 1800s** (`_run_dc_setup` in
  `shifter/engine/provisioner/main.py`). The Packer-built shifter-dc
  AMI runs through 2-3 sysprep reboot cycles on first boot before
  SSM agent is reliably online — empirically 13-15 minutes between
  launch and stable SSM. The 600s ceiling caused the provisioner to
  give up early and tear ranges down. 1800s gives sysprep room; on
  a warm DC AMI the wait still returns in seconds.
- **`ec2:ModifyInstanceMetadataOptions` added to the engine
  provisioner ECS task role** (`platform/terraform/modules/engine-provisioner/iam.tf`).
  Required for the new IMDS hop-limit bump above. Granted alongside
  the existing `ec2:RunInstances`, `ec2:ModifyInstanceAttribute` etc.
  in the `EC2InstanceOperations` statement.

## [3.95.17] - 2026-05-04

### Security

- **Closed shell-injection paths in `mcp/ngfw` (#759).** `run_command`,
  `show_system_info`, and `show_routes` previously interpolated
  user-controlled command strings into shell pipelines on two
  boundaries — every aws-cli invocation in `mcp/ngfw/index.js` ran
  through `execSync()` shell strings on the local host, and the SSM
  `AWS-RunShellScript` payload that ferried PAN-OS commands to the
  NGFW used `echo ${JSON.stringify(command)} | ssh ...` on the portal
  jump host. `JSON.stringify` only produces a double-quoted shell
  string, so payloads containing `$(...)` or backticks were evaluated
  by the portal shell before reaching SSH. Both boundaries are now
  closed: AWS-CLI argv-array helpers (`buildAwsArgv`, `awsExec`,
  `awsJson`, `awsText`, `buildSsmSendCommandArgs`) now live in a
  shared `mcp/shared/aws-helpers.js` module re-exported by both
  `mcp/ngfw/lib.js` and `mcp/ops/lib.js`, so a single change-site
  governs the argv-array contract across MCP servers. Errors carry an
  `aws <service> <op>: <stderr>` operation label so MCP handlers
  surface localized failures. `buildNgfwSshCommands` base64-encodes
  the PAN-OS command (with a trailing newline so the line-oriented
  appliance gets Enter) into the SSM payload; the portal decodes it
  (`base64 -d`) and pipes the bytes into `ssh`'s stdin instead of
  evaluating them. Per-invocation `/tmp/ngfw-<uuid>.pem` paths prevent
  concurrent calls from clobbering each other's key material. `set
  -e` plus `trap 'rc=$?; rm -f <path>; exit $rc' EXIT` preserves the
  SSH/PAN-OS exit code through cleanup so SSM reports failed PAN-OS
  calls as failed. `child_process.execSync` is no longer imported
  from `mcp/ngfw/index.js`. `validateNgfwIp` adds a strict IPv4 check
  on the SSH target as defense in depth. `runNgfwCommand` throws an
  explicit timeout error after 60s and only retries the genuine
  `InvocationDoesNotExist` transient during polling — other AWS
  errors propagate immediately. Regression coverage:
  `mcp/ngfw/lib.test.js` covers argv builders, `awsExec` runner
  injection with operation-labeled errors, SSM JSON payload shape,
  base64 round-trip across `$()`, backticks, quotes, semicolons,
  ampersands, pipes, newlines, and the heredoc terminator;
  `mcp/ops/spawn-roundtrip.test.js` (now covering both packages
  through the shared `spawnSync` boundary) proves Node forwards argv
  elements byte-for-byte; and `mcp/ngfw/script-execution.test.js`
  runs the generated SSM command list under `/bin/sh` with a stub
  `ssh` and asserts the EXIT trap preserves the failing exit code
  (42 round-trips end-to-end) and removes the temporary key file in
  both success and failure paths.
  Component-local guardrails recorded in `mcp/ngfw/SECURITY.md`. The
  `ADR-010-R1` and `ADR-010-R2` exceptions for `mcp/ngfw/*` are
  removed from `docs/adr/exceptions.yaml`; ADR-010 evidence now lists
  the shared module and ngfw artifacts.

## [3.95.16] - 2026-05-04

### Security

- **Closed shell-injection paths in `mcp/ops` (#763).** The shared
  `aws()` and `awsText()` helpers, `getInstancePlatform`,
  `fetchCredentials`, `ensureTunnel`, and `start_portal_test_tunnel`
  previously interpolated user-controlled strings into shell command
  strings and ran them via `execSync()`. Three documented payload
  paths reached the host shell — `filter_log_events` (CloudWatch
  filter pattern), `ssm_send_command` (SSM `--parameters` JSON), and
  `run_manage_command` (Django management commands wrapped in JSON) —
  with several other tools sharing the same unsafe abstraction.
  Every aws-cli invocation in `mcp/ops/index.js` now goes through
  argv-array helpers in `mcp/ops/lib.js` (`buildAwsArgv`, `awsExec`,
  `awsJson`, `awsText`) backed by `spawnSync`, so payloads containing
  `$()`, backticks, single and double quotes, semicolons, ampersands,
  pipes, spaces, and newlines are forwarded as literal argv elements
  rather than evaluated by the local shell. `child_process.execSync`
  is no longer imported from `mcp/ops/index.js`. Regression coverage
  in `mcp/ops/lib.test.js` (argv-builder and runner-injected
  `awsExec`) and `mcp/ops/spawn-roundtrip.test.js` (proves Node's
  `spawnSync` preserves literal argv across all metacharacters)
  guards the new boundary. Component-local guardrails recorded in
  `mcp/ops/SECURITY.md`.

## [3.95.15] - 2026-05-03

### Changed

- **Split `cms.handlers` into per-domain handler modules.** The 389-LOC
  `shifter/shifter_platform/cms/handlers.py` god module is replaced by a
  `cms/handlers/` package: `range_events`, `experiment_bridge`, `ctf_bridge`
  (signal fire), `ngfw_events`, with the package `__init__` owning the
  prefix dispatcher. Public surface preserved via re-exports —
  `cms.handlers.process_event` (referenced as a string in
  `config/settings.py` for the SQS worker), `parse_sns_message`,
  `process_range_event`, `process_ngfw_event`, and
  `notify_experiment_on_range_ready` all keep their existing import paths.
  Runtime routing, signal wiring (`cms.signals.range_status_changed`), and
  experiment-failure semantics are unchanged. New `TestProcessEvent` cases
  cover the previously-untested experiment route. Tracked under #1055 (#1068).
- **Consolidated SNS envelope unwrapping at `shared.messages.envelope.parse_sns_message`.**
  Four near-identical copies — in `cms/handlers/envelope.py`,
  `engine/handlers.py`, `mission_control/handlers.py`, and
  `cms/experiments/handlers.py` (as `_parse_message`) — are replaced by a
  single shared helper. The CMS, Engine, and Mission Control handlers
  re-export `parse_sns_message` so existing
  `from <module>.handlers import parse_sns_message` imports keep working;
  `cms.experiments.handlers._parse_message` was renamed to
  `parse_sns_message` (private name had only the one local consumer).
- **Refactored `cms.models` into a bounded-context package.** The 978-LOC
  `shifter/shifter_platform/cms/models.py` god module is replaced by a
  `cms/models/` package split by domain: `catalogs`, `assets`,
  `provisioning`, `scenarios`, `range`. Public import paths are preserved
  via re-exports — every existing `from cms.models import X` keeps working
  with no consumer changes. Database table names, migrations, and runtime
  behavior are unchanged; verified by a new
  `tests/cms/test_models_no_migration_drift.py` that fails the suite if
  `makemigrations --check` ever detects pending model changes. New layout
  is the foundation for subsequent `cms` god-object decompositions tracked
  under #1055.
- **Deduplicated CMS soft-delete and expiry logic.** Added
  `cms/models/mixins.py` with `SoftDeleteMixin` (provides `is_deleted` for
  any model with a nullable `deleted_at` field) and `ExpiringStateMixin`
  (provides `is_expired` / `expires_soon` for any model with a nullable
  `expires_at` field). `Asset`, `EntityBase`, `Request`, `Scenario`, and
  `Credential` now inherit from `SoftDeleteMixin`; `CredentialBase` and
  `Credential` inherit from `ExpiringStateMixin`. Same property semantics,
  no schema changes.
- **Centralised CMS terminal-status soft-delete invariant** in
  `cms/models/lifecycle.apply_terminal_soft_delete`. `EntityBase.save()`
  and `RangeInstance.save()` both delegate to it instead of re-implementing
  the `TERMINAL_STATUSES → deleted_at + update_fields` logic locally.
- **Decoupled extension-normalisation from DB lookup** on
  `cms.models.OperatingSystem`. `normalize_file_extension()` is now a pure
  function and the iteration moved into a new
  `OperatingSystemQuerySet.for_extension()` queryset method;
  `get_for_extension()` is preserved as a thin compatibility wrapper.
- **Promoted `spec_class` field to `CatalogBase`** — `CredentialType`,
  `InstanceType`, and `AppType` no longer redeclare it. Cosmetic
  `help_text` migration for `cms.CredentialType` (no schema change).
- **`Credential` now extends `CredentialBase`** per the original design
  intent. Adds `last_verified_at` and `last_used_at` columns to the
  credentials table (cms migration `0025`), creating schema slots for
  credential-rotation, staleness, and compromise-detection signals.
- **Closed the soft-delete bypass bug class.** Added
  `shared/db/soft_delete.py` exposing the canonical primitives for any
  model with a nullable `deleted_at` field:
  - `SoftDeleteMixin` — `is_deleted` property.
  - `ExpiringStateMixin` — `is_expired` / `expires_soon`.
  - `SoftDeleteQuerySet` — chainable `.active()` / `.deleted()` /
    `.with_deleted()`.
  - `SoftDeleteManager` — **default manager that pre-filters every
    queryset to non-deleted rows.** A plain `Model.objects.filter(...)`
    cannot return deleted rows. Code that needs deleted rows must
    explicitly use `Model.all_objects` — making the intent obvious to
    reviewers and grep.

  `Asset`, `EntityBase`, `Request`, `Scenario`, `RangeInstance`, `Risk`,
  and `Comment` all declare the canonical pair (`objects =
  SoftDeleteManager()`, `all_objects = SoftDeleteQuerySet.as_manager()`)
  with `Meta.base_manager_name = "all_objects"` so reverse relations
  and admin introspection still see the full table. Removed the legacy
  `cms.models.ActiveRangeInstanceManager` (now redundant: the default
  `RangeInstance.objects` already pre-filters active).
- **Replaced every inline `deleted_at__isnull=True` filter** across
  `cms/services.py` (9 sites), `cms/experiments/services.py` (4),
  `cms/scenarios/registry.py` (3), `cms/scenario_editor/services.py`
  (3), `risk_register/views.py` (2), `risk_register/api/views.py` (2),
  `risk_register/models.py` (2), `ctf/forms.py` (1), and
  `ctf/services/event.py` (1) with default-manager calls — and dropped
  the now-redundant `.active()` chains. Helpers live in `shared/db/`
  (not `shared/models/`) to satisfy ADR-001-R2's
  cross-layer-model-imports check.
- **Fixed risk_register reachability bugs surfaced by the manager
  flip.** `risk_detail` and `risk_delete` now use `Risk.all_objects`
  (preserves view-deleted-risks behavior; makes re-delete idempotent).
  `RiskViewSet.restore` now bypasses the active-only `get_object()` and
  looks up via `Risk.all_objects` directly so deleted risks are
  reachable for restore.
- **Reverse-FK traversal is intentionally active-only.** The split
  between `_default_manager` (active) and `_base_manager` (unfiltered) is
  load-bearing: every implicit Django integration (`get_object_or_404`,
  ModelForm, admin, DRF serializers, generic CBVs) reaches for
  `_default_manager` and must default to active to keep the soft-delete
  bypass closed. Reverse-FK access (`parent.children.all()`) goes
  through the same `_default_manager`, so it is also active-only by
  design. Cascade delete and migration introspection use
  `_base_manager`, which `Meta.base_manager_name = "all_objects"` points
  at the unfiltered manager — so cascades still walk soft-deleted
  descendants and integrity stays correct. Audit / restore / admin code
  that needs to walk reverse relations *including* deleted rows must
  use the explicit `Child.all_objects.filter(parent=parent)` pattern.
  The verbosity is the contract: it makes the intent grep-able.
- **DB-backed integration tests** in
  `tests/integration/cms/test_soft_delete_manager.py` pin the canonical
  semantics: `Model.objects` excludes deleted rows even via explicit
  filter, `Model.all_objects` includes them, the chainable helpers
  compose, `_meta.base_manager_name` points at `all_objects`, and
  `parent.children.all()` returns deleted descendants too. These pin
  behaviour where the unit-test mocks pin call shape.
- **Range lookup helpers** (`get_range_status_by_id`,
  `get_range_spec_by_id`, `find_range_instance_id_by_request` in
  `cms/services.py`) now use `RangeInstance.all_objects` so terminal /
  destroyed ranges remain reachable for status lookups, audit reads,
  and callback correlation.
- **`risk_delete` is idempotent** — a re-delete attempt on an
  already-soft-deleted risk short-circuits before re-mutating
  `deleted_at` or writing a duplicate DELETE audit entry.
- **`RiskViewSet.restore` enforces object-level permissions** explicitly
  via `self.check_object_permissions()` after looking up via
  `Risk.all_objects` (the lookup bypass would otherwise skip DRF's
  permission check that `self.get_object()` would have run).
- **`CommentViewSet.list` honours `?include_deleted=true` for the parent
  risk too** — previously the parent lookup used active-only
  `Risk.objects`, so comment history on a soft-deleted risk was
  unreachable even with the include-deleted flag set.
- **`SoftDeleteQuerySet.with_deleted()` removed.** Its semantics were
  unsafe — it dropped any prior chained filters on the way back to the
  full table. Callers wanting every row use `Model.all_objects`
  directly: single canonical entry point keeps intent unambiguous.

## [3.95.14] - 2026-05-03

### Changed

- **`deploy.yml` cancels in-flight runs on new push to the same ref**
  (`concurrency.cancel-in-progress: true`). Previous setting (`false`)
  queued each new push behind the prior run's full duration, so a
  rapid sequence of pushes to `dev` or `aws-dev` stacked up indefinitely
  (saw 5 active runs after two back-to-back pushes today). Env
  branches never go backwards, so a newer SHA always supersedes the
  older queued one — cancelling is correct.

## [3.95.13] - 2026-05-03

### Changed

- **`deploy.yml` skips Quality on env-branch pushes** to dedupe runs.
  Pushing to `aws-dev`/`gcp-dev`/`main` previously re-ran the entire
  Quality phase even though the same SHA had just passed Quality on
  its `dev` push (per the repo rule: env branches never get commits
  except via merge from `dev`). That doubled CI runner-minutes per
  change. Quality now runs on PRs, `workflow_dispatch`, or direct
  `dev` pushes only. Deploy jobs already tolerate
  `needs.quality.result == 'skipped'`, so no downstream changes
  needed.

  Trust assumption: any SHA reaching an env branch must have green
  Quality on its dev run. If you ever push directly to an env branch
  bypassing dev, Quality won't gate it — keep the rule.

## [3.95.12] - 2026-05-03

### Fixed

- **Range provisioning failed with `dynamodb:PutItem` AccessDenied on a
  non-existent table** (`dev-range-pulumi-state-<redacted-account-id>-locks`).
  `shifter/engine/provisioner/terraform_base.py` derives the lock
  table name from the state bucket: it stripped `-pulumi-state` and
  replaced with `-pulumi-locks`, otherwise fell through to
  `<bucket>-locks`. The 3.95.6 bucket-name fix added a
  `-<account_id>` suffix, breaking the `endswith("-pulumi-state")`
  check, so the fallback computed
  `dev-range-pulumi-state-<redacted-account-id>-locks` — which doesn't exist
  (the actual table from the engine-state module is still
  `dev-range-pulumi-locks`) and isn't in the IAM policy. Switched to a
  regex (`-pulumi-state(?:-\d+)?$`) that matches both the legacy and
  account-id-suffixed forms; lock table name resolves to
  `<prefix>-pulumi-locks` either way. Added a test case for the new
  pattern. (Commit message tagged this 3.95.11 but 3.95.11 was taken
  by the cms refactor PR landing concurrently; bumped here for
  correctness.)

## [3.95.11] - 2026-05-03

### Fixed

- **Range provisioning failed with `dynamodb:PutItem` AccessDenied on a
  non-existent table** (`dev-range-pulumi-state-<redacted-account-id>-locks`).
  `shifter/engine/provisioner/terraform_base.py` derives the lock table
  name from the state bucket: it stripped `-pulumi-state` and replaced
  with `-pulumi-locks`, otherwise fell through to `<bucket>-locks`. The
  3.95.6 bucket-name fix added a `-<account_id>` suffix, breaking the
  `endswith("-pulumi-state")` check, so the fallback computed
  `dev-range-pulumi-state-<redacted-account-id>-locks` — which doesn't exist
  (the actual table from the engine-state module is still
  `dev-range-pulumi-locks`) and isn't in the IAM policy. Switched to a
  regex (`-pulumi-state(?:-\d+)?$`) that matches both the legacy and
  account-id-suffixed forms; lock table name resolves to
  `<prefix>-pulumi-locks` either way. Added a test case for the new
  pattern.

## [3.95.10] - 2026-05-03

### Fixed

- **Portal Apply hit `BucketAlreadyExists` (409) on `shifter-dev-user-storage-e3462f0c`.**
  The user_storage bucket name was hard-pinned in
  `platform/terraform/environments/dev/portal/terraform.tfvars` to a
  UUID-suffixed name from the previous dev account; that name remains
  globally claimed (S3 namespace is shared across all accounts).
  Switched to `shifter-dev-user-storage-<redacted-account-id>` (account-id
  suffix) — same pattern as `engine-state` / `log-aggregation` in 3.95.6.

## [3.95.9] - 2026-05-03

### Fixed

- **Ubuntu packer build failed on `apt-get update` with
  `Splitting up ... InRelease into data and signature failed`.**
  Reproduced across two consecutive runs on a fresh AMI launched from
  the latest official Canonical Ubuntu 22.04 image — not transient.
  Root cause: the base AMI sometimes ships with a corrupted `/var/lib/apt/lists`
  cache that breaks GPG signature parsing on the first `apt-get update`.
  Fix is in `shifter/packer/scripts/ubuntu/base.sh`: clear the apt list
  cache + reinstall `ubuntu-keyring` before any apt operation, and add
  `-o Acquire::Retries=3` to the first update for resilience against
  flaky mirrors.

## [3.95.8] - 2026-05-03

### Fixed

- **`AGENTS.md` and `.ground-control.yaml` pointed at the wrong GC project.**
  Both said `aphelion` with `GC-` prefix; reality is the `shifter` GC
  project (id `df4e718f-1f67-46f8-a375-3ba53fabc9c4`) with `CTF-*`,
  `PLAT-*`, `GEN-*` prefixes by subsystem. (`aphelion` is a separate,
  unrelated graph DB product project.) Surfaced while a backfill agent
  was creating tracking GH issues for 57 of the 58 DRAFT shifter
  requirements (#998–#1054); PLAT-001 was already covered by #802–#809.

  Also documented a `gc_create_github_issue` quirk: its auto-link uses
  `IMPLEMENTS`, which the API rejects on `DRAFT` requirements. Workaround
  is a manual `gc_create_traceability_link` of type `DOCUMENTS`.

## [3.95.7] - 2026-05-03

### Changed

- **`shifter/packer/dev.pkrvars.hcl`** updated for the fresh aws-dev
  account `<redacted-account-id>`: `vpc_id`/`subnet_id` were hardcoded to the
  previous dev account and packer aborted immediately with
  `InvalidSubnetID.NotFound`. Same fix as the github-runner `dev.tfvars`
  in 3.95.3.

## [3.95.6] - 2026-05-03

### Fixed

- **Range / Apply hit `BucketAlreadyExists` (409) on first deploy to the
  fresh `aws-dev` account.** `engine-state` module hardcoded
  `${var.name_prefix}-pulumi-state` (e.g., `dev-range-pulumi-state`)
  and S3 bucket names live in one global namespace. Suffixed both
  module bucket names with `${data.aws_caller_identity.current.account_id}`:
  - `engine-state` → `dev-range-pulumi-state-<account_id>`
  - `log-aggregation` → `dev-portal-logs-dev-<account_id>` (preemptive
    fix; same naming pattern would have collided next).

  The `tag.Name` keeps the account-less form so dashboards stay readable.
  No state migration needed for fresh deploys; if `prod` ever needs to
  carry over an existing bucket, it'll require a separate import +
  rename plan (out of scope here).

## [3.95.5] - 2026-05-03

### Fixed

## [3.95.4] - 2026-05-03

### Added

- **`platform/terraform/global/github-runner/README.md`** documenting
  the actual setup (manual EC2 + SSM registration), the registration
  token semantics (single-use registration, long-lived runner
  credentials after — no per-job re-auth), the AL2023 dependency
  gotcha, and a clean removal procedure.

### Fixed

- **Runner `user_data` now installs libicu + .NET 6 runtime libs
  directly via `dnf`** (`libicu krb5-libs zlib lttng-ust openssl-libs`),
  so a freshly provisioned runner can register on the first
  `./config.sh` call. The bundled `./bin/installdependencies.sh`
  doesn't recognise Amazon Linux 2023 (matches `ID="amzn"` /
  `ID_LIKE="fedora"` and aborts with `Can't detect current OS type`),
  so without these packages registration fails with
  `Libicu's dependencies is missing for Dotnet Core 6.0`. Future
  runner replacements no longer need a manual second SSM pass.

## [3.95.3] - 2026-05-03

### Changed

- **`platform/terraform/global/github-runner/dev.tfvars`** updated for
  the fresh aws-dev account `<redacted-account-id>`: VPC `<redacted-vpc-id>`,
  public subnet `<redacted-subnet-id>` (us-east-2a). Was pointing
  at IDs from the previous dev account.
- **`scripts/runner-deploy.sh`** cleaned up. Stale `Prerequisites` block
  about a GitHub App + `/shifter/github-runner/key-base64` /
  `webhook-secret` SSM params removed (artifact of an abandoned
  philips-labs/terraform-aws-github-runner approach; current module is
  plain EC2 + manual registration). `rm -rf .terraform.lock.hcl` reduced
  to `rm -rf .terraform/` so the now-tracked lockfile survives. Stale
  `terraform output webhook_endpoint`/`runner_labels` (don't exist)
  replaced with `runner_instance_ids`/`ssm_commands`. Top-of-file
  comment now documents the actual manual-registration flow.

### Removed

- **Cruft zips under `global/github-runner/`** (`webhook.zip`,
  `runners.zip`, `runner-binaries-syncer.zip`, `tfplan`) — leftovers
  from the abandoned philips-labs auto-scaler attempt. None were
  referenced by the current `main.tf`.

## [3.95.2] - 2026-05-03

### Fixed

- **`terraform_deploy` now passes `-backend-config=<env>.s3.tfbackend`**
  to `terraform init`. Was running bare `terraform init -reconfigure`,
  which would have failed against the new partial backends (placeholder
  bucket inline → real value supplied via `-backend-config`). Affects
  the `terraform` and `full` subcommands; bootstrap-only flow was
  unaffected because it inits IAM separately.

### Added

- **Bootstrap script now actually commits and pushes** the filled-in
  `.s3.tfbackend` files at the end of `bootstrap` and `full` commands
  (the README listed this as automated but the code did not implement
  it — stale doc → real behaviour). New `walkthrough_git_commit`
  function stages env-scoped paths only (`global/iam/<env>.s3.tfbackend`,
  `environments/<env>/{,portal,range}/<env>.s3.tfbackend`,
  `environments/<env>/portal/main.tf`, plus any other
  `global/**/<env>.s3.tfbackend` rewritten by the bootstrap), shows
  `git status --porcelain` of those paths, prompts to commit (yes / no /
  manual), commits with `Bootstrap <env>: fill in state bucket <bucket>`,
  then prompts separately to push to `origin/<current-branch>`. Runs in
  both `bootstrap` and `full` flows.

## [3.95.1] - 2026-05-03

### Changed

- **`global/dev-box/` converted to partial-backend pattern.** The
  inline `backend "s3"` block hard-coded `shifter-dev-infra-b7113d6f-…`
  as the bucket — the only file in the repo that still did so. Replaced
  with `OVERRIDDEN_VIA_BACKEND_CONFIG` placeholders + new
  `dev.s3.tfbackend` file, matching the rest of the tree. README updated
  with the `-backend-config=dev.s3.tfbackend` init flag.

### Fixed

- **Bootstrap regex was env-blind and could clobber the wrong
  environment's bucket.** `_update_global_backend_configs` matched
  both `shifter-infra-<uuid>` and `shifter-dev-infra-<uuid>` regardless
  of the `--env` flag, so a `--env prod` run would have rewritten
  `dev-box/main.tf`'s dev bucket reference with the prod bucket.
  Tightened the regex to anchor on the current env's bucket prefix
  (`shifter-infra` for prod, `shifter-<env>-infra` otherwise) plus the
  `REPLACE_AT_BOOTSTRAP` placeholder. Also dropped the `*.tf` walker
  since every `*.tf` backend block is now partial (placeholder bucket,
  real value supplied via `-backend-config` at init).

## [3.95.0] - 2026-05-03

### Fixed

- **80+ Dependabot security alerts cleared** across every package manager
  in the repo. Python (uv): bumped Django to 6.0.4, cryptography to
  47.0.0, cbor2 to 6.0.1, pyOpenSSL to 26.1.0, pyasn1 to 0.6.3, pytest
  to 9.0.3, python-dotenv to 1.2.2, Pygments to 2.20.0, requests to
  2.33.1, ujson to 5.12.0, urllib3 to 2.6.3, filelock to 3.25.2,
  virtualenv to 21.2.0. Node (npm): bumped hono to 4.12.16,
  @hono/node-server to 1.19.14, path-to-regexp to 8.4.2, flatted to
  3.4.2, picomatch (v2) to 2.3.2 and (v4) to 4.0.4, brace-expansion to
  2.1.0, minimatch (v3) to 3.1.5 and (v9) to 9.0.9, ajv (v6) to 6.15.0
  and (v8) to 8.20.0. Pinned `cryptography==46.0.7` and `protobuf==5.29.6`
  in `shifter/engine/provisioner/requirements.txt`.

### Changed

- **Full dependency refresh on every uv- and npm-managed manifest**
  beyond the security bumps above. `uv lock --upgrade` ran on
  `shifter/shifter_platform/`, `shifter/engine/provisioner/`,
  `scripts/check_layer_imports/`, `scripts/bootstrap/`,
  `shifter/cyberscript/`, and `shifter/packer/` — pulling in the latest
  patch/minor versions of ~40 transitive packages including pydantic
  2.13.3, mypy 1.20.2, ruff 0.15.12, gunicorn 25.3.0, mozilla-django-oidc
  5.0.2, redis 7.4.0, boto3 1.43.2, grpcio 1.80.0, and protobuf 7.34.1.
  `npm update --package-lock-only` ran on the four MCP servers
  (`mcp/{ops,planner,ngfw}/`), `shifter/shifter_platform/`, and
  `platform/terraform/gcp/modules/platform-core/functions/identity-platform/`.
- **Terraform `required_version` standardized to `>= 1.5.0`** across all
  17 root configs (was an inconsistent mix of `>= 1.0` and `>= 1.5.0`).
- **CI Terraform action bumped 1.7.1 → 1.13.3** in `_core.yml`,
  `_range.yml`, and `_shifter-platform.yml` — required by the
  `use_lockfile` migration below (S3 native locking landed in 1.10).
- **Terraform S3 backend state locking migrated from DynamoDB to S3
  native** (`use_lockfile = true`). All inline `backend "s3"` blocks
  (`environments/{dev,prod}/{,portal,range}/backend.tf`,
  `global/iam/backend.tf`) and all `.s3.tfbackend` files dropped
  `dynamodb_table = "..."` in favour of `use_lockfile = true`. The
  `engine-state` module's `aws_dynamodb_table.engine_locks` resource
  is unrelated to terraform state locking and was left intact (it
  serves the Shifter engine application).
- **Environment backend.tf files converted to partial-backend pattern.**
  The six `environments/{dev,prod}/{,portal,range}/backend.tf` files
  used to hard-code the bucket UUID inline; they now ship with
  `OVERRIDDEN_VIA_BACKEND_CONFIG` placeholders and the real values come
  from `<env>.s3.tfbackend` at init time, matching the existing
  `global/iam/` convention. Single source of truth for the bucket
  name; backend.tf is never modified by automation.
- **CI workflows now pass `-backend-config=${env}.s3.tfbackend`** to
  `terraform init` (was bare `terraform init`). Required by the
  partial-backend conversion above.
- **`scripts/bootstrap/deploy.py` rewritten for the new pattern.** The
  walkthrough now writes `.s3.tfbackend` files for env, portal, and
  range (instead of overwriting `backend.tf`), emits
  `use_lockfile = true`, and never touches `backend.tf`. Bootstrap
  steps renumbered 1/3, 2/3, 3/3 (was 1/4..4/4) since DynamoDB table
  creation is gone. The unused `dynamodb_table_exists` and
  `create_dynamodb_table` helpers are kept for now in case someone
  needs to reintroduce DynamoDB locking. `_update_global_backend_configs`
  now also matches the `REPLACE_AT_BOOTSTRAP` literal so freshly
  templated `.tfbackend` files get filled in at bootstrap time.
- **All `.s3.tfbackend` files templated.** Bucket UUIDs replaced with
  `REPLACE_AT_BOOTSTRAP` so a fresh bootstrap produces matching
  configs without leaving stale UUIDs in the repo. Three new
  `dev.s3.tfbackend` files added under `environments/dev/`,
  `environments/dev/portal/`, and `environments/dev/range/` (those
  three previously had no `.tfbackend` and relied entirely on inline
  config).

### Removed

- **Empty stub directories** `platform/terraform/modules/pulumi-provisioner/`
  and `platform/terraform/modules/pulumi-state/` — they contained only
  stale `.terraform.lock.hcl` files with no `.tf` content, leftover
  from a deleted module.
- **Stale terraform state in `temp/ngfw-bootstrap-test/`** —
  `terraform.tfstate` and `terraform.tfstate.backup` deleted (no
  corresponding live infrastructure).

## [3.94.0] - 2026-04-14

### Added

- **Per-instance `instance_type` scenario override.** Additive field on
  `cms.scenarios.schema.InstanceConfig` and `cyberscript.schemas.range.InstanceSpec`;
  the provisioner's `build_tf_vars` (`shifter/engine/provisioner/main.py`)
  now honours a per-instance `instance_type` when set, falling back to
  the existing role/os-based env-var defaults otherwise. Every existing
  scenario yaml is unaffected (field is optional, default `None`).
- **`shifter/.dockerignore`.** Excludes local dev cruft (`**/.env`,
  `__pycache__`, `.venv`, `.git`, IDE folders) from the portal image
  build context. Without this the local `shifter_platform/.env` —
  which sets `AWS_ENDPOINT_URL=http://localhost:4566` for LocalStack —
  was getting copied into `/app/.env`, and `settings.py`'s `load_dotenv()`
  poisoned the deployed portal's boto3 clients so every SQS/S3/SNS call
  tried to hit `localhost:4566` and failed.

### Fixed

## [3.93.0] - 2026-04-13

### Fixed

### Added

## [3.92.0] - 2026-04-13

### Fixed

### Changed

### Added

## [3.91.0] - 2026-04-13

### Added

## [3.90.0] - 2026-04-13

### Added

## [3.89.0] - 2026-04-13

### Fixed

## [3.88.0] - 2026-04-13

### Added

### Fixed

- **Flag 15 walkthrough wording** (`flags-07-19-front-office.md`) — now
  explicitly says Kowalski's "creds backup" email is in **INBOX** (he sent
  to his own address; Dovecot has no Sent folder for that user). Previous
  "(Kowalski sent it to himself)" parenthetical was ambiguous and led at
  least one walkthrough-runner to check a non-existent Sent folder first.
## [3.87.0] - 2026-04-13

### Added

## [3.86.0] - 2026-04-12

### Fixed

- **Flag 37 walkthrough payload** — the documented sudo-arg-injection
  example `--host "x; cat /root/.scada/hmi.json"` did not actually
  work because `scada_diag.sh` `eval`s `curl -sS http://$HOST:8080/ping`
  — so without a trailing comment the injection expands into
  `cat /root/.scada/hmi.json:8080/ping` and `cat` errors on the
  concatenated filename. Walkthrough now shows the working form with
  the trailing `#` that comments out the `:8080/ping` suffix.
### Changed

### Proofs

## [3.85.0] - 2026-04-12

### Added

### Changed

## [3.84.0] - 2026-04-12

### Fixed

### Changed

- **`tests/setup.sh` + `tests/reset.sh`** taught about the new
  nested layout: `COMPOSE_FILE` env override with default
  `$RANGE_DIR/build/docker-compose.yml` and legacy flat-layout
  fallback to `$RANGE_DIR/docker-compose.yml`. Project name
  explicitly pinned to `range` via `-p range` so network and
  container names stay stable across layout moves.

### Verified

## [3.83.0] - 2026-04-12

### Changed

- Moves were `git mv` wherever possible to preserve history.
  Files from `shifter-k8s/` are copies (different repo, no
  shared git history).
- `run-all-smoketests.sh` updated: new variables `SMOKETESTS_DIR`,
  `RESET_SCRIPT`, `ISOLATION_SCRIPT` with sane defaults for the
  new layout and fallback to the old flat layout if detected.
  Per-test paths switched from `<Content-Dir>/smoketest.ext`
  to `A<N>-smoketest.ext` reflecting the flattened tests/smoketests/.
### Known drift (deferred, needs approval per design-is-source-
of-truth rule)

## [3.82.0] - 2026-04-12

### Fixed

## [3.81.0] - 2026-04-12

### Added

### Changed

## [3.80.0] - 2026-04-12

### Added

## [3.79.0] - 2026-04-12

### Fixed

### Added

## [3.78.0] - 2026-04-12

### Fixed

### Added

## [3.77.0] - 2026-04-12

### Fixed

### Added

## [3.76.0] - 2026-04-12

### Fixed

### Added

## [3.75.0] - 2026-04-12

### Fixed

### Added

## [3.74.0] - 2026-04-12

### Fixed

### Added

## [3.73.0] - 2026-04-12

### Fixed

### Changed

### Added

## [3.72.0] - 2026-04-12

### Fixed

### Added

## [3.71.0] - 2026-04-12

### Fixed

### Changed

### Added

## [3.70.0] - 2026-04-12

### Added

## [3.69.0] - 2026-04-12

### Added

## [3.68.0] - 2026-04-12

### Fixed

### Added

## [3.67.0] - 2026-04-12

### Added

## [3.66.0] - 2026-04-11

### Changed

### Removed

## [3.65.0] - 2026-04-11

### Added

### Changed

## [3.64.0] - 2026-04-11

### Changed
- GCP control-plane deployment cut over to a Helm-based release under `platform/charts/shifter/` with layered values (`values.yaml`, `values-gcp-dev.yaml`, `values-gcp-prod.yaml`) plus bootstrap-generated runtime overrides
- `gdc-bootstrap` now deploys the GCP control plane through the Helm chart instead of the previous raw-manifest path
- `AGENTS.md` has a new "Ground Control Context" section pointing to `.ground-control.yaml`
- `.mcp.json` `ground-control` block now sets `GH_REPO=Brad-Edwards/shifter`

### Added
- `.ground-control.yaml` declaring the `aphelion` Ground Control project, shifter's local lint command (ADR guard), SonarCloud key (`Brad-Edwards_shifter`), and plan rules reference
- `.gc/plan-rules.md` containing ADR guard, guardrail discipline, architectural defaults, and stack-native checker requirements as "plans MUST..." bullets for the `/implement` skill plan phase
- Chart-managed GKE `BackendConfig` for the portal Service so Google Cloud ingress health checks are explicitly pinned to `/health/`
- Environment-scoped Helm values files for `gcp-dev` and `gcp-prod`
- Live bootstrap proof notes for the Helm-based GCP control-plane path in `temp/k8s/gcp-feature-audit.md`
- Terraform-managed GCP Identity Platform auth for `gcp-dev`, including bootstrap-owned first-operator creation and runtime-configured bootstrap admin elevation

### Fixed
- Fixed agentic workshop scenario configs
- GCP bootstrap rerun safety for substrate stages: bootstrap key reuse, secret-version churn avoidance, SSH metadata drift checks, and staged bundle replacement
- Engine migration consistency for `SubnetAllocation` so GCP bootstrap can run the platform database migrations cleanly on a fresh control plane
- GCP bootstrap now leaves a usable externally reachable Shifter platform after control-plane bring-up, including healthy portal ingress and expected Mission Control login redirect behavior
- AWS auth continuity while adding GCP identity support: AWS keeps the existing Cognito/OIDC path and GCP uses a provider-seamed first-party Identity Platform login flow

## [3.63.0] - 2026-04-09

### Added
- Kubernetes manifest validation: kubeconform schema checks and kube-linter security/best-practice enforcement in pre-commit and CI
- Checkov Kubernetes framework scanning for CIS benchmark checks on `platform/k8s/` manifests (soft-fail)
- Cloud factory parity check (`cloud-factory-seam`) enforcing ADR-005-R1: every cloud adapter in `cloud/aws/` must have a counterpart in `cloud/gcp/`
- TFLint `tflint-ruleset-google` plugin for GCP-specific Terraform linting
- Image registry check ensuring Kustomize overlay images reference Artifact Registry (`pkg.dev`)
- Pod Security Standards labels (`restricted` profile) on Kubernetes namespace manifests
- PSS namespace labels architecture check in pre-commit Stage 4 (ADR-006-R1)
- ADR-006: Kubernetes workloads must meet Pod Security Standards
- ADR-004-R5 (kubeconform + kube-linter) and ADR-004-R6 (tflint-ruleset-google) rules
- CI jobs: `k8s-lint`, `k8s-schema`, `security-k8s` in quality workflow
- Time-bounded exceptions for known K8s manifest gaps (securityContext, NetworkPolicies) expiring 2026-07-08

## [3.62.1] - 2026-04-06

### Fixed
- ADR guard argparse ambiguity: positional `checks` arg replaced with `--checks` named option to prevent `--files nargs="+"` from swallowing check names
- Claude post-edit hook no longer runs `guardrail-docs` check, which is a changeset-level check incompatible with per-file hook context

### Added
- Ground Control project context in AGENTS.md for the `/implement` workflow

## [3.62.0] - 2026-04-05

### Added
- Enforce magic link token expiration at login — expired tokens are now rejected (PLAT-101)
- Configurable magic link expiration via `MAGIC_LINK_EXPIRY_HOURS` setting (default 24 hours)
- Configurable single-use tokens via `MAGIC_LINK_SINGLE_USE` setting (default multi-use)
- Rate limiting on invitation generation endpoints (50 per hour per organizer)

## [3.61.0] - 2026-04-05

### Added
- Time-boundary enforcement on flag submissions rejects attempts before event start or after event end, regardless of event state (CTF-702)
- Countdown timer on participant event page showing time until event start or end
- Client-side local timezone display for event start and end times on participant event page

## [3.60.0] - 2026-04-05

### Added
- Scheduled reminder notifications at configurable intervals before event start (CTF-1005)
- `reminder_hours` field on CTFEvent for organizer-configurable reminder intervals (default: 24h, 1h)
- `event_timezone` field on CTFEvent for timezone-aware start times in reminder emails
- Access URL included in reminder emails linking to participant event page
- Timezone-aware event start time display in reminder email templates
- Per-challenge connection info for range-integrated challenges (CTF-115)
- `target_instance_name` and `target_port` fields on CTFChallenge to map a challenge to a specific range service
- Participant challenge detail view now resolves the configured target against the participant's ready range and displays the host:port inline

### Changed
- Scheduler `_handle_send_reminder` handler now calls `send_reminder()` (was a stub)
- `_schedule_event_tasks` creates one SEND_REMINDER task per configured interval with `hours_before` metadata

## [3.59.0] - 2026-04-05

### Added
- Shared email templating and delivery service in `shared.email` (PLAT-103)
- `render_template()` for rendering HTML+text email template pairs with variable substitution
- `send_email()` for synchronous delivery with error logging (never raises)
- `send_email_async()` for fire-and-forget background delivery via thread pool
- CTF notification service now delegates to the shared email service

## [3.58.0] - 2026-04-05

### Added
- Per-event email template customization: organizers can override default email templates for any notification type (CTF-805)
- `CTFEmailTemplate` model with unique constraint per event and notification type
- Admin page listing template override status per notification type
- API endpoint for CRUD operations on custom email templates

## [3.57.0] - 2026-04-04

### Added
- Event force delete: permanently delete an event and all associated resources regardless of state (CTF-704)
- Force delete cascades to range instances, participants, challenges, submissions, scores, and scheduled tasks
- Confirmation page requiring organizer to type event name before force deleting
- API endpoint for programmatic force delete with confirmation_name validation
- Danger zone section on event detail page linking to force delete

## [3.56.2] - 2026-04-04

### Fixed
- Enforce registration deadline when inviting or bulk-importing participants (CTF-007)

## [3.56.1] - 2026-04-04

### Added
- Organizer email notifications on automated event start/end transitions (CTF-1004)
- Email templates for event start and event end organizer notifications
- `notify_organizer_event_start()` and `notify_organizer_event_end()` notification service functions
- Tests for scheduler event start/end handlers and organizer notifications

## [3.56.0] - 2026-04-04

### Added
- Scoreboard visibility toggle: organizers can hide the scoreboard from participants until ready (CTF-004)
- `scoreboard_visible` boolean field on CTFEvent model (default True)
- Participant scoreboard view and API return hidden state when scoreboard is not visible
- Admin scoreboard shows banner when scoreboard is hidden from participants
- Scoreboard visibility checkbox in event create/edit form

## [3.55.0] - 2026-04-02

### Added
- Bracket support: group participants into named brackets (e.g. beginner, intermediate, advanced) with separate scoreboards per bracket (CTF-405)
- `CTFBracket` model with event-scoped name uniqueness and soft delete
- `bracket` foreign key on `CTFParticipant` for bracket assignment
- Bracket CRUD service (`ctf/services/bracket.py`) with assignment validation
- `bracket_id` filter parameter on `get_scoreboard()` and `get_team_scoreboard()`
- `bracket_name` field in scoreboard response entries
- Bracket tabs on participant and admin scoreboard views
- Admin bracket management views (list, create, edit, delete)
- API endpoint for assigning/removing participant brackets
- Bracket column in admin participant list
- `CTFBracketAdmin` in Django admin with participant count
- `CTFBracketForm` for bracket creation/editing

## [3.54.0] - 2026-04-02

### Added
- Scoreboard freeze support: organizers can set a freeze time after which participants see frozen standings while organizers see real-time scores (CTF-403)
- `scoreboard_freeze_at` field on CTFEvent model with validation
- `is_scoreboard_frozen` convenience property on CTFEvent
- `freeze_at` parameter on `get_scoreboard()` and `get_team_scoreboard()` scoring functions
- Freeze time input on event creation/edit form
- Freeze status banners on participant and admin scoreboard views
- Freeze indicator in scoreboard API JSON responses

## [3.53.1] - 2026-04-02

### Fixed
- Team scoreboard solve count now counts unique challenges solved instead of total submissions (CTF-402)
- Participant scoreboard template context variable mismatch preventing scoreboard from rendering (CTF-402)
- Participant scoreboard auto-refresh reading wrong JSON key from API response (CTF-402)
- Participant scoreboard now displays team-specific columns (Members) when team mode is active (CTF-402)

## [3.53.0] - 2026-04-02

### Added
- Per-participant score timeline API and charts showing cumulative score progression over event duration (CTF-408)
- Score timeline chart on participant scoreboard page (own timeline) and admin participant detail page (any participant)
- `get_score_timeline()` service function in CTF scoring module

## [3.52.0] - 2026-04-01

### Added
- Per-iteration progress logging during throttled range provisioning — logs "N/M (X ready, Y failed)" after each provision (CTF-905)
- Test suite for `provision_event_ranges_throttled()` covering happy path, partial failure, delay clamping, and graceful shutdown (CTF-905)

## [3.51.0] - 2026-03-30

### Added
- Organizer dashboard: quick-access event controls (pause, end, cancel) for active events (CTF-1301)
- Organizer dashboard: participant count with registration breakdown (CTF-1301)
- Organizer dashboard: range provisioning status overview with ready/provisioning/error counts (CTF-1301)
- Organizer dashboard: recent activity feed showing last 15 submissions across active events (CTF-1301)

## [3.50.0] - 2026-03-29

### Added
- Browser-based RDP access buttons on CTF participant range page (CTF-904)

## [3.49.0] - 2026-03-29

### Added
- Next challenge navigation: optional per-challenge FK to suggest follow-up after solving (CTF-121)
- Organizer dropdown on challenge form to configure next challenge
- Participant "Next:" link in solved alert with non-blocking navigation

## [3.48.0] - 2026-03-29

### Added
- Hint purchase confirmation showing actual penalty cost and resulting challenge value (CTF-304)
- Warning when hint purchase would reduce challenge to minimum 1-point floor (CTF-304)

## [3.47.0] - 2026-03-29

### Changed
- Progressive ordered hints system replacing single hint per challenge (CTF-003)
- `CTFHint` model with per-hint text, penalty, and order for sequential unlock
- `CTFHintUsage` model tracks which hints each participant has unlocked
- Cumulative penalty calculation (sum of unlocked hint penalties, capped at 100%)
- Organizer hint management via API (add/remove hints on challenge detail page)
- Participant progressive hint UI with sequential unlock and penalty display
- Data migration converts existing single-hint challenges to CTFHint records

### Removed
- Legacy `hint` and `hint_penalty` fields from CTFChallenge
- Legacy `hint_used` field from CTFSubmission

## [3.46.0] - 2026-03-28

### Added
- Participant challenge ratings on a 1-5 scale (CTF-120)
- `CTFChallengeRating` model with unique constraint per participant per challenge
- `rating_visibility` event-level config: public, organizer-only, or disabled
- API endpoint `POST /api/challenges/<id>/rate/` for submitting ratings
- Average rating and count displayed in admin and participant challenge detail
- Rating visibility dropdown in event admin form

## [3.45.0] - 2026-03-28

### Added
- Controlled vocabulary topic taxonomy for CTF challenges (CTF-119)
- `CTFTopic` model for global knowledge areas and attack techniques (e.g. SQL Injection, Privilege Escalation)
- Topics distinct from categories (event-scoped enum) and tags (freeform, event-scoped)
- Topic filtering on participant challenge listing via `?topic=` query parameter
- Topics displayed as badges on challenge cards and admin detail pages
- Topics included in challenge API responses (list and detail)

## [3.44.0] - 2026-03-28

### Added
- Official solution writeups on CTF challenges (CTF-117)
- `solution` TextField on CTFChallenge for rich-text Markdown content
- Solutions visible to organizers at all times, revealed to participants after event ends
- Solution editing in admin challenge form, display in admin challenge detail
- Solution field in challenge API detail response

## [3.43.0] - 2026-03-27

### Added
- Freeform metadata tags on CTF challenges for secondary filtering (CTF-113)
- `CTFChallengeTag` model scoped to events with unique constraint per event
- Tag filtering on participant challenge listing via `?tag=` query parameter
- Tags displayed as badges on challenge cards and admin detail pages
- Tags included in challenge API responses (list and detail)
- Comma-separated tag input on admin challenge form

## [3.42.0] - 2026-03-26

### Added
- Configurable attempt limit behavior per event: lockout (permanent) or timeout (temporary with cooldown) (CTF-112)
- `attempt_limit_mode` field on CTFEvent selects behavior when max attempts reached
- `attempt_limit_cooldown_seconds` field on CTFEvent controls timeout duration before attempts reset
- Submission Limits section in event admin form for managing cooldown and attempt limit settings
- Attempt limit fields exposed in event API GET response

## [3.41.0] - 2026-03-26

### Added
- Configurable time-based submission rate limiting per event (CTF-114)
- `submission_cooldown_seconds` field on CTFEvent controls minimum delay between flag submissions per participant per challenge
- Rate-limited responses include `Retry-After` header and retry details for client display

## [3.40.0] - 2026-03-26

### Added
- Automatic challenge release scheduling via the CTF scheduler (CTF-111)
- `RELEASE_CHALLENGE` scheduled task type transitions HIDDEN challenges to VISIBLE at their configured `release_time`
- Challenge create/update automatically manages release task lifecycle (create, reschedule, cancel)
- Event rescheduling recreates challenge release tasks for all eligible challenges

## [3.39.0] - 2026-03-26

### Added
- Challenge visibility control with three states: visible, hidden, locked (CTF-110)
- Organizers can hide broken challenges mid-event or stage challenges before making them visible
- Locked challenges appear in participant lists but block submissions

## [3.38.0] - 2026-03-26

### Added
- Range lifecycle management tied to event state (CTF-902) — ranges are destroyed when events end (if auto_cleanup) or are cancelled
- Manual stop, start, and restart APIs for organizer range management
- Provisioning retry with exponential backoff (3 retries, 30s base delay)
- Organizer email notification on provisioning failures
- Context-appropriate range action buttons in organizer UI (stop/start/restart/destroy per status)

### Changed
- Enforced strict service layer boundaries — all cross-layer imports must go through `layer.services` only
- Added `ctf` to architecture-as-code checkers (`check_layer_imports`, `check_model_fks`)
- Replaced `management.UserProfile.active_ctf_event` ForeignKey with soft-reference UUIDField (zero cross-layer FKs)
- Moved `get_s3_client` and `sanitize_s3_filename` from `cms.assets.s3` to `shared.s3`
- Moved `range_status_changed` signal from `ctf.signals` to `cms.signals` (CMS emits, CTF receives)
- Removed duplicated Guacamole URL generation from CTF — participants use the platform's existing RDP access flow
- Fixed 13 cross-layer import violations across cms, mission_control, and ctf

## [3.37.0] - 2026-03-25

### Changed
- Completed event statistics for CTF analytics dashboard (CTF-1304) — added active participants (submission-based), challenges with zero solves, average score, median score, incorrect submissions, and event duration metrics
- Fixed `active_participants` in `get_event_statistics()` to count participants with at least one submission instead of filtering by status
- Expanded analytics template from 4 to 8 stat cards

## [3.36.0] - 2026-03-24

### Changed
- CTF event lifecycle expanded to 7-state machine: draft, registration, active, paused, ended, cancelled, archived (CTF-701)
- Renamed event status "scheduled" to "registration" and "completed" to "ended"
- Event transitions enforced via centralized VALID_TRANSITIONS map
- Added pause_event, resume_event, archive_event service functions

## [3.35.1] - 2026-03-22

### Fixed
- `reconcile_ranges` now detects all running range EC2 instances, including those with custom Name tags or hyphenated roles, by filtering on `shifter:range_id` tag instead of Name tag pattern (#796)
- `reconcile_ranges` now flags orphan instances when engine_instance exists but has no associated range (NULL range_status from LEFT JOIN)

## [3.35.0] - 2026-03-22

### Added
- File attachments for CTF challenges (CTF-001) — organizers can upload downloadable files (binaries, pcaps, images, etc.) to challenges; participants download via presigned S3 URLs
- Challenge prerequisites (CTF-001) — challenges can require other challenges to be solved first, with BFS cycle detection, locked challenge display, and submission gating
- `CTFChallengeFile` model with S3 storage, SHA256 integrity, size/extension validation (50 MB max, 10 files per challenge)
- `CTFChallengePrerequisite` model with same-event validation, self-reference prevention, and circular dependency detection
- Attachment service (`add_challenge_file`, `remove_challenge_file`, `get_challenge_files`, `get_download_url`)
- Prerequisite service functions (`add_prerequisite`, `remove_prerequisite`, `get_prerequisites`, `get_dependents`, `check_prerequisites_met`)
- API endpoints for file management and prerequisite management
- Admin challenge detail UI sections for managing files and prerequisites
- Participant challenge views show downloadable files and prerequisite lock/gate UI

### Changed
- `get_available_challenges()` accepts optional `participant_id` to exclude challenges with unmet prerequisites
- `submit_flag()` checks prerequisites before accepting submissions
- `delete_challenge()` cascades soft-delete to prerequisite links where the challenge is required

## [3.34.0] - 2026-03-22

### Changed
- **Terraform**: Rename remaining `pulumi_state_*`, `pulumi_locks_*`, `pulumi_secrets_*` variable names in `modules/engine-provisioner/variables.tf` to `engine_state_*`, `engine_locks_*`, `engine_secrets_*`
- **Terraform**: Rename remaining `pulumi_state_*`, `pulumi_locks_*`, `pulumi_secrets_*` output names in `environments/*/range/outputs.tf` to `engine_*` equivalents
- **Terraform**: Update all `data.terraform_remote_state.range.outputs.pulumi_*` references in `environments/*/portal/main.tf` to match renamed outputs
- **Terraform**: Rename Terraform resource identifiers (with `moved` blocks) in `modules/engine-state/` (`aws_s3_bucket.pulumi_state` → `engine_state`, `aws_kms_key.pulumi_secrets` → `engine_secrets`, `aws_dynamodb_table.pulumi_locks` → `engine_locks`, plus sub-resources)
- **Terraform**: Rename Terraform resource identifiers (with `moved` blocks) in `modules/engine-provisioner/` (`aws_ecs_cluster.pulumi` → `engine`, `aws_ecs_task_definition.pulumi_provisioner` → `engine_provisioner`, `aws_iam_role_policy.pulumi_state` → `engine_state`)
- **Terraform**: Update comments and descriptions referencing "Pulumi" to "engine" in `modules/engine-provisioner/iam.tf` and `variables.tf`

### Removed
- **Terraform**: Remove deprecated `pulumi-*` SSM parameters from `modules/portal/ssm/main.tf` (confirmed no application code references them; `engine-*` parameters already active)

## [3.33.0] - 2026-03-22

### Changed
- **Platform**: ECS modules (`engine/ecs.py`, `cms/experiments/ecs.py`) now propagate `CloudTaskError` instead of catching it and re-raising as `botocore.exceptions.ClientError`
- **Platform**: `engine/services.py` callers (`pause_range`, `resume_range`) catch `CloudTaskError` instead of `ClientError`
- **Platform**: Extract `_get_engine_ecs_config()` helper in `engine/ecs.py` to DRY up config reading from 3 internal functions

### Fixed
- **Terraform**: Portal `ecr_repository_url` uses `try()` fallback for foundation output rename (`engine_provisioner_ecr_url` || `pulumi_provisioner_ecr_url`) so portal plan succeeds regardless of foundation apply order

### Removed
- **Platform**: Remove `from botocore.exceptions import ClientError` from `engine/ecs.py` and `cms/experiments/ecs.py`

## [3.32.0] - 2026-03-22

### Changed
- **Platform**: Rename `PULUMI_ECS_CLUSTER_ARN`, `PULUMI_TASK_DEFINITION_ARN`, `PULUMI_ECS_SECURITY_GROUP_ID`, `PULUMI_PRIVATE_SUBNET_IDS` to `ENGINE_*` prefix across settings, application code, tests, Terraform SSM, deployment scripts, and CI/CD
- **Platform**: Rename `PULUMI_BACKEND_URL` to `STATE_BUCKET_URL` in task definition and local provisioner script
- **Platform**: Settings use fallback pattern (`ENGINE_*` || `PULUMI_*`) for zero-downtime transition
- **Terraform**: Rename module directories `modules/pulumi-provisioner/` to `modules/engine-provisioner/` and `modules/pulumi-state/` to `modules/engine-state/`
- **Terraform**: Rename module blocks `pulumi_provisioner` to `engine_provisioner`, `pulumi_state` to `engine_state`, `pulumi_provisioner_ecr` to `engine_provisioner_ecr` with `moved` blocks for state continuity
- **Terraform**: Rename variables `pulumi_provisioner_repository_name` to `engine_provisioner_repository_name`, `pulumi_container_tag` to `engine_container_tag`, and SSM module variables `pulumi_ecs_*`/`pulumi_task_*`/`pulumi_private_*` to `engine_*`
- **Terraform**: Rename outputs `pulumi_provisioner_ecr_*` to `engine_provisioner_ecr_*` and portal outputs `pulumi_ecs_*`/`pulumi_task_*`/`pulumi_private_*` to `engine_*`
- **Terraform**: Update all `module.pulumi_provisioner.*` and `module.pulumi_state.*` references to `module.engine_provisioner.*` and `module.engine_state.*` across environments
- **Terraform**: Update comments, descriptions, and tags from "Pulumi" to "Engine" in module internals (resource names unchanged for state compatibility)
- **Terraform**: Add new `engine-*` SSM parameters alongside deprecated `pulumi-*` parameters for transition

### Removed
- **Platform**: Remove `PULUMI_SECRETS_PROVIDER` env var (dead after Pulumi removal)
- **Platform**: Remove `PULUMI_BACKEND_URL`/`PULUMI_SECRETS_PROVIDER` from `_run_local_provisioner()` and `.env.example`
- **Platform**: Remove mock-pulumi PATH injection from local provisioner

## [3.31.0] - 2026-03-22

### Added
- **Provisioner**: `terraform_base.py` — shared Terraform runner helpers extracted from duplicate code in `terraform_runner.py` and `range_terraform_runner.py`
- **Provisioner**: `cloud/aws/base.py` — `BaseAWSAdapter` base class with shared `_get_client()` for all AWS adapters
- **Provisioner**: Shared executor exceptions (`ExecutorError`, `ExecutorCommandError`, `ExecutorTimeoutError`) in `executors/base.py`

### Changed
- **Provisioner**: `terraform_runner.py` and `range_terraform_runner.py` are now thin wrappers around `terraform_base.py`, eliminating ~550 lines of exact duplication
- **Provisioner**: All 5 AWS adapters (`secrets`, `db_auth`, `config_store`, `event_bus`, `storage`) inherit `BaseAWSAdapter` instead of duplicating `_get_client()`
- **Provisioner**: SSM, SSH, and NGFW executors use shared exception base classes from `executors/base.py` with backward-compatible aliases
- **Provisioner**: `main.py` SQL query construction uses `psycopg.sql` module for safe identifier composition instead of f-string formatting
- **Provisioner**: `linux_xdr_agent_install.py` bash scripts use `mktemp` for unpredictable temp file paths instead of hardcoded `/tmp` paths
- **Provisioner**: NGFW executor temp key file cleanup improved with `__del__` fallback; removed redundant `os.chmod` (mkstemp already creates with 0o600)

### Removed
- **Provisioner**: Remove `pulumi` and `pulumi_aws` from `requirements.txt` (already removed from `pyproject.toml`)

### Security
- **Provisioner**: Added `# NOSONAR` annotations for reviewed security hotspots (subprocess calls, Paramiko AutoAddPolicy, SSH StrictHostKeyChecking, test credentials)

## [3.30.0] - 2026-03-21

### Added
- **Provisioner Cloud**: `SecretsStore` protocol, `CloudSecretsError` exception, `AWSSecretsStore` adapter, and `get_secrets_store()` factory
- **Provisioner Cloud**: `object_exists()` and `delete_object()` methods on `ObjectStorage` protocol and `AWSObjectStorage` adapter

### Changed
- **Provisioner**: Migrate `events.py` from direct `boto3` SNS calls to `EventBus` cloud abstraction
- **Provisioner**: Migrate `config.py` RDS IAM auth from `boto3` to `DBAuth` cloud abstraction
- **Provisioner**: Migrate `main.py` S3/SSM/RDS/Secrets calls to `ObjectStorage`, `ConfigStore`, `DBAuth`, `SecretsStore` cloud abstractions
- **Provisioner**: Migrate `stacks/range_stack.py` Secrets Manager call to `SecretsStore` cloud abstraction
- **Provisioner**: Migrate `components/network.py` RDS IAM auth to `DBAuth` cloud abstraction
- **Provisioner**: Migrate `terraform_runner.py` S3 calls to `ObjectStorage` cloud abstraction
- **Provisioner**: Migrate `range_terraform_runner.py` S3 calls to `ObjectStorage` cloud abstraction

### Removed
- **Provisioner**: Remove `_get_sns_client()` from `events.py` (replaced by `EventBus` protocol)
- **Provisioner**: Remove direct `import boto3` from `events.py`, `config.py`, `main.py`, `stacks/range_stack.py`, `terraform_runner.py`, `range_terraform_runner.py`

## [3.29.1] - 2026-03-21

### Changed
- **Provisioner**: Remove misleading "stub" docstrings from AWS cloud adapters (`AWSObjectStorage`, `AWSConfigStore`, `AWSEventBus`, `AWSDBAuth`) — implementations are complete

## [3.29.0] - 2026-03-21

### Changed
- **Worker**: Migrate `run_worker` management command from direct `boto3` SQS calls to `shared.cloud.get_queue_consumer()` abstraction layer
- **CMS**: Migrate `cms/experiments/events.py` from direct `boto3` SQS calls to `shared.cloud.get_queue_publisher()` abstraction layer
- **Cloud**: Remove stub docstring from `AWSQueuePublisher`/`AWSQueueConsumer` now that extraction is complete

### Removed
- **Engine**: Delete deprecated `_get_ecs_client()` from `engine/ecs.py` (replaced by `shared.cloud.get_task_runner()`)
- **CMS**: Delete deprecated `_get_ecs_client()` from `cms/experiments/ecs.py` (replaced by `shared.cloud.get_task_runner()`)
- **Tests**: Delete `tests/engine/ecs/test_get_ecs_client.py` (tested removed function)

## [3.28.0] - 2026-03-21

### Changed
- **Engine**: Migrate `engine/secrets.get_ssh_key()` from direct `boto3` Secrets Manager calls to `shared.cloud` abstraction layer
- **CTF**: Migrate `ctf/bridges._get_instance_ssh_key()` from direct `boto3` Secrets Manager calls to `shared.cloud` abstraction layer
- **Cloud**: Remove stub docstring from `AWSSecretsStore` now that extraction is complete

## [3.27.3] - 2026-03-21

### Changed
- **Tests**: Consolidate test suite through parametrization and fixture extraction (39,712 → 39,050 lines, -662 net)
- **Tests**: Extract shared `mock_queryset` fixture and `INVALID_USERS`/`INVALID_RANGE_IDS` parametrize helpers to `tests/conftest.py`
- **Tests**: Extract in-memory model builders (`make_ctf_event`, `make_challenge`, `make_team`, `make_participant`, `make_scheduled_task`) to `tests/ctf/conftest.py`
- **Tests**: Create `tests/cms/conftest.py` with shared `credential_type_obj` fixture and `make_credential` builder
- **Tests**: Convert `_create_range_patches` helper to `create_range_ctx` pytest fixture in `cms/test_services_range.py`
- **Tests**: Parametrize user/range_id validation and error propagation tests across service classes in `cms/test_services_range.py`
- **Tests**: Consolidate model_dump/model_validate round-trip tests into parametrized classes in `shared/schemas/test_range.py` and `test_credentials.py`
- **Tests**: Parametrize required-field, default-value, computed-property, and status validation tests in `shared/schemas/test_range.py`
- **Tests**: Parametrize expiry property and positive-id validator tests in `shared/schemas/test_credentials.py`
- **Tests**: Parametrize boolean property, count, and status transition tests in `ctf/test_models.py`
- **Tests**: Parametrize credential property tests in `cms/test_models.py`
- **Tests**: Refactor `test_scoring.py` scoreboard setup methods to use shared `mock_queryset` fixture

### Added
- **Tests**: Add error handling, input validation, and missing config tests for `start_provisioning()` (2 → 7 tests)
- **Tests**: Add error handling, input validation, and missing config tests for `start_teardown()` (2 → 7 tests)
- **Tests**: Add error cases for `start_ngfw_provisioning()` (3 → 6 tests)
- **Tests**: Add error cases for `start_ngfw_teardown()` (4 → 7 tests)

### Removed
- **Tests**: Delete empty `mission_control/test_consumers.py` (0 tests, placeholder comment only)
- **Tests**: Remove redundant `InstanceContext` tests that duplicated `InstanceContextBase` coverage

## [3.27.2] - 2026-03-21

### Security
- **Platform**: Bump `django` 6.0 -> 6.0.3
- **Platform**: Bump `cryptography` 46.0.3 -> 46.0.5
- **Platform**: Bump `pyopenssl` 25.3.0 -> 26.0.0
- **Platform**: Bump `pyasn1` 0.6.1 -> 0.6.3
- **Platform**: Bump `ujson` 5.11.0 -> 5.12.0
- **Platform**: Bump `cbor2` 5.7.1 -> 5.8.0
- **Platform**: Bump `urllib3` 2.6.0 -> 2.6.3
- **Platform**: Bump `filelock` 3.20.0 -> 3.25.2
- **Platform**: Bump `virtualenv` 20.35.4 -> 21.2.0
- **Platform**: Add `[tool.uv] constraint-dependencies` to enforce minimum versions for transitive security deps

## [3.27.1] - 2026-03-21

### Security
- **Provisioner**: Bump `cryptography` 46.0.3 -> 46.0.5
- **Provisioner**: Bump `protobuf` 5.29.5 -> 5.29.6
- **Provisioner**: Bump `urllib3` minimum to >=2.6.3

## [3.27.0] - 2026-03-21

### Changed
- **Test suite: eliminate all DB access outside `tests/integration/`** — 63% faster (722s → 269s)
  - Converted 87 `@pytest.mark.django_db` markers and ~48 `TestCase` subclasses to mock-based tests
  - Only 22 markers remain, all in `tests/integration/` (legitimate integration tests)
  - View tests: replaced `Client`/`force_login` with `RequestFactory` + mock users
  - Model tests: in-memory construction via `Model()` or `__new__` + `__dict__`
  - Service tests: patched ORM managers (`objects.get`, `objects.filter`, `objects.create`, etc.)
  - Added missing engine migration (SubnetAllocation `reserved_at` → `created_at` rename)
  - Added missing CTF migration (index rename, field alter)
  - Changed all `OperatingSystem.objects.get(slug=...)` to `get_or_create()` for xdist resilience

## [3.26.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_models_subnet.py` (CMS) by mocking ORM
  - Added `_make_subnet()` helper to construct Subnet instances in-memory via `__dict__` assignment, bypassing Django FK descriptor validation
  - EntityBase `is_deleted` tests: built in-memory with `deleted_at` set/unset
  - Terminal status auto-`deleted_at` tests: patched `validate_data` and `django.db.models.Model.save` to exercise real `EntityBase.save()` logic without DB
  - Relationship tests: replaced cascade-delete DB test with `_meta` introspection asserting `CASCADE` on_delete and `related_name='subnets'`
  - Ordering test: asserted `Subnet._meta.ordering` instead of querying DB
  - Validation tests: called `subnet.validate_data()` directly on in-memory instances
  - Data/property tests: constructed in-memory instances and asserted properties
  - 4 class-level `@pytest.mark.django_db` markers removed, all 18 tests pass without DB access

## [3.25.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_models.py` (mission_control) by mocking ORM
  - Added `_make()` helper to construct Django model instances in-memory, bypassing FK validation and populating `_state.fields_cache`
  - OperatingSystem `get_for_extension` tests: patched `OperatingSystem.objects.all`
  - UserProfile tests: built via `_make()` with mock user in fields_cache
  - AgentConfig tests: built via `_make()` with mock user/os, `active_for_user` patched at `AgentConfig.objects.filter`
  - Range standup_duration tests: set `created_at`/`ready_at` directly on in-memory instances; annotation test mocks `Range.objects` chain
  - ActivityLog tests: `log()` patched at `ActivityLog.objects.create`, `__str__` tests use `_make()`
  - 4 class/method-level `@pytest.mark.django_db` markers removed, all 34 tests pass without DB access

## [3.24.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_auth.py` (CTF) by mocking ORM
  - Created `_MockGroupManager`/`_MockGroupQS` helpers to simulate `user.groups` with in-memory sets
  - OIDC backend tests: patched `config.oidc.Group.objects`, `config.oidc.get_user_profile`, `ctf.models.CTFEvent.objects`
  - Dashboard routing tests: call `dashboard_router` directly via `RequestFactory` with mock users
  - Access control decorator tests: patched `management.services.get_user_profile`, `ctf.models.CTFParticipant.objects`
  - Dev login tests: patched `config.dev_auth.User.objects`, `config.dev_auth.Group.objects`, `config.dev_auth.login`
  - Context processor tests: patched `management.services.get_user_profile` (bridges import locally)
  - Register view tests: patched `ctf.models.CTFParticipant.objects`, `django.contrib.auth.login`
  - Dual-role tests: patched `management.services.get_user_profile`, `django.contrib.auth.models.Group.objects`
  - 8 class-level `@pytest.mark.django_db` markers removed, all 48 tests pass without DB access

## [3.23.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_range_api.py` (mission_control) by mocking ORM
  - Replaced `Client`/`force_login` with `RequestFactory` + mock user via `AnonymousUser` for auth tests
  - View tests (get_range, launch_range, cancel_range, destroy_range, list_agents): patched CMS service functions (`get_active_range`, `cms_create_range`, `cms_get_agent`, `cms_list_agents`, `cms_list_scenarios`) at the view-module boundary
  - Subnet allocation tests: mocked `transaction.atomic` and `Range.objects` queryset chain
  - Shared fixtures (`mock_user`, `mock_agent`, `mock_linux_agent`, `other_user`) replace DB-backed `test_agent`/`windows_os`/`linux_os` fixtures
  - 6 class-level `@pytest.mark.django_db` markers removed, all 37 tests pass without DB access

## [3.22.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_scoring.py` (CTF) by mocking ORM
  - `TestCalculateScore`: mocked `CTFSubmission.objects.filter().aggregate()` chain
  - `TestGetScoreboard` / `TestGetTeamScoreboard`: mocked annotated queryset chains with mock participant/team objects
  - `TestGetParticipantRank`: mocked both `.get()` lookup and scoreboard queryset
  - `TestGetChallengeStatistics`: mocked `CTFChallenge.objects.get()` and submission queryset chains
  - `TestGetEventStatistics`: mocked `CTFEvent.objects.get()` and all related model managers
  - `TestCalculatePointsWithPenalty`: replaced real model instances with mocks binding the real method
  - 7 class-level `@pytest.mark.django_db` markers removed, all 27 tests pass without DB access

## [3.21.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_views.py` (mission_control) by mocking ORM
  - View tests (dashboard, settings, help): replaced `Client`/`force_login` with `RequestFactory` + mock user, patched `render` to avoid DB-hitting context processors
  - `TestGetUserStorageUsed`: mocked `AgentConfig.active_for_user` queryset instead of creating real DB records
  - `TestUploadLock`: replaced Django session with plain dict (no DB session backend needed)
  - 5 class-level `@pytest.mark.django_db` markers removed, all 14 tests pass without DB access

## [3.20.0] - 2026-03-20

### Changed
- Remove `@pytest.mark.django_db` from three CMS test files by mocking all ORM access
  - `test_services_scenarios.py`: replaced real User/AgentConfig fixtures with mocks, patched registry functions (list_all_scenarios, get_scenario_detail, load_scenario_template)
  - `test_scenario_hydrator.py`: replaced real User/AgentConfig fixtures with mocks, patched hydrator's load_scenario with canned ScenarioTemplate Pydantic objects
  - `test_services_range.py`: converted remaining 4 `create_range` test classes (Validation, EngineCall, Instance, Return) from DB to fully mocked ORM using ExitStack-based helper

## [3.19.0] - 2026-03-20

### Changed
- Test suite optimization: remove unnecessary `@pytest.mark.django_db` markers and add `--reuse-db`
  - Added `--reuse-db` to pytest addopts in pyproject.toml for faster repeated runs
  - `test_create_range.py`: removed `django_db`, added `_mock_transaction` autouse fixture
  - `test_cancel_range.py`: removed `django_db` from both classes, added `_mock_range_lookup` fixture
  - `test_services_storage.py`: converted real `User` fixture to `mock_user`, removed `django_db`
  - `test_handlers.py` (CMS): removed `django_db` from `TestProcessEvent` and `TestParseSnsMessage`
  - `test_handlers.py` (Engine): removed `django_db` from `TestProcessEvent` and `TestParseSnsMessage`
  - `test_models_agent_config.py`: removed `django_db` from `TestAgentConfigModel` (metadata-only tests)
  - `test_models_operating_system.py`: removed `django_db` from `TestOperatingSystemModel` (metadata-only tests)
  - 10 class-level markers removed across 7 test files

## [3.18.0] - 2026-03-20

### Changed
- Test suite cleanup: remove duplicate wrapper tests and unnecessary `@pytest.mark.django_db` markers
  - Removed ~51 duplicate tests from ECS wrapper test files (delegation verified in 2-4 tests each)
  - Deleted `tests/mission_control/test_engine.py` (12 tests duplicating `tests/engine/ecs/`)
  - Removed `@pytest.mark.django_db` from 8 test files that only use mocks (no ORM calls)
- CMS service test streamlining: replace real DB fixtures with mocks in mock-heavy tests
  - `test_services_range.py`: removed `django_db` from 8/12 classes (~75 tests), kept 4 `create_range` classes on DB
  - `test_services_upload.py`: removed `django_db` from all 3 classes (57 tests), removed unused DB fixtures
  - `test_services_agents.py`: removed `django_db` from all 4 classes (34 tests), removed unused DB fixtures
  - Added `mock_user` fixture with `Mock(pk=42, id=42)` to replace real `User.objects.create_user` in pure-mock tests
- Task runner abstraction delegation (PLAT-001.3, #813)
  - `engine/ecs.py`: All ECS task functions now delegate to `TaskRunner` protocol via `get_task_runner()`
  - `cms/experiments/ecs.py`: `start_experiment_task()` delegates to `TaskRunner` protocol via `get_task_runner()`
  - Added `container_name` parameter to `TaskRunner.run_task()` protocol and `AWSTaskRunner` adapter
  - `AWSTaskRunner.run_task()` now raises `CloudTaskError` when no tasks are started (was returning None)
  - `AWSTaskRunner.get_task_status()` now returns all fields callers expect (`desired_status`, `started_at`, `stopped_at`)
  - Exception bridging: `CloudTaskError` caught and re-raised as `ClientError` for backward compatibility
  - All existing function signatures, import paths, and caller contracts preserved
  - `_get_ecs_client()` kept deprecated in both modules; `import boto3` moved inside it

## [3.17.0] - 2026-03-19

### Changed
- Object storage abstraction delegation (PLAT-001.2, #812)
  - `cms/assets/s3.py`: All S3 functions now delegate to `ObjectStorage` protocol via `get_object_storage()`
  - `cms/experiments/s3.py`: All S3 functions now delegate to `ObjectStorage` protocol via `get_object_storage()`
  - `provisioner/config.py`: `generate_presigned_url()` delegates to provisioner `ObjectStorage` adapter
  - Exception bridging: `CloudStorageError` caught and re-raised as `S3Error` for backward compatibility
  - All existing function signatures, import paths, and caller contracts preserved

## [3.18.0] - 2026-03-20

### Added
- Programmable flag validation (CTF-118) — flags can use registered Python validator functions or HTTP callbacks for custom pass/fail logic
- New flag types: `programmable` (server-side validator registry) and `http` (external endpoint validation)
- Validator registry module (`ctf/validators.py`) with `register_validator` / `get_validator` API
- Built-in example validators: `always_true`, `contains_substring`
- `validator_config` JSONField on `CTFFlag` model for per-flag configuration

### Changed
- `CTFFlag.flag_type` max_length increased from 10 to 20 to accommodate new type names

## [3.17.0] - 2026-03-20

### Added
- CTF awards system (CTF-206) — organizers can grant point bonuses or deductions to participants via `CTFAward` model
- Award service (`grant_award`, `revoke_award`, `get_participant_awards`, `get_event_awards`)
- Score calculation now includes awards: `calculate_score`, `get_scoreboard`, `get_team_scoreboard`, model `total_score` properties, and admin annotations all reflect submission points + award points
- `get_event_statistics` includes `total_awards` count
- Award admin interface with inline views on participant and event admin pages

## [3.16.1] - 2026-03-20

### Changed
- Consolidated all in-app test directories (`ctf/tests/`, `cms/experiments/tests/`, `risk_register/tests/`) into centralized `tests/` directory so all 2331 tests are discovered by the default `pytest` command
- Removed `--cov` from pytest `addopts` — local runs are now fast; coverage runs only in CI
- CI workflow now includes `--cov` for `ctf`, `engine`, and `risk_register` modules and no longer ignores `tests/risk_register`

## [3.16.0] - 2026-03-19

### Added
- Cloud provider abstraction layer foundation (PLAT-001.1, #811)
  - Protocol definitions for ObjectStorage, TaskRunner, QueueConsumer, QueuePublisher, SecretsStore (platform)
  - Protocol definitions for EventBus, ConfigStore, DBAuth, ObjectStorage (provisioner)
  - Factory functions with `CLOUD_PROVIDER` setting (defaults to "aws")
  - AWS adapter implementations for all protocols
  - Provider-agnostic exception hierarchy
  - Generic setting aliases (`CLOUD_PROVIDER`, `CLOUD_REGION`, `STORAGE_BUCKET_NAME`) with backward-compatible AWS fallbacks
- Multiple flags per challenge (CTF-107) — new `CTFFlag` model supports multiple valid flags per challenge where any correct flag constitutes a solve
- Each flag independently supports static (hashed) or regex (pattern match) types and case sensitivity
- `add_flag` / `remove_flag` service functions and API endpoints for flag management
- Flag management UI on admin challenge detail page (add/remove flags with type and case sensitivity controls)
- Backward compatible — challenges with only the legacy `flag_hash` field continue to work without migration

## [3.15.4] - 2026-03-18

### Fixed
- Deploy pipeline circular dependency — Engine Deploy now skips gracefully when ECS task definition doesn't exist yet (first deploy), allowing Platform terraform to create it
- Platform workflow no longer blocked by Engine Deploy failure — tolerates non-success results so first deploy can complete
- Guacamole ECS stability check: replaced `aws ecs wait services-stable` (hard 10min timeout) with polling loop (20min); auto-detects FAILED deployments from prior runs and forces redeployment before waiting
- Migration `cms/0015_ngfw_model.py` made idempotent — checks if `ngfw_spec` column exists before adding it, preventing "column already exists" error on fresh databases; uses `PRAGMA table_info` for SQLite (tests) and `information_schema` for PostgreSQL (prod)
- Docker Compose build context corrected — set to parent directory so Dockerfile can access sibling directories (`cyberscript/`, `shifter_platform/`)

### Added
- `SKIP_MIGRATIONS` environment variable support in `entrypoint.sh` for local development

## [3.15.3] - 2026-03-16

### Added
- CTF walkthrough page with 7-step copy-pasteable prompts for Box 0 (WebShell) guided workshop — accessible to participants at `/ctf/walkthrough/`

## [3.15.2] - 2026-03-15

### Fixed
- Range destroy no longer fails with empty CIDR — allocated subnet CIDRs are now persisted to range_config during provisioning, and destroy falls back to the allocation table for ranges provisioned before this fix

## [3.15.1] - 2026-03-15

### Added
- CTF scheduler process (`run_ctf_scheduler`) added to deployment workflow and docker-compose — scheduled tasks (range provisioning, event start/end, cleanup) now execute automatically

### Removed
- `describe_stacks` tool from the ops MCP server — CloudFormation is not used in this project (Pulumi is used instead), so the tool was dead code

## [3.15.0] - 2026-03-15

### Fixed
- CTF magic link now takes participants directly to Mission Control instead of showing a login page
- Removed dead CTF login page — magic link is the only auth path for CTF participants
- Logout now works for all auth types — unified `/logout/` view routes OIDC users through Cognito logout, magic-link/dev users through Django session logout
- Dashboard session-expiry redirect no longer hardcodes `/oidc/authenticate/` — uses `/dashboard/` (the router) so all user types land correctly

### Changed
- CTF participants now only see the Kali (attacker) box in the terminal UI — victim, DC, and NGFW tabs are filtered out in the `active_range()` context processor

## [3.14.0] - 2026-03-15

### Added
- Instance names from scenario YAML templates are now set as EC2 hostnames during provisioning — instances get meaningful names (e.g., `webdev01`, `kali`, `mx-internal`) instead of AWS defaults like `ip-10-1-2-109.us-east-2.compute.internal`
- `name` field passed through Terraform variables, locals, user_data templates, and outputs for all instance types (Kali, Linux victim, Windows victim, DC)
- Hostname setting in `victim_linux.sh.tpl`, `victim_windows.ps1.tpl`, and `dc_windows.ps1.tpl` user_data templates
- EC2 Name tags now use the scenario template name when available

## [3.13.2] - 2026-03-14

### Fixed
- Subnet allocation race condition — `allocate_subnets()` call in `range_stack.py` now passes `range_id` and `request_id`, so CIDR reservations are actually written to `engine_subnetallocation` (GH #786)
- Windows SSH failure during CTF bootstrap — CTF AMIs now build on top of Shifter base AMIs (`shifter-windows`, `shifter-ubuntu`) which have OpenSSH pre-installed, instead of raw Amazon/Canonical images that required runtime installation (GH #786)

### Changed
- CTF Packer templates (`ctf-helpdesk`, `ctf-vault`, `ctf-webshell`, `ctf-mailroom`, `ctf-devbox`) rebase on Shifter base AMIs instead of raw vendor images; `base.ps1`/`base.sh` provisioner steps removed
- CTF setup scripts deduplicated — removed IIS install, WinRM config, SSH config, and firewall rules already baked into base AMIs
- Reverted `configure_ssh` bootstrap DISM fallback — OpenSSH is now guaranteed by base AMI; missing SSH should fail loudly

## [3.13.1] - 2026-03-14

### Fixed
- CTF range destroy API returns 500 due to missing `range_id` — `process_range_event()` now persists `range_id` from SNS event to `RangeInstance` (#756)

## [3.13.0] - 2026-03-14

### Fixed
- Normal Shifter users who are also CTF participants no longer lose access to platform features like Assets, Docs, Settings/Help, and Launch Range (GH #758) — UI restrictions now use `is_ctf_participant_only` which only hides features for pure CTF participants with no other platform role

### Added
- `is_ctf_participant_only()` utility in `shared/auth.py` — returns True only when a user is a CTF participant with no staff, superuser, organizer, or threat research role
- `is_ctf_participant_only` template context variable exposed via CTF context processor

## [3.12.0] - 2026-03-14

### Fixed
- Experiment creation now enforces `staff_only` and `disabled` scenario restrictions (GH #770) — previously the experiment UI and service layer loaded scenarios directly via `cms.scenarios.loader`, bypassing `ScenarioMetadata` access controls

### Changed
- Experiment create form uses `list_all_scenarios(user)` from the scenario registry instead of raw YAML loader, so non-staff users only see scenarios they're allowed to use
- `create_experiment()` service checks scenario access via `check_scenario_access()` before creating the experiment
- `get_scenario_instances()` AJAX endpoint passes the requesting user for access checking
- Experiment services use `load_scenario_template()` from the registry (checks DB first, then YAML) instead of `load_scenario()` from the raw loader

## [3.11.0] - 2026-03-14

### Changed
- CTF organizer admin views now use Mission Control layout (`mission_control/base.html`) instead of separate CTF portal — organizers see the full MC sidebar with ranges, terminal, assets, etc.
- Added "CTF Admin" nav item to Mission Control sidebar for organizers (between Risk Register and Scenario Editor)
- Dashboard router sends CTF organizers to Mission Control dashboard instead of CTF admin dashboard — fixes dual-role users losing access to MC launch panel (GH #758)
- Removed separate CTF organizer sidebar (`ctf_organizer_sidebar.html`) — organizers use the standard MC sidebar

## [3.10.0] - 2026-03-14

## Changed
- Update Claude Code model versions (Sonnet 4.5, Haiku 4.5)

## [3.9.0] - 2026-03-13

### Changed
- CTF participants now land on Mission Control dashboard instead of separate CTF UI — reuses existing range, terminal, and Guacamole views
- Magic link registration (`/ctf/register/`) redirects to Mission Control dashboard
- Dashboard router sends CTF participants to Mission Control
- Dev login redirects CTF participants to Mission Control
- MC sidebar hides Assets, Docs, Settings, and Help nav items for CTF participants (shows only Ranges and Terminal)
- MC dashboard hides Launch Range form for CTF participants (their ranges are pre-provisioned by organizers)
- Dashboard JS skips launch UI initialization in view-only mode for CTF participants

## [3.8.0] - 2026-03-13

### Changed
- CTF participants are auto-registered (Django user created, status set to `registered`) when added individually or via CSV import — eliminates the separate "registration" step
- Magic link emails can be sent to any participant at any time, regardless of status — removed registered-participant guard from `resend_invite()`
- "Send All Links" button now sends to all participants, not just uninvited ones
- Per-participant "Send Link" button always visible in participant list (was hidden after registration)
- Invitation email wording updated: "Click below to access your event" / "Access Event" (was "To register" / "Register Now")

## [3.7.1] - 2026-03-13

### Added
- `list_ranges` MCP tool — list ranges with status, user, scenario, instance count, and timestamps; supports filtering by status and username
- `get_range` MCP tool — get detailed range info including instances and subnet allocations
- `list_subnet_allocations` MCP tool — list subnet CIDR allocations with optional status/VPC filtering

## [3.7.0] - 2026-03-13

### Added
- `SubnetAllocation` model and migration (`engine_subnetallocation` table) to reserve CIDRs during concurrent provisioning, preventing TOCTOU race condition where multiple ranges pick the same subnet CIDR
- Subnet allocation table is checked alongside AWS `describe_subnets` during CIDR selection; stale reservations (>30min) are automatically reclaimed
- `confirm_subnet_allocations()` / `release_subnet_allocations()` lifecycle hooks called on provision success, destroy, and failure (Terraform path)
- `SubnetAllocationAdmin` registered in Django admin for ops visibility
- 7 new tests for allocation table integration (reserve, skip-reserved, stale-reclaim, released-reuse, confirm, release, DB-fallback)

## [3.6.0] - 2026-03-13

### Fixed
- CI deploy workflow (`_shifter-platform.yml`) now passes `EMAIL_BACKEND` and `CTF_FROM_EMAIL` env vars to containers (emails were silently going to console backend)
- EC2 IAM role missing `ses:GetSendQuota` permission required by `django-ses` backend (applied via Terraform)
- `get_scoreboard` and `get_team_scoreboard` annotation `total_score` collided with model `@property` of the same name, causing 500 on participant dashboard, admin scoreboard, and scoreboard API (renamed annotation to `computed_score`)
- Invite token expiry now uses event end time directly instead of `min(7 days, event_end)`, ensuring tokens remain valid through the entire event

### Changed
- `agentic_workshop` scenario template simplified from two-subnet to single flat subnet topology (multi-subnet isolation doesn't work without NGFW; attack path enforced by challenge design instead)

### Added
- CTF range management JavaScript (`static/js/ctf-ranges.js`) with `CTFRangeManager` class wiring Provision All, per-participant Provision, and per-participant Destroy buttons to API endpoints
- Per-participant range API endpoints: `POST /ctf/api/participants/<id>/range/provision/` and `POST /ctf/api/participants/<id>/range/destroy/`
- 20 Jest tests for `CTFRangeManager` covering all button interactions, error handling, and loading states

## [3.5.0] - 2026-03-13

### Added
- `ami_key` optional field on `InstanceConfig`, `InstanceSpec`, and `InstanceContextBase` for custom AMI support
- Provisioner resolves `ami_key` to AMI ID via SSM `/shifter/ami/<ami_key>` and passes per-instance `ami_id` to Terraform
- `get_ami_id()` now accepts arbitrary SSM parameter suffixes (custom ami_key values), not just the 4 known types
- Terraform `ami_id` per-instance override: when non-empty, bypasses the `os_type` AMI lookup
- `agentic_workshop` scenario template: 6-box single-subnet CTF range with custom AMIs for vibe hacking workshop

## [3.4.1] - 2026-03-13

### Fixed
- `resend_invite` now actually sends the invitation email (previously only refreshed the token without emailing)
- `user_data.sh` includes `localhost,127.0.0.1` in `DJANGO_ALLOWED_HOSTS` for SSM tunnel access
- `user_data.sh` stops `ctf-scheduler` container during redeployment (was missing from stop list)

## [3.4.0] - 2026-03-13

### Changed
- CTF RBAC migrated from `UserProfile.user_type` CharField to Django Groups (`CTF Organizer`, `CTF Participant`), enabling users to hold both roles simultaneously
- `get_user_role()` now checks Django group membership instead of `UserProfile.user_type`
- `_set_ctf_participant_profile` / `_clear_ctf_participant_profile` use additive/subtractive group operations instead of overwriting `user_type`
- OIDC callback and dev login add/remove Django groups instead of setting `user_type` field
- Dashboard router uses `shared.auth` helpers instead of `UserProfile` properties
- `UserProfile.is_ctf_organizer` / `is_ctf_participant` properties now delegate to group membership (deprecated, use `shared.auth` helpers)

### Added
- Data migration `0004_ctf_groups` creates `CTF Organizer` and `CTF Participant` groups and migrates existing users
- `shared.auth`: `CTF_ORGANIZER_GROUP`, `CTF_PARTICIPANT_GROUP` constants and `is_ctf_organizer()`, `is_ctf_participant()` helpers
- Dual-role test coverage (organizer who is also a participant)

## [3.3.0] - 2026-03-12

### Added
- Vibe Hacking Workshop CTF range: 5-box range with network topology for 90-minute workshop
- Packer templates for all CTF boxes: ctf-webshell, ctf-mailroom, ctf-helpdesk, ctf-devbox, ctf-vault
- Box 0 "WebShell" (Ubuntu walkthrough): Apache/PHP webshell -> sudo -> SUID privesc
- Box 1 "MailRoom" (Ubuntu): anonymous FTP -> credential pattern -> SSH -> PATH hijack privesc
- Box 2 "HelpDesk" (Windows): SMB cred leak -> RDP -> scheduled task abuse
- Box 3 "DevBox" (Ubuntu, dual-homed): command injection -> SSH key hunting -> GTFOBins sudo node
- Box 4 "Vault" (Windows, internal only): pivot target with WinRM, Backup Operators privesc, KeePass alt path
- Validation test scripts for each CTF box (setup verification)
- CTF scheduled task executor management command (`run_ctf_scheduler`) — polls for due `CTFScheduledTask` rows and dispatches SPIN_UP_RANGES, EVENT_START, EVENT_END, CLEANUP_RANGES, and SEND_REMINDER tasks with signal handling and heartbeat monitoring
- Throttled bulk range provisioning (`provision_event_ranges_throttled`) — spreads AWS resource creation across the spinup window with configurable delay clamped to [5, 120]s and graceful shutdown support
- Full Guacamole connection parameters (RDP credentials, SFTP config, SSH keys) for CTF range access via new `get_range_connection_info` bridge
- "Send All Invites" button on the CTF organizer participant list page with API endpoint
- Registration URL in CTF invitation emails (replaces raw invite token display)
- Event-driven range status sync from CMS to CTF via Django signal (`range_status_changed`) — updates `CTFParticipant.range_status` when CMS processes SNS range events
- Scenarios API endpoint (`/ctf/api/scenarios/`) for listing available CMS scenarios as JSON
- Datetime string parsing in event API POST/PUT handlers so JSON-submitted datetime strings are converted before reaching the service layer
- `range_spinup_minutes` field in event detail API GET response

### Changed
- CTF event create/edit form rewritten to use Mission Control AJAX pattern with XDR dark theme instead of Django form posts with Bootstrap
- CTF admin views and templates: replaced Bootstrap classes with XDR theme styling for visual consistency with Mission Control

### Fixed
- CTF participant registration now sets `UserProfile.user_type` and `active_ctf_event` directly, removing dependency on pre-configured Cognito custom claims for `ctf_participant_required` decorator
- CTF participant disqualification and deletion now clear `UserProfile` CTF fields
- `get_range_access_url` now passes RDP username/password, SFTP root directory, and SSH key to Guacamole instead of only hostname

### Removed
- Dead `_extract_ip_from_range_spec` helper in `ctf/services/range.py` (replaced by `get_range_connection_info` bridge)
- Django form-based event creation/edit views (replaced by AJAX pattern)

## [3.2.0] - 2026-03-12

### Added
- CTF scheduled task executor management command (`run_ctf_scheduler`) — polls for due `CTFScheduledTask` rows and dispatches SPIN_UP_RANGES, EVENT_START, EVENT_END, CLEANUP_RANGES, and SEND_REMINDER tasks with signal handling and heartbeat monitoring
- Throttled bulk range provisioning (`provision_event_ranges_throttled`) — spreads AWS resource creation across the spinup window with configurable delay clamped to [5, 120]s and graceful shutdown support
- Full Guacamole connection parameters (RDP credentials, SFTP config, SSH keys) for CTF range access via new `get_range_connection_info` bridge
- "Send All Invites" button on the CTF organizer participant list page with API endpoint
- Registration URL in CTF invitation emails (replaces raw invite token display)
- Event-driven range status sync from CMS to CTF via Django signal (`range_status_changed`) — updates `CTFParticipant.range_status` when CMS processes SNS range events

### Fixed
- CTF participant registration now sets `UserProfile.user_type` and `active_ctf_event` directly, removing dependency on pre-configured Cognito custom claims for `ctf_participant_required` decorator
- CTF participant disqualification and deletion now clear `UserProfile` CTF fields
- `get_range_access_url` now passes RDP username/password, SFTP root directory, and SSH key to Guacamole instead of only hostname

### Removed
- Dead `_extract_ip_from_range_spec` helper in `ctf/services/range.py` (replaced by `get_range_connection_info` bridge)

## [3.1.2] - 2026-03-12

### Fixed
- CTF event form: replace plain text `scenario_id` input with a dropdown populated from the CMS scenario registry
- CTF event form: add `is-invalid` CSS class to fields with errors for Bootstrap 5 error visibility
- CTF event form: validate submitted `scenario_id` exists in the scenario registry

## [3.1.1] - 2026-03-12

### Fixed
- Flag hashing bug: challenges created via admin form used bare SHA256, producing hashes that `verify_flag()` could never match; now uses `hash_flag()` from services
- Potential division by zero in scoring solve rate calculation
- Removed unreachable `return` statements in `api_participant_list` and `api_participant_detail`

### Security
- Add missing authorization decorators to 8 CTF API views: `api_challenge_list`, `api_challenge_detail`, `api_submit_flag`, `api_use_hint`, `api_submissions`, `api_range_status`, `api_range_access`, `api_scoreboard`
- Remove `invite_token` from API responses in `api_participant_list` and `api_participant_resend_invite`
- Replace SHA256 fallback with PBKDF2-SHA256 (600k iterations) for flag hashing when bcrypt is unavailable
- Add `# NOSONAR` annotations to hardcoded test/dev encryption keys in settings
- Add SNS topic KMS encryption in dev and prod Terraform environments
- Set `recovery_window_in_days = 7` for Secrets Manager in production (was 0)
- Pin Secrets Manager IAM policy ARNs to specific AWS account ID
- Add `#tfsec:ignore` justifications to required IAM wildcards and egress rules
- Add `# NOSONAR` annotation to dev auth bypass with justification

## [3.1.0] - 2026-03-12

### Added
- CTF admin team list, scoreboard, and analytics pages
- CTF help page with getting started content
- CTF API endpoints: event list/detail, challenge list/detail
- NGFW toggle in CTF event form (range_config)

### Changed
- CTF app uses bridge module (`ctf/bridges.py`) for all cross-domain integrations (CMS, management, mission_control)
- CTF scheduled tasks documented as database-only; no Celery dependency
- Email backend defaults to console for dev; configure via `EMAIL_BACKEND` env var for production
- Wire `EMAIL_BACKEND` and `CTF_FROM_EMAIL` through deployment pipeline (SSM → user_data.sh → Docker env → Django settings)

### Fixed
- Removed stale scheduler module reference from services docstring

### Removed
- Dead `mock_scheduler` fixture that patched non-existent `ctf.services.scheduler`

## [3.0.0] - 2026-03-11

### Added
- CTF (Capture The Flag) management platform — core app files: models, enums, services, admin, forms, migrations
- CTF config and routing integration: settings, URL routing, dashboard router, dev login user types, OIDC user type claims
- CTF views, URL routing, and templates: organizer admin views, participant views, API endpoints, 38 template files, email templates, sidebar partials
- UserProfile CTF fields: user_type, active_ctf_event, role properties (is_ctf_organizer, is_ctf_participant, is_standard_user)
- CTF test suite: 13 test files, 230 tests across models, auth, challenges, events, participant views, services (notification, range)
- CTF participant registration endpoint (`/ctf/register/`) to complete invite-link registration flow

### Fixed
- CTF invite emails never sent: `invite_participant()` and `bulk_import_participants()` prematurely set `invited_at`, causing `send_invitations()` to skip all participants
- CTF range provisioning: all ranges were created under the organizer's user, causing the second participant's range to fail the active-range check; now uses `participant.user`

### Security
- Add organizer ownership checks to 11 CTF views missing authorization: range list/provision APIs, notification list/create/send views and APIs, team list, scoreboard, analytics, and event detail API — non-owning organizers now get 403

## [2.3.3] - 2026-03-10

### Added
- SE Admin IAM Users Terraform module (`platform/terraform/global/se-admins/`) for managing PANW SE admin access to the dev AWS account

## [2.3.2] - 2026-02-24

### Fixed
- Logout button not working (GET request to POST-only `OIDCLogoutView`)

## [2.3.1] - 2026-02-24

### Added
- CyberScript DSL language reference documentation (`documentation/docs/cyberscript/`)
- Schema validators: unique instance names, `dc_config` required when `domain_controller: true`

### Fixed
- Threat Research RBAC sidebar visibility and auth redirect

## [2.3.0] - 2026-02-24

### Added
- Unified platform audit logging system
- Audit coverage for range pause/resume, experiments, scenario editor
- AuditLog entity types: experiment, scenario, script
- AuditLog actions: pause, resume, cancel
- Audit service tests (16 tests)

### Fixed
- audit_log() now swallows exceptions instead of re-raising (never breaks the application)
- Stale self.range_id references in SSH consumer after refactor
- Migrated agent events from deprecated ActivityLog to AuditLog

## [2.2.10] - 2026-02-23

### Added
- Threat Research RBAC group
- Threat Research access to Experiment Manager and Scenario Editor

## [2.2.9] - 2026-02-22

### Fixed
- Experiment runner integration fixes

## [2.2.8] - 2026-02-22

### Changed
- Finish experiment runner integration

## [2.2.7] - 2026-02-21

### Added
- Scenario Editor UAT plans

### Fixed
- Role enum validation for ScenarioTemplate

## [2.2.6] - 2026-02-21

### Changed
- Range pause/unpause uses Ready instead of Active status

## [2.2.5] - 2026-02-21

### Added
- MCP tools for SSM tunnel testing: start_portal_test_tunnel, stop_portal_test_tunnel
- localhost to ALLOWED_HOSTS in dev for tunnel access

## [2.2.4] - 2026-02-21

### Changed
- Enable dev_login in deployed dev environment for programmatic testing via SSM tunnel

## [2.2.3] - 2026-02-21

### Fixed
- Broken migration chain causes Django crash loop

## [2.2.2] - 2026-02-17

### Fixed
- Deploy script SSM waiter timeout - increased max attempts from 20 to 60 (15 minutes)

## [2.2.1] - 2026-02-16

### Changed
- Centralized script variable sanitization in Pydantic contexts for consistent and secure variable handling.
- Moved experiment template variable logic to shared `cyberscript` library to enable cross-layer reuse and validation.
- Hardened `ExperimentOrchestrator` with comprehensive exception handling and debug logging to ensure unexpected failures mark runs as FAILED rather than hanging.
- Standardized `ExperimentManager` services and views to match CMS defensive coding patterns, including uniform user validation and ORM result type checking.
- Refactored experiment creation flow to enforce model-level validation within atomic transactions.

## [2.2.0] - 2026-02-16

### Add
- Direct NGFW access for users

## [2.1.7] - 2026-02-16

### Added
- Cortex Broken Bank AMI

## [2.1.6] - 2026-02-16

### Added
- Add XDR Collector and Cloud Identity Engine agents to CMS
-
## [2.1.5] - 2026-02-15

### Changed
- Merged MCP-Shifter and MCP-NGFW into MCP-Ops
- MCP-Ops has range reconciliation tool to find and destroy orphaned instances
- Add better parsing for AWS to SonarQube

## [2.1.4] - 2026-02-15

### Fixed
- Shifter DB MCP no longer leaks connections to RDS

## [2.1.3] - 2026-02-15

### Fixed
- Failed ranges do not always get destroyed

## [2.1.2] - 2026-02-14

### Fixed
- Restrictive Egress rules in Network Firewall loosened to match XSIAM docs recommendations

## [2.1.1] - 2026-02-10

### Fixed
- Subnet `connected_to` semantics corrected: Terraform now creates security group rules on target subnet allowing traffic from source (was reversed)
- Range provisioning now reads NGFW data ENI ID from database instead of non-existent environment variable

### Changed
- Updated `connected_to` documentation to clarify unidirectional semantics (both subnets must list each other for bidirectional traffic)
- Updated basic_ngfw scenario template to have bidirectional subnet connectivity

## [2.1.0] - 2026-02-08

### Added
- Experiment Manager for creating and managing experiments

## [2.0.0] - 2026-02-07

### Added
- Scenario Editor for creating and editing CyberScript

## [1.1.3] - 2026-02-07

### Added
- Certipy to Kali AMI

## [1.1.2] - 2026-02-07

### Added
- Credentials details page

## [1.1.1] - 2026-02-07

### Changed
- Increased number of possible user subnets by decreasing subnet size

## [1.1.0] - 2026-02-06

### Changed
- Range pause/resume flow and UI updates

### Fixed
- Guacamole ECS service not deploying correctly

## [1.0.9] - 2026-02-02

### Fixed
- Claude errors due to using wrong small model
- Handle NGFW "starting" state correctly

## [1.0.8] - 2026-02-02

### Fixed
- Fix logic error handling non-NGFW scenarios

## [1.0.7] - 2026-02-01

### Fixed
- Refine Internet egress domains and CIDR to Palo Alto Networks published IPs instead of overbroad GCP IPs

## [1.0.6] - 2026-01-28

### Added
- MCP servers for Shifter DB, NGFW, and AWS ops
### Fixed
- NGFW destroy flow does not remove EC2 instances
- NGFW commands not piped to SSH as required
- Provisioner missing permission for deleting NGFW resources

## [1.0.5] - 2026-01-28

### Changed
- Updated SSH connection validation to handle difference between SSH being up and management plane being fully up

## [1.0.4] - 2026-01-28

### Fixed
- Hydrator no longer rejects empty folder fields for SCM creds

## [1.0.3] - 2026-01-27

### Fixed
- Some range boxes have unexpected Internet access

## [1.0.2] - 2026-01-25

### Added
- Range pause/resume flow and UI updates

## [1.0.1] - 2026-01-25

### Changed
- Migrated range and NGFW provisioning to Terraform

## [1.0.0] - 2026-01-21

### Added
- Cortex BYOT scenario (automation except for CIE and XDR collector)
- Cortex Deployment Experience scenario

### Changed
- Dashboard renamed to Ranges
- Ranges view uses multiple tiles for launch and active ranges
- NGFW flow handles prompting user to associate NGFW to SCM and XDR
- Removed legacy Terraform-based range provisioning
- Ubuntu box supports RDP/desktop access
- Users can set MFA to remember devices

### Fixed
- Django build does not include cyberscript shared library
- Extend and streamline NGFW stand up plan
- Dynamic subnet creation for ranges misses Shifter Platform creation
- Missing VPC route for kali
- VPC Internet egress not enforcing drop rule
- Kali RDP not working due to permissions on logs
- XDR not deployed on BYOT scenario DC
- Race condition in DC readiness and target attempt to join domain

## [0.10.7] - 2026-01-12

### Changed
- Extract all Cyberscript related code to shared library for reuse in Provisioner and Engine
-
## [0.10.6] - 2026-01-13

### Fixed
- Type conflict causes NGFW provisioning to fail
- CMS parses legacy and new range_spec formats for consumers

## [0.10.5] - 2026-01-12

### Fixed
- Provisioner ID mismatch causes range create status update to fail
- Range subnets have no route to s3 for agent downloads

## [1.0.4] - 2026-01-12

### Changed
- Extracted ssh key generation to shared library

## [1.0.3] - 2026-01-12

### Added
- Additional local dev support

### Fixed
- Provisioner ID mismatch causes range create status update to fail

## [1.0.0] - 2026-01-10

### Added
- NGFW create/destroy flow and UI
- NGFW's dynamically add routes for subnets in user ranges
- NGFW's dynamically pause if user has no active ranges
- CyberScript (DSL) templates and initial interpreter for all range operations (range, ngfw, dc, etc.)
- v1.0 of the Cortex BYOT scenario template
  - Two config options: Automated or Full Manual
  - Automated: NGFW, DC, 2x Workstations, Server, Attacker, domain join, XDR agent install, subnet routing
    - Remaining manual (automation coming soon): CIE, XDR Collector, Caldera
- Improved Bedrock logging and alarms
- Draft Cortex BYOT scenario template
- venv enforcer hook for Claude Code
- Guacamole RDP for Range instances
- User (not just technical) docs in Shifter

### Changed
- NGFW models and services refactored to use schemas
- Extended DSL and initial DSL interpreter implementation for NGFW flows
- Templates refactored to use CyberScript DSL
- Engine refactored to accept RequestSpec and interpret it into Engine models
- CyberScript subnets align with actual subnets in AWS
- AaC gate (service layer boundary violations at code or model level) fails will now block PRs
- AWS assets tagged to requests for cost tracking and cleanup
- Patched vulnerable urllib3, now on 2.6.3
- Update technical docs

### Fixed
- Dashboard range status updates and styling
- Better AaC checking in check_layer_imports script
- Sticky sesesions on Linux terminals: keep history, scrollback, etc when reconnecting
- tmux now used for Terminal UI sessions
- RDP copy/paste not working
- Packer does not clean up EC2 instance after build
- tmux Terminal UI sessions not allowing mouse scrolling

## [0.10.6] - 2025-01-09

### Added
- Guacamole RDP for Range instances

### Fixed
- tmux now used for Terminal UI sessions

## [0.10.5] - 2025-01-06

### Changed
- Added tmux install to Kali and Ubuntu AMIs

## [0.10.4] - 2025-01-06

### Fixed
- Hotfix for Home subnet CIDR conflict detection

## [0.10.3] - 2025-01-04

### Changed
- user_data for Shifter Platform deployment and ASG lifecycle hook

### Fixed
- Terminal timeouts, reconnects, and stability issues
- Range instance username mismatch

## [0.10.2] - 2025-01-04

### Changed
- GitHub runners replaced with auto-scaling ephemeral runners via terraform-aws-github-runner module
  - Scale from zero on workflow trigger
  - EC2 spot instances for cost savings
  - GitHub App authentication for secure runner registration
- Added runner-deploy.sh script for runner infrastructure management
- Added manual-deployment.md documentation for global terraform stacks

## [0.10.1] - 2025-01-02

### Added
- Cyber range DSL foundation (Shared Schema)
- Interactive cli app for Shifter AWS account bootstrap and infrastructure deployment
- Arch as Code foundation: Code and model level service layer boundary violation detection in CI/CD and pre-commit
- Independent processes consume range status updates
- Claude develop skill
- Centralized code coverage reporting

### Changed

- CMS services extraction edge cases and fixes
- Mission Control re-wire to use services
- Engine services extraction and implementation (excl pause/resume)
  - NGFW services deferred to upcoming patch
  - Mission Control re-wire deferred to upcoming patch
- Model migrations to respect service layer separation
- Redis replication for HA (single-node in dev, replication group in prod)
- SNS/SQS for range status updates with alarms
- Fault-tolerant fully alarmed range status consumer processes
- Unit test coverage improvements

### Fixed
- In-depth help check short circuited by Django middleware
- Remove dead code from service layer refactoring
- Frontend tests not included in pre-commit
- Remove stale Celery references
- Linting
- Some tests not called
- Pre-commit and CI/CD test, lint, quality, and sast coverage
- SonarQube coverage exclusions
- Tests for repo utility apps and Architecture as Code tests

## [0.10.0] - 2025-01-01

### Added
- CMS services extraction and implementation
- Unified Credential model

## [0.9.9] - 2025-12-31

### Added
- Management services implementation
  - cognito_sub update service
  - activity log service
  - user profile service

### Changed
- OIDC backend updated to use management services
- User profile model moved to management domain
- Activity log model moved to management domain

## [0.9.8] - 2025-12-31

### Added
- Portal NGFW Management UI (#416)
  - NGFW list view at `/mission-control/assets/ngfw/`
  - NGFW detail view with AWS resources, PAN-OS info, linked ranges
  - 5-step setup wizard (Name & Credentials → Registration → Confirm → Provisioning → Complete)
  - Deprovision confirmation view with linked ranges warning
  - API endpoints:
    - `GET /api/ngfw/list/` - List user's NGFWs
    - `POST /api/ngfw/` - Start provisioning
    - `GET /api/ngfw/<id>/status/` - Poll provisioning status
    - `POST /api/ngfw/<id>/start/` - Start NGFW
    - `POST /api/ngfw/<id>/stop/` - Stop NGFW
    - `POST /api/ngfw/<id>/deprovision/` - Deprovision NGFW
  - WebSocket consumer for real-time provisioning status updates
  - XDR manual configuration instructions with serial number display
  - 62 tests covering all views and APIs
- Test review skill (`.claude/skills/test-review/`)
  - 6 quality criteria with specific fail indicators
  - Anti-pattern catalog by severity (HIGH/MEDIUM/LOW)
  - Coverage gap detection checklist
  - Scoring formula and fix guidance

### Note
- NGFW API endpoints are stubbed pending Issue #414 (UserNGFWStack)
- UI is complete and functional with simulated provisioning flow

## [0.9.7] - 2025-12-30

### Security
- Hardened GitHub Actions OIDC IAM permissions to limit blast radius (#430)
  - Restricted `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PutRolePolicy` to specific role name patterns
  - Restricted `iam:CreateInstanceProfile` to matching instance profile patterns
  - Restricted `iam:PassRole` to same role patterns
  - Allowed patterns: `dev-portal-*`, `prod-portal-*`, `dev-range-*`, `prod-range-*`, `shifter-*`, `github-actions-shifter-*`
  - Prevents attacker from creating arbitrary roles with `AdministratorAccess` if GHA is compromised

## [0.9.6] - 2025-12-30

### Added
- S3 cost budget alerts for dev and prod environments
  - Defense-in-depth monitoring for unusual S3 costs
  - Alerts at 80% of $50/month threshold

## [0.9.3] - 2025-12-30

### Added
- Windows victim AMI Packer build (#410)
  - `windows.pkr.hcl` Packer template with WinRM communicator
  - PowerShell provisioning scripts: base, services, tools, claude-code, sysprep
  - XAMPP, IIS, FTP Server, OpenSSH Server
  - Python 3.12, Node.js 20.x, Git
  - Claude Code configured for Bedrock (system PATH at `C:\Program Files\nodejs`)
  - WinRM enabled for remote management
  - Windows Defender disabled via GPO for XDR compatibility
  - EC2Launch v2 sysprep for AMI finalization
- GitHub Actions workflow support for Windows AMI builds

### Changed
- Updated packer README with Windows AMI documentation
- Updated victim-ami.md with Packer build instructions

## [0.9.2] - 2025-12-30

### Added
- Ubuntu victim AMI Packer configuration (#409)
  - `ubuntu.pkr.hcl` template following Kali pattern
  - Provisioning scripts: base.sh, services.sh, tools.sh, claude-code.sh
  - Services: Apache 2.4 with mod_php, MySQL 8.0, Docker, OpenSSH, vsftpd, Samba
  - Development tools: build-essential, Python 3, Node.js 20.x, Git
  - Claude Code configured for AWS Bedrock
- GitHub Actions workflow support for Ubuntu AMI builds
- Ubuntu test classes in shifter/packer/tests/test_packer.py

### Changed
- SSM parameter for victim AMI renamed from `/shifter/ami/victim` to `/shifter/ami/ubuntu`
- Terraform data sources updated for new SSM parameter name

## [0.9.1] - 2025-12-30

### Changed
- Engine architecture refactor (#413)
  - Executors moved to `executors/` (ssm_executor, ssh_executor)
  - Orchestrators moved to `orchestrators/` (setup_orchestrator)
  - Plans moved to `plans/` (setup_plan.py → base.py)
  - RangeStack moved to `stacks/`
  - New: `AWSExecutor`, `OpsOrchestrator` stubs
  - New: Base protocols for executors and orchestrators

## [0.9.0] - 2025-12-30

### Added
- NGFW database models for persistent per-user NGFW support (#412)
  - `SCMCredential` model for Strata Cloud Manager PIN-based registration
  - `NGFWDeploymentProfile` model for Software NGFW Credits authcodes
  - `UserNGFW` model for persistent NGFW instances
  - `Asset` and `Credential` abstract base classes with soft delete and expiration
- Field-level encryption for sensitive credentials using `django-encrypted-model-fields`
  - `scm_pin_value` and `authcode` fields encrypted at rest
  - `FIELD_ENCRYPTION_KEY` environment variable required in production
- Range model fields for NGFW integration
  - `ngfw` FK to UserNGFW (SET_NULL on delete)
  - `gwlb_endpoint_id` for GWLB endpoint tracking
- Django admin for new models (SCMCredential, NGFWDeploymentProfile, UserNGFW)
- Database grants for provisioner_lambda user on new tables
- NGFW infrastructure foundation for persistent per-user NGFW instances (#408)
  - Dedicated /22 subnet (10.1.4.0/22) for ~500 NGFW capacity
  - Management security group (SSH/HTTPS from Portal for management)
  - Dataplane security group (all VPC traffic via GWLB)
  - IAM role with S3 bootstrap read and CloudWatch Logs access
  - CloudWatch alarm for NGFW capacity (>400 triggers SNS alert)
  - Terraform outputs for Engine/Pulumi consumption

### Removed
- `StrataConfig` model (superseded by `SCMCredential` and `NGFWDeploymentProfile`)
- Range fields: `ngfw_enabled`, `strata_config`, `ngfw_instance_id`, `ngfw_untrust_ip`, `ngfw_trust_ip`

## [0.8.9] - 2025-12-29

### Added
- Packer infrastructure for reproducible AMI builds (#273)
- sshpass in Kali AMI for non-interactive SSH (#273)
- GitHub Actions workflow for AMI builds

## [0.8.8] - 2025-12-29

### Changed
- Remove redundant SSH security group rules (#290)

## [0.8.7] - 2025-12-29

### Added
- `standup_duration` property on Range model for tracking provisioning time

## [0.8.6] - 2025-12-29

### Changed
- Remove Step Functions permissions from GitHub OIDC role (cleanup after v1 provisioner removal)

## [0.8.5] - 2025-12-29

### Fixed
- Dashboard dropdown behavior and portal test stability

## [0.8.4] - 2025-12-29

### Changed
- Extract service layer from views.py (engine, cms apps)
- Centralize Range status groupings as frozenset constants

## [0.8.3] - 2025-12-29

### Changes
- Refactor consumers.py for maintanability

## [0.8.2] - 2025-12-27

### Added
- NGFW (VM-Series) support
- Strata Cloud Manager support
- Cortex XDR sidebar submenu styling
- Asset Menu

### Changes
- GitGuardian and Snyk ignore tests

## [0.8.1] - 2025-12-27

### Changed
- Migrate all instances to Shifter Engine
- Docs updated to reflect new architecture and naming conventions

## [0.8.0] - 2025-12-27

### Added
- Domain controller AMI
- Basic AD scenario option with AD join by Windows
- Re-factor Shifter Engine scenario generation for extensibility

### Changed
- SonarQube ignores test files

## [0.7.20] - 2025-12-24

### Added
- JavaScript unit tests for DirectUploader (upload.js) with Jest (#136)
  - 79 tests covering happy paths, failure modes, edge cases, order of operations
  - Proper mocks for fetch, XMLHttpRequest, navigator.sendBeacon, window events
  - `make test-js` and `make test-js-coverage` Makefile targets
  - CI integration via `portal-js-tests` job in quality workflow

## [0.7.19] - 2025-12-24
- Add TDD planning Claude Code skill

## [0.7.18] - 2025-12-24

### Added
- Claude Code Skills for common repo/ops tasks

## [0.7.17] - 2025-12-24

### Changed
- Risk register app is accessible only by admin
- Removed History sidebar item (not yet working)
- Terminal page and link handles no active range gracefully

## [0.7.16] - 2025-12-23

### Added
- Developer documentation section (`docs/dev/`) with onboarding guides
  - Local setup, CI/CD, secrets management, Terraform patterns, engineering principles
- Commit tfvars to repository (no longer gitignored)
- Dev-box admin password auto-generated and stored in Secrets Manager

### Changed
- Removed `*.tfvars` from `.gitignore` - config values are not secrets
- Dev-box no longer requires manual password in tfvars

### Removed
- `terraform.tfvars.example` files (redundant now that tfvars are committed)
- `admin_password` variable from dev-box Terraform

## [0.7.15] - 2025-12-23

### Added
- Documentation section in Mission Control sidebar
- Renders markdown docs from `shifter/shifter_platform/documentation/docs/` with navigation tree
- Mermaid.js diagram support for architecture diagrams
- Cortex XDR dark theme styling for documentation pages

## [0.7.14] - 2025-12-22

### Fixed
- Terminal UI text overflows container

## [0.7.13] - 2025-12-22

### Fixed
- Terminal UI does not show IP address for Windows victims

## [0.7.12] - 2025-12-22

### Added
- Windows victim support in provisioner v2
- Windows victim AMI v3 with XAMPP, Claude Code, Python, Git, IIS, FTP, OpenSSH
- Terminal UI SSH support for Windows victims (Administrator username)
- Database migration granting provisioner SELECT on operatingsystem table

### Fixed
- Range destroy race condition leads to subnet collision
- Django logs not forwarded to CloudWatch
- Windows AMI sysprep: Claude Code installed to system path (`C:\Program Files\nodejs`)
- Windows Defender disabled via policy to avoid XDR conflicts

## [0.7.11] - 2025-12-21

.deb and .rpm packages confirmed fix as part of provisioner v2 in 0.7.7

### Added
- Provisioner confirms assigned subnet index is available before provisioning

### Fixed
- Kali boots slow due to redundant kali headless install
- Failed range auto-cleanup not running in dev

## [0.7.10] - 2025-12-21

### Fixed
- Provisioner fails to install .deb or .rpm agent packages properly
- Provisioner fails to rollback range if agent installation fails

## [0.7.9] - 2025-12-21

### Fixed
- Provisioner uses vars for instance types instead of hardcoded values

## [0.7.8] - 2025-12-21

### Added
- Standing dev box instance for development and testing

## [0.7.7] - 2025-12-21

### Added
- Pulumi-based provisioner for declarative multi-OS range infrastructure
  - ECS Fargate execution with Step Functions orchestration
  - S3/DynamoDB state backend, ECR container registry
  - Reusable components: NetworkComponent, InstanceComponent, RangeStack
  - Instance catalog supporting Kali, Ubuntu, Windows, Amazon Linux
- CI/CD workflow for Pulumi provisioner (`_pulumi-provisioner.yml`)
- Django model fields and service routing for v1 (Lambda) / v2 (Pulumi) provisioners
- Self-hosted GitHub Actions runner for CI/CD

### Changed
- Range instance types bumped to t3.medium (4GB min for Claude Code)
- CI Docker builds use local caching instead of GitHub Actions cache

### Fixed
- Secrets Manager resources now Pulumi-managed (proper lifecycle, no orphans)
- KMS policy, DNS egress, availability zone configuration for ECS tasks
- WebSocket terminal consumer reads from `provisioned_instances` field (v2 provisioner compatibility)

### Removed
- V1 (Lambda) provisioner

## [0.7.6] - 2025-12-19

### Added
- ALB access logs, VPC flow logs, RDS log exports, WAF logging
- XDR CloudTrail integration via CloudFormation (dev and prod)
- CloudWatch alarms for log aggregation (Firehose delivery lag, SQS DLQ)

### Changed
- Replaced Checkov skip comments with actual implementations (CKV_AWS_91, CKV2_AWS_11, CKV_AWS_129)
- Removed unused XDR IAM from Terraform (managed by CloudFormation instead)

### Fixed
- Multiple code quality, security, and code smells

## [0.7.5] - 2025-12-18

### Added
- AWS WAF protection for ALB with rate limiting and AWS managed rules

## [0.7.4] - 2025-12-18

### Added
- ElastiCache Redis module for Django Channels
- Portal autoscaling: launch template, ASG, scaling policies, CloudWatch alarms
- ALB session stickiness for WebSocket affinity
- Lambda auto-fix for range security group SSH rules from Portal VPC

### Changed
- Django Channels uses Redis when `REDIS_HOST` env var set, falls back to InMemory
- EC2 module supports single instance or ASG mode via `enable_autoscaling` flag
- Dev environment: autoscaling enabled with 2 instances
- GitHub Actions portal workflow supports ASG deployment via SSM targeting by tag
- IAM: Added `elasticache_asg` policy for ElastiCache, Auto Scaling, and Launch Template permissions

## [0.7.3] - 2025-12-17

### Fixed
- VPC peering TF drift dev/prod

### Fixed
- Network Firewall blocking XDR agent egress to Cortex cloud
  - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
  - Added Suricata rule to block direct IP connections (SNI bypass prevention)
- XDR agent not registering with tenant after installation
  - Added cortex.conf deployment before running installer script

## [0.7.2] - 2025-12-17

### Changed
- Removed redundant connection status from terminal header
- Increased terminal padding for better readability

## [0.7.1] - 2025-12-16

### Fixed
- XDR agent not installing on victim EC2 instances (#274)
  - Root cause: User data script used `aws s3 cp` but victim EC2 lacks AWS CLI
  - Changed to presigned URL + curl for agent download (no AWS CLI required)
  - Added SSM-based agent verification before marking range as ready
- CI/CD pipeline not updating Step Functions and Lambdas on code changes
  - Root cause: Missing `output_file_mode` in `archive_file` caused inconsistent zip hashes across CI runners
  - Added `output_file_mode = "0666"` to all Lambda archive_file blocks
  - Extracted Step Functions definitions to external ASL JSON files with `templatefile()`
- Dashboard polling errors when session expires during range provisioning
  - CORS errors occurred when API redirected to Cognito for re-authentication
  - Added session expiration detection and automatic redirect to login page
  - Network Firewall blocking XDR agent egress to Cortex cloud
    - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
    - Added Suricata rule to block direct IP connections (SNI bypass prevention)
  - XDR agent not registering with tenant after installation
    - Added cortex.conf deployment before running installer script

### Added
- Agent verification step in provisioning workflow
  - New `verify_agent` Lambda checks installation via SSM RunCommand
  - Step Functions retry loop with 30s intervals (5 min max)
  - Ranges fail fast with descriptive error if agent install fails
- External ASL state machine definitions for better maintainability
  - `provision_range.asl.json`, `teardown_range.asl.json`, `cleanup_stale_ranges.asl.json`

## [0.7.0] - 2025-12-16

### Added
- Claude Code on Kali and Victim AMIs for AI-assisted penetration testing
  - Configured for Amazon Bedrock (no internet required)
  - Role-specific CLAUDE.md system prompts for each instance type
  - Kali: Authorized pentester role with subnet-only scope
  - Victim: Scenario setup assistant for vulnerable configurations
- Bedrock VPC endpoints (bedrock-runtime, sts) for Range VPC
- Bedrock IAM permissions for range instance role

### Changed
- Increased Portal EC2 instance to t3.large (from t3.micro) for WebSocket stability
- Increased Kali and Victim instances to t3.small for Claude Code memory requirements

## [0.6.0] - 2025-12-16

### Added
- Browser-based Terminal UI for SSH access to range instances (#267)
  - Side-by-side Kali and Victim terminal panes with xterm.js
  - WebSocket-based SSH via Django Channels
  - Terminal sidebar menu item with active range indicator
- VPC peering between Portal and Range VPCs for SSH connectivity
- Security group rules allowing SSH from Portal to range instances

### Changed
- Switched from Gunicorn (WSGI) to Daphne (ASGI) for WebSocket support

### Fixed
- Buttons should not have underline

## [0.5.4] - 2025-12-15

### Removed
- OpenWebUI/AgentChat infrastructure (#261)
  - Deleted agentchat Terraform modules and environments
  - Removed MCP-Shifter and OpenWebUI MCP wrapper code
  - Removed agentchat GitHub Actions workflows
  - Removed ECR repositories for openwebui and mcp-shifter
  - Removed Cognito agentchat client
  - Removed openwebui_db Secrets Manager secret
  - Removed agentchat documentation
  - Removed migrations for victim_mcp_user and kali_mcp_user rename
- Entire MCP directory (`mcp/`) including aptl-mcp-common and mcp-red

### Changed
- Architecture updated: Chat UI replaced with planned browser-based terminal (Django Channels)
- `chat_base_url` now optional in provisioner module (empty string allowed)
- Updated CLAUDE.md and architecture docs to reflect new terminal-based approach

## [0.5.3] - 2025-12-15

### Added
- TARGET_MODE parameterization for MCP-Shifter (`kali` or `victim`)
  - Same binary serves both target types via environment variable
  - Dynamic column selection based on target mode
  - Tool prefixes match target type (`kali_*` or `victim_*`)
- Victim MCP database user (`victim_mcp_user`) for operational isolation
- Renamed `mcp_user` to `kali_mcp_user` for consistency
- SSM VPC Endpoints for Range VPC (ssm, ssmmessages, ec2messages)
  - Enables Systems Manager access without internet
  - Traffic stays within AWS network
- Custom OpenWebUI Docker image with Cortex theme baked in
  - ECR repository for custom OpenWebUI image
  - Dockerfile extends base image with custom CSS/assets
  - CI/CD builds and deploys themed image automatically
- Victim MCP wrapper for OpenWebUI (`mcp_wrapper_victim.py`)

### Changed
- Replaced mcp-red with mcp-shifter in CI quality workflow
- Architecture docs updated with MCP dual-container diagram
- AgentChat uses custom OpenWebUI image instead of stock ghcr.io image

## Fixed
- Missing s3 permissions to fetch XDR installer
- Fix range user_data fails to account for different installer types

## [0.5.2] - 2025-12-15

### Changed
- Reskin OpenWeb UI UX to match Cortex XDR look and feel

## [0.5.1] - 2025-12-15

### Added
- AWS Network Firewall for Range VPC egress filtering (#251)
- NAT Gateway for private subnet internet access
- Domain allowlists: Victim restricted to XDR endpoints, Kali has no external access

## [0.5.0] - 2025-12-14

### Added
- MCP-Shifter server for OpenWebUI integration (`mcp/mcp-shifter/`)
  - Cognito JWT authentication with per-user session management
  - RDS IAM authentication for range lookup
  - Secrets Manager integration for SSH key retrieval
  - Session limits (per-user and global) with structured logging
  - Idle connection cleanup timer
  - StreamableHTTPServerTransport for MCP over HTTP
- OpenWebUI MCP wrapper tool (`mcp/openwebui-mcp-wrapper/`)
- `cognito_sub` column on Range model for MCP user lookups
- Custom OIDC backend passing Cognito `sub` claim to Range model
- Security context in MCP server description (authorized pentest boundaries)
- VPC peering between Portal VPC and Range VPC for SSH connectivity
- ALB listener rules for `/chat` and `/mcp` path routing
- IAM policies for MCP server (RDS connect, Secrets Manager read)
- Security group rules for SSH from AgentChat to Kali instances
- Cognito app client for OpenWebUI OIDC authentication
- AgentChat docker-compose for local development (`agentchat/`)
- SSH keypair generation in create_kali Lambda (stored in Secrets Manager)
- `kali_ssh_key_secret_arn` field on Range model

### Changed
- AgentChat deployment workflow includes mcp-shifter container
- mark_ready Lambda sets chat_url when range becomes ready
- - AgentChat routing changed from subpath (`/chat/`) to subdomain (`chat.{domain}`)
- ACM certificate includes SAN for `chat.{domain}` subdomain
- Cognito OAuth callbacks updated for subdomain URLs
- ALB listener rules use `host_header` matching instead of `path_pattern`
- Docker layer caching added to portal and agentchat CI/CD workflows (faster builds)

## [0.4.5] - 2025-12-15
### Changed
- Reskin Portal and Risk Register to Cortex XDR look and feel

## [0.4.4] - 2025-12-14

### Changed

- Upgraded patch @modelcontextprotocol/sdk

## [0.4.3] - 2025-12-13

### Added
- Risk Register Django app
-
## [0.4.2] - 2025-12-13

### Added
- OpenWebUI + Bedrock Access Gateway (BAG) for AgentChat
- Sonnet 4.5 and DeepSeek R1 models for AgentChat
- AgentChat infrastructure
- Checkov IaC security scanning in CI and pre-commit
- Dockerfile HEALTHCHECK for portal container

### Changed
- SonarCloud coverage extended to all modules
- GitHub Actions workflows: explicit permissions, removed workflow_dispatch inputs where not needed
- Use SonarQube Cloud automatic analysis instead of CI/CD workflows

### Security
- Full review of lint (ruff, bandit, eslint) and IaC (checkov) findings
- Fixed critical issues: workflow permissions, Dockerfile healthcheck
- Created issues (#214-222) for deferred security hardening (WAF, flow logs, KMS, etc.)
- All checkov findings now have explicit skip comments with issue references

## [0.4.1] - 2025-12-12

### Removed
- LibreChat
- LiteLLM

## [0.4.0] - 2025-12-12

### Added
- Dev environment (`terraform/environments/dev/`)
- Branch-based deployments: `dev` branch → dev, `main` branch → prod
- Bootstrap script for new AWS accounts (`scripts/bootstrap-dev.sh`)

### Changed
- All workflows support environment selection via branch or manual dispatch
- Streamline GitHub Actions workflows for consistency
- Utility scripts work with dev and prod environments
- User updated immediately when range deploy fails

## [0.3.6] - 2025-12-11

### Fixed
- Remove default value from s3_bucket_arn variable (module variables should have no defaults)

## [0.3.5] - 2025-12-11

### Changed
- Make no versioning on user data s3 bucket explicit

## [0.3.4] - 2025-12-11

### Added
- AWS Bedrock as LibreChat LLM provider

### Changed
- LibreChat EC2 instance rebuilds on user_data changes

## [0.3.3] - 2025-12-11

### Changed
- RDS deletion protection enabled for prod database
- Final snapshot enabled before RDS deletion

## [0.3.2] - 2025-12-11

### Added
- Kali EC2 provisioning Lambda (create_kali) with official AWS Marketplace AMI
- Kali security group in Range VPC with bidirectional victim traffic
- kali_instance_id and kali_ip fields on Range model
- Kali cleanup in teardown Lambda
- Range VPC security documentation (security groups, traffic matrix, isolation)

### Changed
- Victim security group now allows all inbound from Kali SG (for attacks)
- Kali security group allows all inbound from Victim SG (reverse shells, C2)

## [0.3.1] - 2025-12-11

### Added
- LibreChat infrastructure (EC2, dedicated subnet, Secrets Manager, Docker Compose)
- LibreChat CI/CD workflows (infra and deploy)
- SSM tunnel script for LibreChat admin access

### Fixed
- Portal/LibreChat infra workflows now trigger on direct push to main, not just upstream cascade

## [0.3.0] - 2025-12-11

### Added
- Provisioner fields on Range model (subnet_id, subnet_cidr, subnet_index, victim_instance_id, step_function_execution_arn)
- IAM Database Authentication on RDS for Lambda provisioner
- Django migration to create provisioner_lambda PostgreSQL user with minimal permissions
- Provisioner Lambda functions (create_subnet, create_victim, create_kali, configure_librechat, cleanup)
- Step Functions state machines for provisioning and teardown with error handling and timeouts
- Victim security group in Range VPC
- Provisioner module wiring to Portal VPC with remote state references
- Portal integration with Step Functions (replaces callback-based stub)
- EC2 IAM permissions for Step Functions execution
- Range failure alarms
- Stale range cleanup
- docs/maintenance.md: RDS maintenance window reference

### Fixed
- Lambda DB queries: `agent_config_id` → `agent_id`, `os_type_id` → `os_id` (Django FK naming)
- Lambda handlers: `range_id[:8]` slice on integer (range_id is int, not UUID)
- db-connect.sh: Added autocommit for INSERT/UPDATE queries
- IAM policy: Fix `ec2:CreateSubnet` permission (unsupported `ec2:Vpc` condition key)
- Cleanup Lambda: Allow teardown from `ready` state (mark_failed=false)

### Removed
- Callback endpoint for provisioner (Lambda writes directly to DB)

## [0.2.9] - 2025-12-09

### Fixed
- AWS_REGION mismatch
- ALB health check errors
- Update docs

## [0.2.8] - 2025-12-09

### Fixed
- Range provisioner missing env var for domain
- Remove default site url for range provisioner

## [0.2.7] - 2025-12-09

### Added
- Dashboard Range launch flow with live status polling
- Range API endpoints (status, launch, cancel, destroy, callback)
- Range model status fields (pending, provisioning, ready, paused, resuming, destroying, destroyed, failed)
- Stub provisioner service with HMAC-signed callback tokens
- Client-side DashboardManager for state management
- State transition validation to prevent callback replay attacks

## [0.2.6] - 2025-12-08

### Fixed
- Upload lock clears on page navigation/error (beforeunload + 30s timeout fallback)

## [0.2.5] - 2025-12-08

### Added
- 2GB file upload via presigned S3 URLs with progress indicator
- 5GB per-user storage quota
- Upload cancel/abort support
- S3 CORS configuration for browser uploads
- S3 lifecycle rule for orphan cleanup

## [0.2.4] - 2025-12-08

### Fixed
- Logout now clears Cognito session (redirects to Cognito /logout endpoint)
- Local dev logout uses dev_logout instead of OIDC logout

## [0.2.3] - 2025-12-08

### Fixed
- Agent uploads failing: container now uses EC2 instance role via IMDSv2

### Removed
- Static IAM user credentials for portal container

## [0.2.2] - 2025-12-08

### Added
- Agent upload to S3 with magic byte validation
- File type validation (.msi, .zip, .tar.gz, .tgz, .deb, .rpm)
- Agent delete with S3 cleanup
- S3 bucket env var in deploy workflow

## [0.2.1] - 2025-12-08

### Added
- Mission Control data models (OperatingSystem, UserProfile, AgentConfig, Range, ActivityLog)
- Django admin registration for all models
- UserProfile auto-creation signal
- Model unit tests (21 tests, 100% coverage)

## [0.2.0] - 2025-12-08

### Added
- Mission Control UI shell (Dashboard, Agents, History, Settings, Help)
- Dev auth bypass for local testing
- User stories: Help, Language, Notifications

## [0.1.19] - 2025-12-08

### Changed
- Updated license to proprietary
- Block access to /admin from public internet

## [0.1.18] - 2025-12-08

### Changed
- Improved portal coming soon page design

## [0.1.17] - 2025-12-08

### Fixed
- Insecure TLS config in MCP HTTP client (removed global NODE_TLS_REJECT_UNAUTHORIZED)
- Portal deploy/infra workflow race condition (workflow_run trigger + concurrency)

### Security
- Upgraded @modelcontextprotocol/sdk to 1.24.3 (CVE-2025-66414 DNS rebinding fix)

## [0.1.16] - 2025-12-08

### Changed
- README update

## [0.1.15] - 2025-12-07

### Added
- Landing page at / to prevent redirect loop after OIDC auth

## [0.1.14] - 2025-12-07

### Fixed
- Cognito secret retrieval from Secrets Manager (issuer -> issuer_url key)

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.12] - 2025-12-07

### Added
- Range VPC module - stable VPC, IGW, route table
- Range environment config
- Range infrastructure workflow
- Range infrastructure documentation

## [0.1.11] - 2025-12-07

### Added
- Cognito Terraform module (user pool, client, hosted UI domain)
- Pre-signup Lambda for email domain restriction
- Auth architecture docs
- Wire Cognito into portal environment
- EC2 module accepts list of secret ARNs
- IAM permissions for Cognito and Lambda
- Django OIDC integration (mozilla-django-oidc)
- Entrypoint fetches Cognito secrets from Secrets Manager
- Deploy workflow passes COGNITO_SECRET_ARN to container

## [0.1.10] - 2025-12-07

### Fixed
- Hardcoded domain in Django ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS replaced with domain from tfvars secret

## [0.1.9] - 2025-12-07

### Fixed
- IAM permissions for SSM SendCommandToInstances
- Staticfiles directory permission error in container

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.8] - 2025-12-07

### Added
- Django portal Docker setup (multi-stage Dockerfile with uv)
- Container entrypoint with DB wait, migrations, gunicorn
- docker-compose.yml for local dev with Postgres
- Makefile with dev commands (up, down, build, logs, shell, migrate, init)
- GitHub Actions workflow for portal build, ECR push, SSM deploy
- Portal dev documentation
- Secrets management: IAM user for prod, Secrets Manager for DB + app secrets

### Changed
- Architecture docs updated with portal deployment pipeline
- GitHub OIDC role gets SSM permissions for deployments

## [0.1.7] - 2025-12-07

### Added
- Portal EC2 module (Docker host, SSM access, ECR/Secrets Manager IAM)
- Portal ALB module (ACM certificate, HTTPS listener, target group)
- Environment wiring with terraform_remote_state for ECR
- IAM permissions for EC2, ELB, ACM
- Security documentation
- Ethics documentation
- Disclaimer in README

### Changed
- Architecture docs updated for EC2+ALB (was ECS)
- ECR authentication via credential helper (replaces manual docker login)

### Security
- IMDSv2 enforced on EC2 (SSRF mitigation)
- ALB drops invalid HTTP headers
- ACM certificate validation with 45m timeout

## [0.1.6] - 2025-12-05

### Fixed
- Missing IAM permissions for ec2:ModifySubnetAttribute and iam:CreateServiceLinkedRole (RDS)

## [0.1.5] - 2025-12-05

### Added
- Portal VPC module (public/private subnets, NAT gateway)
- Portal RDS module (PostgreSQL, Secrets Manager credentials)
- Namespaced tfvars sync script (`TF_VARS_{ENV}_{COMPONENT}`)
- IAM permissions for VPC, RDS, Secrets Manager, KMS

## [0.1.4] - 2025-12-05

### Added
- Terraform foundation infrastructure (ECR module, global IAM, environment structure)
- GitHub Actions OIDC authentication for AWS
- CI/CD workflow for infrastructure deployment
- Version bump script

## [0.1.3] - 2025-12-05

### Added
- MkDocs with Material theme
- Documentation site (architecture, setup, API reference)
- GitHub Actions workflow for automatic GitHub Pages deployment
- Mermaid.js diagrams in architecture docs

## [0.1.2] - 2025-12-04

### Added

- Image assets for docs

### Changed
- Updated CLAUDE.md to reflect new architecture
- Removed unused files from .gitignore
- Only run mcp tests on code change

## [0.1.1] - 2025-12-04

### Added
- SonarCloud integration
- Build and test workflow
- Quality gate badge to README

### Fixed
- npm version mismatch

### Changed
- Upgraded vitest from 1.x to 4.x (required code changes to test files due to breaking changes)
## [0.1.0] - 2025-12-04

### Added
- Initial Shifter architecture for self-service cyber range platform
- Core MCP library (`mcp/aptl-mcp-common`) with SSH session management
- Reference MCP server (`mcp/mcp-red`) as template for new MCPs
- SonarCloud integration with automated code quality scanning
- Test coverage reporting via vitest with lcov output

### Changed
- Forked from APTL (Advanced Purple Team Lab) with new direction

### Removed
- All Docker/Wazuh infrastructure (replaced by XDR/XSIAM integration)
- Container definitions (kali, victim, gaming-api, minetest, minecraft, reverse)
- CTF scenarios (will be AI-generated dynamically)
- Local deployment scripts
