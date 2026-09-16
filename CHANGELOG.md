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
* finish nazgul GCP standup — Helm metadata netpol, evidence read, polaris verify-stack ([d28af86](https://github.com/Brad-Edwards/shifter/commit/d28af86019f84cc36f56927d1d34f641dbe9b26b))
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
* grant packer SA bucket-metadata reader on gdc-vm-images (GDC export + polaris stack fetch) ([77f0e9b](https://github.com/Brad-Edwards/shifter/commit/77f0e9ba2688f21bba24f044d703bc3256483afe))
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
* polaris splice helper hands off to a14-kali's real entrypoint path ([e028a88](https://github.com/Brad-Edwards/shifter/commit/e028a880fc10a3d7a96ab5a0dbfd480a597fc47b))
* **polaris:** preserve splice credential on recreation ([3c497cc](https://github.com/Brad-Edwards/shifter/commit/3c497cc83b568595593e4cc7ba0f0e4c94752868))
* **polaris:** preserve splice credential on recreation ([9b0f5a9](https://github.com/Brad-Edwards/shifter/commit/9b0f5a9c4dbb094a0a820a1498520420417040e5))
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
* supply bake-time DC01_IP so polaris dns service starts during polaris-vm bake ([853ea93](https://github.com/Brad-Edwards/shifter/commit/853ea93caf4fbd810c832ff0c50d29bff163eb31))
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
- Removed live AWS infrastructure identifiers (account IDs, VPC/subnet IDs, account- and UUID-suffixed S3 bucket names, a Secrets Manager ARN, and a console sign-in URL) from tracked operational tooling — github-runner and Packer dev var files, the polaris-aws-range scripts, the tssummit and se-admins Terraform, the Polaris bake workflow, deprecated docs, and historical CHANGELOG entries — and deleted committed prod EC2 inventory dumps. A new `adr_guard` check (ADR-004-R14, `no-live-cloud-identifiers`) scans tracked files in pre-commit and CI and blocks reintroduction; values that must stay exact (vendor connector templates, Terraform backend/state buckets read by `terraform init`, synthetic test fixtures) are cleared via scoped `docs/adr/exceptions.yaml` entries. (#936)
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
- **GCP range cells now enforce fail-closed network and guest-identity boundaries.** Oversized or overlapping subnet bindings and universal firewall allows are rejected before cloud mutation, cross-range rules remain scoped to deterministic cell tags, and only Polaris hosts that need host-side cloud access receive the least-privilege range-host service account. (#1345)
- Gated the GDC VM Runtime range backend for live-fire scenarios: normal Mission Control and CTF range provisioning now fails closed unless the approved GCE VM range-cell backend is selected, with a CMS service-boundary gate and a provisioner defense-in-depth denial. GDC VM Runtime is development/validation only (ADR-030). (#1348)
- AWS Polaris range agents (`a14-kali`) no longer authenticate to Bedrock through the shared host operations role via IMDS. Each range now gets its own short-lived, revocable STS-assumed Bedrock role, delivered to the container through a host-refreshed credential file; the host firewall permanently drops container traffic to the instance metadata service, closing the path a participant could previously use to reach broader SSM/S3 permissions. (#1377)
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
- Cleared the outstanding CodeQL security backlog carried on `dev`. Provisioner and platform logs now fingerprint or omit sensitive identifiers and secret references and sanitize user-controlled values before logging, Terraform apply output is summarized instead of dumped, the CTF register-exchange endpoint returns a fixed message instead of raw exception text, and the Identity Platform logout redirect is restricted to same-origin relative paths. Intentionally vulnerable Polaris scenario target containers are excluded from platform code scanning so their expected findings no longer mask real platform issues.
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
- Polaris CTF scenario can now run on the GCP Compute Engine range-cell backend (`GCP_RANGE_BACKEND=gce`): the range-cell plan translates the scenario image key to a validated GCE profile (ignoring AWS `instance_type`), the per-range Polaris bootstrap runs over the routed guest-SSH transport with the Kali agent configured for Vertex AI (replacing AWS Bedrock), and the range firewall opens the Docker-host management SSH port. New `GCP_RANGE_*` runtime knobs (Vertex project/region/models, Private Google Access, host management SSH port, Polaris tests bucket/key) flow through the generated runtime env, inventory, and engine task env allowlist. (#1342)
- Added a live-fire escape validation suite that proves the outer boundary of a GCP VM range cell fails closed before the range is trusted for live fire (ADR-030-R5). The `run_range_escape_validation` management command runs bounded, read-only probes from participant context inside one or more running ranges and attempts the escape paths a participant would try (cross-range private IP and DNS, platform pod/service/node networks, GKE/GDC API, portal-private endpoints, metadata credentials, internet egress against the ADR-017 policy, and peer-sourced management ingress). It emits a closed, versioned JSON report whose per-check boundary codes name the exact boundary that leaked, supports one-range and two-or-more-range runs through the same contract, and exits non-zero for a CI or operator gate. The core suite is scenario neutral, with a probe-launch adapter seam (native VM SSH and a Polaris container-exec reference adapter) and scenario-supplied checks kept additive. A static plan-leak checker in the provisioner catches an intentionally misconfigured cross-range allow rule with no cloud call. (#1347)
- Enabled participant and operator portal access (browser SSH terminal and Guacamole SSH/RDP) to scenario endpoints inside GCP VM range cells, at parity with the existing AWS range access, by authorizing the portal and guacd workloads to reach range guests over the private range network. (#1349)
- Added the platform-wide SPA shell (#1369): a single role-aware React shell with global navigation, a home/dashboard surface, and auth-adjacent states, built on the locked Apple-dark design system. Navigation renders from one shared, role-aware contract (the seam later Phase 2 modules register into), and the Risk Register is rehomed under the unified client router. It ships behind the reversible `PLATFORM_SPA_ENABLED` rollout flag with the legacy Django pages preserved for rollback; the shell meets WCAG 2.1 AA (skip link, landmarks, route-change focus, keyboard navigation). (#1369)
- Ported the Mission Control workspace onto the platform SPA (#1370, SPA Cutover Phase 2), behind the new `MISSION_CONTROL_SPA_ENABLED` rollout flag (in addition to `PLATFORM_SPA_ENABLED`); the legacy Django templates stay the default and remain available for rollback. The React module (`frontend/src/features/mission-control/`) covers the range dashboard, range history, launch, and detail; live range status (a Channels range-status socket used as an advisory refresh trigger over authoritative `/api/v1/` reads, with bounded polling as the fallback per ADR-025-R4); an embedded xterm.js SSH terminal over the existing terminal Channels route; server-brokered Guacamole RDP/SSH sessions opened in a new tab (never embedded, no signed URL persisted); and NGFW, credentials, and agent-upload surfaces. All data access is on the canonical `/api/v1/mission-control/` DRF surface, which was given typed response serializers and `@extend_schema` so `gen:api` now generates real TypeScript types; a new `GET /api/v1/mission-control/ranges/` range-history endpoint was added, and the DRF current-range read now applies the CTF-participant Kali-only instance filter that the legacy template path already applied. Loading, empty, validation, permission, error, and destructive-confirm states are handled throughout, targeting WCAG 2.1 AA. Where Mission Control still lacks `/api/v1/` read coverage (agent deletion, listing existing credentials, and deployment-profile / SCM-credential pickers), the SPA notes the gap in place rather than calling legacy endpoints or adding ad hoc ones; that consolidation is tracked separately (#1328 / #1329). (#1370)
- Added the Scenario Editor single-page application (SPA) workspace (SPA cutover Phase 2, following the Risk Register and Mission Control modules) behind the `SCENARIO_EDITOR_SPA_ENABLED` rollout flag (default off, AND-gated with `PLATFORM_SPA_ENABLED`). It is a React + TypeScript module in the platform SPA that consumes new canonical `/api/v1/cms/scenario-editor/` DRF endpoints (structured create/update, delete, clone, availability metadata, YAML export, plus the existing catalog and YAML validate/create routes) with session authentication and CSRF. Authors can browse the scenario catalog and create, edit (structured or YAML), clone, enable/disable, restrict, export, and delete custom scenarios; built-in, ACES, and CTF scenarios are read-only. When the flag is on, the GET pages under `/scenario-editor/` are served by the SPA host view while the legacy Django POST action URLs remain for compatibility and rollback; when off, the existing Django templates are unchanged. (#1371)
- Add a typed `/api/v1/ctf/` DRF surface (participant + organizer) powering the CTF workspace SPA. (#1372)
- Added the SPA Administer workspace (Phase 2 of the SPA cutover) for staff operators, behind the default-off `ADMINISTER_SPA_ENABLED` rollout flag (served only when `PLATFORM_SPA_ENABLED` is also on). It provides native user administration on the canonical `/api/v1/administer/` DRF surface as explicit named operations rather than a broad model CRUD: a bounded, paginated, filterable user list and detail (roles, account origin, and provenance shown read-only, with no identity-binding fields exposed), plus activate/deactivate, soft-delete, and a grant-only local CTF-Organizer operation. Every operation requires a staff session (platform API tokens are rejected) and the matching Django model permission, and writes a strict, request-attributed audit row inside its atomic service boundary. Platform Settings ships as a read-only, deployment-managed informational surface and Cost as a truthful "unavailable" state pending a separately owned canonical cost source. Django admin at `/admin/` is unchanged and remains available in every rollout state; flipping the flag off restores prior behavior. (#1373)
- Add `scripts/sync-deploy-secrets.sh` to push each environment's local deploy overlays (`local.auto.tfvars` for portal/range/core, plus the `shifter.yaml` for `SHIFTER_CONFIG_*`) into their matching `TF_VARS_*` / `SHIFTER_CONFIG_*` GitHub Actions secrets. Operators now sync from the same files they use for local `terraform` instead of hand-editing whole-file secrets in the GitHub UI; the script supports `--dry-run`, fails loud on a missing overlay, and never prints secret contents. Documented in `docs/dev/deploy-secrets.md`. (#1379)
- Pre-promoted domain-controller images can now be baked for any domain from one parameterized Packer template (`dc-prebaked.pkr.hcl`) driven by per-purpose profile var-files in `shifter/packer/gcp/dc-profiles/`. To add a DC for a new domain, copy a profile, supply its AD-content script, and run the Packer GCE build with `dc_profile=<name>`; it publishes image family `shifter-<purpose>-dc`. The former `polaris-dc` template becomes the default `polaris` profile (BOREAS.LOCAL). The parameterized runtime-promotion path is retained but unused (pre-bake keeps time-to-serve low). (#1391)
- Added the ACES-native provisioning core (ADR-031/ADR-032, behind the `SHIFTER_ACES_NATIVE_PROVISIONING` feature flag, default off): a Shifter ACES RuntimeTarget backend (`shared.aces.runtime_target`) that validates a compiled ACES `ProvisioningPlan` against the backend capability envelope (failing closed on any out-of-envelope term) and dispatches the serialized plan itself through an injected port, superseding the earlier `scenario_ref` passthrough. Per ADR-032, Shifter rides the ACES contract end to end: it introduces no parallel SDL or re-modeled spec; the engine persists the serialized ACES plan in `range_config` and the provisioner reads it via accessors that mirror the reference ACES backend (image from the authored `source`, sizing from `resources`, `os_family` for OS dialect only), resolving concrete artifacts at realization from the authored identity. The backend is verified by the ACES-owned conformance suite (fixture + a live target probe that rejects a vacuous pass), and a platform-side drift test keeps the provisioner reader aligned with the reference backend. The producer uses the released `aces-scenario-packs` 1.2.0 / `aces-sdl` 0.20.0 pair, while the provisioner retains a bounded rolling-read window for persisted 0.19.1 plans; an import-linter contract confines ACES SDL tooling to `shared.aces`. With the flag off there is no behaviour change; the existing cyberscript range path stays authoritative. (#1444)
- Add `scripts/ctfd-workshop/standup-gcp-ctfd.sh`, a small re-runnable gcloud helper that stands up the standalone CTFd workshop on GCE (static IP + 80/443 firewall + debian-12 VM running CTFd via docker compose behind host nginx), mirroring the AWS `ctfd-workshop` pattern for the GCP Polaris event surface. (#1459)
- Added ACES-native GCE range-cell realization (ADR-031/ADR-032, behind the `SHIFTER_ACES_NATIVE_PROVISIONING` feature flag, default off). The provisioner realizes a serialized ACES ProvisioningPlan into a real Compute Engine range cell via a new `aces-range provision|destroy --request-id` command: it maps the authored topology into the neutral GCE range-cell plan (image resolved from the authored `source` against the tenant registry, sizing from `resources`, `os_family` as OS dialect only, authored network CIDRs to subnets, deterministic IP assignment, `count` fan-out) and provisions it by reusing the provenance-neutral GCE apply primitives with an ACES-owned instance path that mints one provisioner-managed SSH key per node for reachability and carries no cyberscript scenario, role, RDP, or Vertex coupling. Authored node ACLs are realized as fail-closed GCE firewall rules placed below the management plane so an authored deny never severs the provisioner's own reachability. Authored ACES composition is realized genuinely as guest bootstrap (ADR-032-R6): content placements (inline files written for real; directories created; non-inline content supplied by the baked image), account placements (real guest users with groups/shell/home/mail/spn, locked when disabled), and service feature bindings (a real install+enable step whose package is provided by the baked image or guest repo) are emitted as an idempotent Linux-bash / Windows-PowerShell script appended to the instance startup script. All plan-controlled values are shell-quoted, file bytes go through base64, and identifiers are validated fail-closed, so authored content cannot inject shell; a placement targeting an absent node aborts. A node that declares no `source` still boots: the backend resolves a base OS image from the tenant registry keyed on `os_family` (ADR-032-R5), a policy distinct from the prohibited inference of an image from `os_family` for an authored source. Image version pins are honored exactly -- a pinned version never silently falls back to the any-version registry mapping, matching aces-sdl (opaque version, no substitution) and the reference backend (hard-fail on an unavailable image). The backend capability manifest now declares the backing capability (`supports_acls`, `supports_accounts`, `supported_content_types`, `supported_account_features`) and the platform capability envelope accepts and fail-closed-validates content/feature/account placements. With the flag off there is no behaviour change; the cyberscript range path stays authoritative. (#1477)
- Wired the ACES-native provisioning path's operational evidence into the existing ACES sidecar/Mission-Control read seams (ADR-031, behind `SHIFTER_ACES_NATIVE_PROVISIONING`, default off). The provisioner now emits `operation_status` observations (running/succeeded/failed) and a `runtime_snapshot` of the provisioned topology from the `aces-range` provision/teardown path, via new `range.aces.operation` / `range.aces.snapshot` outbox events; the engine consumer persists them as `operation_status` and `runtime_snapshot` AcesOperationRecords through the validated, redacted persisters (a new `persist_runtime_snapshot_record` fills the one missing write helper). The snapshot carries only bounded `{address, resource_type, status}` entries built from the authored plan, never the raw GCE outputs (which hold secrets/CIDRs), and failures map to a bounded, sanitized status reason. Records are readable through the existing redacted Mission Control ACES endpoints, keyed by `request_id`; range lifecycle status stays driven by the neutral range status events, so the ACES records are additive evidence. With the flag off there is no behaviour change. (#1478)
- Made ACES packages launchable through a native provisioning path, gated by `SHIFTER_ACES_NATIVE_PROVISIONING` (default off, ADR-031-R5). A new package loader (`shared.aces.package_loader`) turns a registered pack-root `package_ref` into a dispatched launch: under `ACES_PACKAGE_ROOT`, CMS re-verifies the registered canonical content digest, the loader selects the pack's single direct SDL entry, compiles it with `aces-sdl`, plans it against the Shifter provisioning-only backend, and applies the compiled plan through an injected dispatch port. A new launch service (`cms.services.create_aces_native_range`, routed by `create_range_dispatch`) launches a registered ACES package in parallel to the cyberscript `create_range`: it reuses the same ownership, active-range, launchability, and audit checks and persists the same CMS `Request` + `RangeInstance` bookkeeping (with no cyberscript `RangeSpec`), so Mission Control visibility, active-range admission, and range-status propagation all work uniformly. ACES catalog entries become launchable only with the flag on; with the flag off, no ACES entry is launchable and `create_range_dispatch` is byte-identical to `create_range`. Fixed two ACES-conformance gaps that previously blocked launching any real ACES package: the Shifter backend manifest now declares `switch` node support (the aces-sdl planner rejects every network resource otherwise, even though Shifter realizes networks), and the provisional provisioning snapshot now echoes the authored realization concerns (`os_family`, `node_type`, content `spec.type`) so the aces-sdl runtime non-approximation gate confirms the backend committed to realize exactly what the author declared. (#1479)
- Added an explicit `TEST_DB_BACKEND` test-database selector (separating `TESTING=1` posture from the database backend) and a required PostgreSQL CI lane that runs the broad platform suite against real PostgreSQL, so production persistence semantics (transactions, constraints, row/table locking) are exercised instead of only SQLite. (#1524)
- Added GCP-native self-hosted GitHub Actions runners so a GCP dev tenant runs its own CI/deploy instead of borrowing the AWS runner fleet (dev-tenant containment). `deploy.py runners --cloud gcp` provisions a GCE runner into the target GCP project via a dedicated Terraform root (`platform/terraform/gcp/global/github-runner/`, separate state prefix so a platform destroy never removes it): a private-only Shielded VM in a custom VPC with Cloud NAT egress and SSH reachable only over IAP. Registration mints a single-use token per runner and delivers it to the host over the `gcloud compute ssh` stdin stream into a root-only temp file, kept out of the operator's argv/logs, Terraform state, instance metadata, and Secret Manager. (The runner's `config.sh` requires `--token` for non-interactive registration and offers no stdin/file/env channel, so the single-use token is present only momentarily in the isolated runner VM's process args during registration, then removed.) The runner registers with `--no-default-labels` + the `gcp-dev` label, and the command fails closed unless the runner reports online with that label. GCP-dev deploy and destroy workflows now target the `gcp-dev` runner; a new `check-tf-gcp-runner-network` guard (ADR-008-R8) and the extended ADR-003-R5 exposure checker keep the isolation and pull-request gating intact. (#1546)
- Added a first-class AWS Packer template for the Polaris domain controller (`shifter/packer/polaris-dc.pkr.hcl`, wired into `packer.yml` as the `polaris-dc` AMI type). It is the amazon-ebs twin of the GCP `dc-prebaked` template: it bakes a pre-promoted `boreas.local` DC (OUs/users/SPNs/DCSync ACL/shares via `a2_setup.ps1`) with OpenSSH Server preinstalled (required by the range provisioner's DC setup). This replaces the previous ad-hoc DC bake, which produced AMIs missing OpenSSH. (#1547)
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
- Added an `aws-tenant-standup` skill, available to both Claude Code (`.claude/skills/`) and Codex (`.agents/skills/`), that captures the end-to-end AWS Shifter tenant teardown and rebuild: teardown or AMI-preserving teardown, bootstrap and secrets, image bakes, deploy via the real `deploy.yml` dispatch, health verification, base-range smoke, and a POLARIS range walkthrough. It takes profile, region, and teardown mode as promptable, optional parameters, points at the authoritative deploy docs, and encodes the fresh-environment pitfalls found during the proof rebuild. (#1700)
- Added a GCP Packer build for the `polaris-dc` (BOREAS.LOCAL) domain-controller image, salvaged from the GDC effort when Polaris moved to the GCE range-cell backend, so a GDC AD image can still be baked if needed in future.
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
- Stop tracking Polaris AWS operator run outputs (`provisioning_state.json`, status/health reports) and extend ADR-004-R8 guard coverage so they cannot be re-committed. (#772)
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
- Scenario verification now uses a provider- and scenario-neutral shared framework with lazy installed-metadata discovery, explicit version-pinned plugin selection, bounded runner and prerequisite contracts, and redacted versioned reports. Core ships and tests no Polaris adapters or answer material; the existing range smoke remains in-tree while scenario-specific verification is supplied separately by operators. (#1293)
- The portal container image build and CI now build the SPA frontend: a Node/Vite stage in `shifter/shifter_platform/Dockerfile` compiles the bundle into the static tree before `collectstatic`, and a new `SPA (shifter_platform frontend)` job in the Quality workflow lints, typechecks, unit-tests (Vitest), and builds the frontend on changes under `shifter/shifter_platform/`. (#1302)
- Added the `aces-parity-inventory-path-integrity` ADR guard check (ADR-024-R4): `adr_guard --all --level ci` now fails when a `legacy_source` or `validation_evidence` clause in `docs/architecture/aces-migration-parity-inventory.yaml` is a repository path or glob that no longer resolves, while classifying shell-command and prose clauses so they are never false-flagged. The check is a global repository invariant (it runs even when the inventory is not in the changed-file set) and is wired into the `ci` level, a dedicated always-run `adr-guard-parity-inventory` pre-commit hook, and the always-present `deploy.yml` pre-commit job so a referenced-file deletion cannot silently leave the ACES cutover parity ledger pointing at nonexistent paths. (#1313)
- Define and structurally enforce the provider-neutral range-substrate contract for provision, destroy, pause, and resume across AWS Terraform and GCP GDC adapters, with Azure explicitly deferred pending conformance. (#1322)
- Consolidated the Mission Control and CTF app-local JSON HTTP APIs onto the versioned `/api/v1/` DRF surface and retired the legacy duplicate mounts. The Mission Control UI (dashboard, agents, terminal, NGFW, credentials) and the CTF UI now call the canonical `/api/v1/mission-control/` and `/api/v1/ctf/` routes exclusively, and the internal callers that produced Guacamole and redirect URLs were repointed to them. The legacy `/mission-control/api/*` mount was removed entirely, and `/ctf/api/*` was reduced to the single scoreboard endpoint (intentionally retained because its v1 twin uses different public-access semantics). Two previously legacy-only CTF operations, event spare-range provisioning and participant range recovery, were added to `/api/v1/ctf/` so the versioned surface is complete. As part of the removal the per-mount error-format compatibility shim was dropped, so Mission Control endpoints now always return the canonical `{"error": {"code", "message", "details"}}` envelope instead of the legacy flat `{"error": "..."}` form. (#1328)
- Hardened the GCE guest-image pipeline for the range-cell backend. Added a candidate-boot validation gate (`packer-gcp-validate.yml`) that boots the exact built image in a disposable, isolated VM (no external IP, IAP, Shielded VM, and no guest service account) and gathers evidence from the trusted runner over an IAP tunnel: for Linux/polaris-vm it SSH-executes a check script (guest agent, Docker, baked compose config/images, every declared compose service running) and gates on the exit code; for a pre-promoted DC it probes AD over LDAP (rootDSE proves AD DS serves the expected forest, no first-boot promotion). Passing again after a reset proves a clean boot; on success it labels the image `validated=passed`. Promotion (`packer-gcp-promote.yml`) is now evidence-driven: it copies the exact validated candidate into the prod family (derived from the image's own family, so `polaris-vm` and purpose-scoped `<purpose>-dc` families work), verifies the new prod image, then deprecates the previous head; it no longer re-resolves "newest in the dev family" at promotion time. `load_gce_range_cell_config` now validates the image-reference shape, disk type, and a per-role policy minimum boot-disk size before any Compute Engine call. See `docs/architecture/gcp-guest-images.md`. (#1343)
- **GCP VM range cells now enforce a closed scenario-to-platform contract.** Canonically validated scenario content crosses as a digest-bound artifact, while the platform owns admission, network bindings, lifecycle, membership, declared participant access, and cleanup. Destroy can replay without scenario-owned CIDRs, and host-management credentials stay outside participant access results. (#1344)
- GCP ranges now provision on the GCE range-cell backend by default (`GCP_RANGE_BACKEND` defaults to `gce`). The GDC VM Runtime path is retained and can be re-selected per environment with `GCP_RANGE_BACKEND=gdc`. Added the range-scoped `GCP_RANGE_CELL_PROJECT_ID` so range cells target the real range project independently of the control-plane project. (#1387)
- Gate the platform deploy on worker/scheduler container health. The post-deploy checks only covered the portal web tier (image digest + ALB `/health/`), so crash-looping workers (outbox drainer, reconciler, ctf-scheduler, etc.) shipped as a green deploy. A new `verify-asg-workers` step SSM-checks each in-service instance's worker containers and fails the deploy when any never reaches `healthy`, retrying to tolerate the health-start-period and a single transient restart. (#1398)
- Made the post-deploy range smoke agent-independent. It now provisions minimal ranges built entirely from base range AMIs: `smoke_linux` (Kali attacker + Ubuntu victim, SSH probe) and `smoke_windows` (Kali attacker + plain Windows victim, RDP probe), with no XDR agent, and no longer requires the `SMOKE_LINUX_AGENT_ID` / `SMOKE_WINDOWS_AGENT_ID` secrets. The smoke validates the platform (provision, connect, teardown); XDR/agent install is scenario content exercised by real scenarios, not the smoke. (#1422)
- The self-hosted runner Terraform (`platform/terraform/global/github-runner`) gains an explicit ADR-004-R20 opt-in, `allow_default_vpc`, for account-default-VPC placement. The guard still fails closed by default; when opted in (aws-dev/aws-proof set it) the stack auto-resolves the default VPC and one of its subnets, so no live VPC/subnet IDs are committed (ADR-004-R14). This reconciles the #1222 non-default-VPC mandate with the reality that deploys have always run runners in the default VPC. The pinning checker, its tests, ADR-004-R20, and the runner runbook/README are updated to match, and issue #1437 tracks reassessing the durable placement design. (#1425)
- Bootstrap can now provision **and register** self-hosted GitHub Actions runners end-to-end. A new `deploy.py runners` subcommand (and the `full` flow) applies the runner Terraform root (optionally provisioning a dedicated, ADR-004-R20-compliant runner VPC via the new `create_runner_network` variable), then registers each runner over SSM using a single-use GitHub token minted per runner and verifies it online via the GitHub API. Registration tokens never touch Terraform state, user data, SSM Parameter Store, Secrets Manager, or operator logs. Manual `config.sh` registration is no longer required. (#1433)
- Standardized the TechVault and Polaris scenario AMI bakes on Packer. The hand-rolled `run-instances` / SSM-RunCommand-shell / `create-image` workflows (`techvault-scenario-bake.yml`, `polaris-scenario-bake.yml`) are deleted; both scenarios now bake via new Packer sources (`shifter/packer/techvault.pkr.hcl`, `polaris-vm.pkr.hcl`) dispatched through the shared `packer.yml` (`ami_type=techvault` / `polaris-vm`). Packer owns builder launch, provisioning, image creation, and teardown over the no-inbound AWS Session Manager communicator with an encrypted root volume; the workflow keeps the encrypted-AMI check and fresh-boot golden-verify as gates before publishing `/shifter/ami/<key>`. Bake behavior (running-stack image semantics, the aptl/polaris build steps, and the per-range runtime bootstrap contract) is unchanged. The deploy role gains a narrow `ssm:StartSession` grant for Packer's Session Manager tunnel (applied via an IAM `terraform apply`). This also resolves #1491: the shared `packer.yml` bake job carries a `dev`/`proof` `environment` selector with per-environment role resolution, so the polaris bake is no longer hardcoded to the dev account. (#1469)
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
- Corrected AMI and smoketest documentation drift. `ami-management.md` now points at the real runtime resolver `shifter/engine/provisioner/provisioner_ami.py:get_ami_id()`, uses the correct `shifter/packer/scripts/ubuntu/` build-scripts path, and enumerates the full set of baked AMI types (adding `brokenbk`, `polaris-dc`, `techvault`, and `polaris-vm`). The AWS AMI seeding runbook no longer references a non-existent `ctf-*` AMI type, and the native CTF smoketest uses the authoritative proof domain `dev.shifter.keplerops.com`.
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
- Closed fail-open and credential-hygiene gaps in the GCE guest-image bake. The polaris-vm `host-setup.sh` now fails the build when the compose stack is absent, its `POLARIS_STACK_SHA256` checksum mismatches, the compose config is invalid, a build/pull fails, or a required image is missing, instead of warning and producing a non-promotable image. The pre-promoted `dc-prebaked` DC no longer carries a committed default DSRM password (it is generated per build and injected as a sensitive var), and a pre-capture cleanup provisioner strips build transcripts and the staged AD-content seed so no secret-bearing artifact ships in the un-sysprepped image; the live domain Administrator credential continues to rotate per range at runtime. (#1343)
- GCP Polaris ranges now provision end-to-end on the GCE range-cell backend. Fixed the provisioner→range-host management-SSH firewall port, Private Google Access egress so range guests reach Vertex AI / Cloud Storage / Secret Manager, the range-guest OAuth scope, root execution of guest setup scripts, and a range-id plumbing bug that pointed the agent credential lookup at the wrong secret. (#1387)
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
- The TechVault scenario bake (`techvault-scenario-bake.yml`) now encrypts the bake host root volume at launch (`Encrypted:true`, matching the Polaris precedent) instead of relying only on the account's EBS-encryption-by-default posture, and adds a fail-closed pre-publish gate that verifies the produced AMI's EBS snapshots are encrypted before recording it in `/shifter/ami/techvault`. Previously an unencrypted golden AMI could be published, which the range provisioner's `ec2:Encrypted=true` IAM condition then correctly denied at launch, so TechVault ranges could not start. (#1455)
- The portal can now send SES email (CTF magic-link invites, alarm notifications) from the locked-down private tier. `django_ses` uses the SES API, but the private tier has no internet egress to the public SES endpoint, so every outbound email silently hung until timeout. A VPC interface endpoint for the SES API (`com.amazonaws.<region>.email`) is added to the portal endpoint set, keeping SES traffic on the VPC-local path like the other 18 service endpoints; no SMTP switch or credentials are required. (#1460)
- CTF magic-link registration now lands participants on their range page (`ctf:participant_range`) instead of the Mission Control dashboard, where a CTF participant would see no active range (MC ranges are separate from CTF ranges). The portal ASG also no longer fails `terraform apply` on large scale-ups: `wait_for_capacity_timeout` is set to `0` so the apply does not block on the ASG reaching capacity (new instances sit in Pending:Wait through their launch lifecycle hook, and warm-pool churn compounds it, exceeding Terraform's default 10-minute wait); readiness is gated by the instance refresh and the deploy's verify steps instead. (#1462)
- CTF participant range page now shows the environment for single-seat purple-team labs (for example, TechVault). `get_range_target_instances` previously excluded every `attacker`-tagged instance, which returns nothing for a scenario whose only node is the attacker-tagged seat host the participant works from; the page then rendered "available" with no reachable host. It now falls back to returning the seat hosts when a ready range has no non-attacker targets, preserving multi-node behavior (POLARIS still hides its attacker and shows its targets). RDP access for the range page now logs in as the guest's recorded seat user (`ssh_username`) rather than the `os_type` default, so a TechVault host (os_type `kali`, seat user `ubuntu` where VS Code Desktop + Claude Code run) is reached as `ubuntu`. A domain controller keeps its domain-admin login. (#1465)
- The engine deploy `validate` job now runs on the self-hosted runner class instead of `ubuntu-latest`. A GitHub-hosted runner-acquisition stall could previously cancel the job with zero steps started, which skipped the whole AWS Platform deploy stage through the fail-closed dependency chain. `validate` is fail-closed on `pull_request` (ADR-003-R5), keeps `contents: read` permissions only, and has a `timeout-minutes` backstop. (#1474)
- Dropped the unused `chat.<domain>` subject-alternative name from the portal ALB's ACM certificate. No listener rule, DNS record, or app configuration ever served `chat.<domain>`, but the extra SAN forced a second ACM DNS-validation record that silently blocked certificate issuance until the record was added by hand (hit at the proof DNS gate). The certificate now validates against the portal domain alone. (#1475)
- The Polaris scenario bake workflow (`polaris-scenario-bake.yml`) can now bake `polaris-vm` in any supported AWS environment. It gained an `environment` input (dev/proof) and resolves the deploy role the same way as `packer.yml` and `techvault-scenario-bake.yml`, instead of hardcoding the dev account role. The golden-range Terraform `name_prefix` now defaults to `shifter-polaris` so the instance role it creates falls within the CI role's `iam:PassRole` scope (`shifter-*`); the previous bare `polaris` prefix was outside that scope and RunInstances failed with a PassRole `AccessDeniedException`. The workflow also no longer uses `actions/setup-python` (unavailable on the self-hosted runners' tool cache); it builds a venv from the runner's system `python3` instead, matching the other self-hosted workflows. (#1491)
- Granted the GitHub Actions CI role read-only access to AWS-owned public SSM parameters under `arn:aws:ssm:<region>::parameter/aws/service/*`. The scenario bakes (techvault and polaris golden ranges) resolve current base AMIs through these public parameters, and the management policy previously scoped SSM read to `parameter/shifter/*` only, so the bakes failed with an `AccessDeniedException` on the Canonical Ubuntu and Amazon Linux AMI-ID lookups. (#1493)
- Fixed the TechVault scenario bake failing at `aptl lab start` "Preparing Suricata runtime volumes" with a `BackendSeedError`. The bake installs Docker as root but runs the stack (and aptl's first docker operation, the Suricata named-volume seed) as the `ubuntu` user, which was not in the `docker` group, so the seed hit a `docker.sock` permission-denied. The bake toolchain now adds `ubuntu` to the `docker` group. (#1495)
- Fixed the TechVault bake's container-count gate, which required 31 running `aptl-*` containers. The `techvault-operational` stack on aptl-labs 4.1.2 settles at 30 long-running containers plus a one-shot `aptl-cortex-index-init` that exits 0, so the bake-wait and golden-verify never reached 31 and timed out. Both checks now require 30. (#1497)
- Granted the GitHub Actions CI role read-only access to the scenario bake S3 buckets (`shifter-*-bake-*`). The polaris scenario bake verifies its operator-uploaded build tarball in the bake bucket, and the CI role's `data` policy previously scoped S3 to infra/state/user-storage/portal buckets only, so the check failed with an `AccessDenied`. (#1500)
- Fixed the TechVault bake timing out at `create-image`. The bake used `aws ec2 wait image-available` (10-minute default), but the large TechVault AMI (100 GB root plus the full baked stack) takes 30-60 minutes to snapshot, so the wait failed with `Max attempts exceeded` and skipped recording the AMI in SSM even though it was finalizing normally. The bake now polls for availability with a 60-minute deadline and fails fast on a terminal image state. (#1502)
- Completed the Polaris AWS scenario bake for self-hosted Amazon Linux 2023 runners and the private-content split. The bake now consumes an operator-uploaded S3 build tarball (the `scenario-dev/polaris/build/` flags/solutions live in the private `penumbra-scenarios` repo, not this public repo) and fails loud if it is missing; it no longer runs `actions/setup-python`/`reportlab`/`poppler` (unavailable on the runners) and uses a system-`python3` venv only for the range health check. Also fixed the golden-range Terraform `coalesce(var.aws_profile, "")`, which errored with `Call to function "coalesce" failed` when `aws_profile` is null (the CI default). (#1505)
- Codify the GCE range-cell backend's fresh-deploy requirements on GCP so a clean deploy provisions ranges without manual setup: Terraform now creates the range host and Vertex service accounts, grants their roles, and grants the provisioner workload SA Compute admin plus service-account-user and key-admin on the range SAs; the prebaked Windows DC domain Administrator password is provisioned as a Secret Manager secret rendered as `DC_DOMAIN_PASSWORD_SECRET_ID` (previously unwired, leaving the DC's set_admin_password step with an empty password); and in-range SSH guests (GDC and GCE range VMs) get a longer first-boot SSH-ready budget so the heavy Polaris host image is reachable before the provisioner times out. (#1509)
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
- Fixed the GCP `shifter-kali` range image never accepting SSH, which made every scenario that uses a Kali attacker (basic, techvault, polaris) fail provisioning because the range provisioner could not reach the guest. The image build strips `/etc/ssh/ssh_host_*` (so instances never ship shared host keys) and enables `ssh.service`, but Kali, unlike the Ubuntu image, does not regenerate the host keys on first boot, so `sshd` could not start and never bound port 22 (the guest booted to a login prompt but only exposed the systemd AF_UNIX local ssh socket). The Kali GCE conversion now installs a first-boot systemd oneshot that runs `ssh-keygen -A` before `sshd` whenever host keys are missing, so a freshly provisioned Kali guest generates per-instance host keys and `sshd` comes up on port 22. Requires a `shifter-kali` image re-bake to take effect. (#1745)
- Fixed the AWS portal Terraform apply, which failed with `LimitExceeded: Maximum policy size of 10240 bytes exceeded` on the engine-provisioner ECS task role and blocked every `Shifter Platform` deploy. Recent Gateway Load Balancer and OpenVPN-gateway work pushed the role's aggregate inline-policy size past AWS's 10,240-byte per-role ceiling. The two largest inline policies (EC2 provisioning and GWLB provisioning) now attach as customer-managed policies, which do not count toward the inline aggregate; the granted permissions are unchanged. Applies to all AWS environments. (#1749)
- **AWS range provisioning now grants the narrowly scoped IAM and load balancer permissions required to create per-range OpenVPN gateways.** Policy guardrails also reject broader permission variants, and post-deploy smoke tests stop immediately when a range reaches a terminal failure state. (#1755)
- GCE range cells now resolve each legacy scenario `ami_key` through an exact, deployment-approved image profile, allowing generic Kali, Polaris, and TechVault scenarios to coexist without runtime ConfigMap swaps. (#1761)
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
- Allow the range provisioner to create the per-range POLARIS agent IAM role under the CI permissions boundary. The polaris agent feature (#1377) creates a per-range agent role at provision time, but the provisioner's anti-escalation boundary (#253) denied all `iam:CreateRole`, so a polaris range could never reach `terraform apply`. The boundary now carves the `shifter-<env>-*-polaris-agent` role namespace out of the IAM deny. This is safe because the provisioner identity policy already permits `iam:CreateRole` there only with this same boundary attached (`iam:PermissionsBoundary` condition) and grants no boundary-strip action, so every created agent role stays capped by the boundary (the AWS permissions-boundary delegation pattern). A new `DenyPolarisAgentBoundaryTamper` statement re-denies boundary removal on that namespace as defense-in-depth.
- Force the regional STS endpoint for the POLARIS a14-kali agent container. The bootstrap verify runs `aws sts get-caller-identity` inside a14-kali, but the container's aws-config set only `region`, so the CLI used the global `sts.amazonaws.com` endpoint, which a14-kali cannot resolve (only the regional `sts.<region>` endpoint is pinned in the container's extra_hosts). Add `sts_regional_endpoints = regional` to the container aws-config so STS calls use the pinned regional endpoint, and surface the get-caller-identity error in the verify output instead of discarding it with `2>/dev/null`.
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

- Scope the engine-provisioner ECS task role's ELBv2 (Gateway Load Balancer)
  permissions. The `aws_iam_role_policy.gwlb` policy in
  `platform/terraform/modules/engine-provisioner/iam.tf` no longer grants
  mutable `elasticloadbalancing:*` actions on `Resource = "*"`; create,
  delete, modify, register/deregister-targets, and tag-mutation actions are
  restricted to Gateway Load Balancer resource ARNs
  (`loadbalancer/gwy/*`, `listener/gwy/*/*/*`, `targetgroup/*`) and gated on
  Shifter ownership request/resource tags. `Describe*` is enumerated and
  retains `Resource = "*"` per AWS service authorization requirements. A new
  `scripts/check_tf_iam_elb_scope` static checker (wired through pre-commit
  and the Quality workflow) prevents regression. (#46)- **Scoped the engine provisioner EC2 lifecycle IAM permissions to Shifter-owned
  instances.** Mutable instance actions now require the existing runtime ownership
  tags instead of allowing the task role to manage every EC2 instance in the
  account. (#55)- Add a portal-VPC east-west inspection boundary on AWS. An AWS Network
  Firewall sits between the public ALB tier and the private services
  tier, with route-backed steering through a dedicated firewall subnet
  and a baseline stateful rule group that ALERTs on protocols that have
  no legitimate east-west use (SSH/RDP/ICMP). FLOW + ALERT logs go to a
  CMK-encrypted CloudWatch log group and feed the existing
  `log-aggregation` pipeline; `enable_portal_inspection = true`
  fails closed when `enable_log_aggregation = false`. Portal RDS and
  Redis ingress tighten from a broad VPC-CIDR allowlist to SG-to-SG
  references from the portal EC2 / Django security group. Gated by the
  new `enable_portal_inspection` environment variable. (#122)- Portal and Guacamole RDS instances now explicitly pin the AWS RDS CA certificate and keep IAM database authentication enabled, with a repo-native Terraform guardrail preventing either setting from regressing. (#140)- **Portal Secrets Manager secrets are now encrypted with customer-managed KMS keys** (CKV_AWS_149). A per-environment `aws_kms_key.secrets_manager` (alias `alias/shifter-<env>-secrets-manager`) with annual rotation is created in the portal env root and plumbed into the `portal/rds`, `portal/cognito`, `guacamole`, and `engine-provisioner` modules, plus the env-root `app` (Django) secret. The CMK ARN is also exposed to the engine-provisioner ECS task as `SECRETS_KMS_KEY_ARN`, so the runtime range and NGFW Terraform modules (`shifter/engine/provisioner/terraform/modules/{range,ngfw}`) encrypt their per-instance SSH-key secrets with the same CMK. The key policy is bound to the `shifter-<env>-*` / `shifter/<env>/*` secret namespace via `kms:EncryptionContext:SecretARN`, so a principal with `kms:Decrypt` on this key cannot use it to decrypt unrelated Secrets Manager secrets in the account. Six `#checkov:skip=CKV_AWS_149` comments on portal-runtime secrets are removed. (#213)- **Portal ALB now has deletion protection enabled** (CKV_AWS_150). `aws_lb.this` reads from a new `enable_deletion_protection` module input (defaulting to `true`) and the corresponding `#checkov:skip=CKV_AWS_150` waiver is removed. Dev pins to `false` for intentional teardown; prod pins to `true`. Mirrors the existing `db_deletion_protection` convention so future destroys remain an explicit configuration change rather than a source patch. (#214)- **Portal user-uploads S3 bucket is now encrypted with a customer-managed KMS key** (CKV_AWS_145). A per-environment `aws_kms_key.portal_s3` (alias `alias/shifter-<env>-portal-s3`) is created in the portal env root and wired into the `portal/s3` module via a new `kms_key_arn` input. The bucket encryption switches from AES256 to `aws:kms` with `bucket_key_enabled = true` to keep KMS API call volume (and cost) bounded. The key policy is bound to the bucket via `kms:EncryptionContext:aws:s3:arn`, so a principal with `kms:Decrypt` on this key cannot use it to decrypt unrelated S3 objects in the account. Access-logging is handled separately by #310 (unified logging strategy); event notifications remain deferred because no real consumer exists. (#218)- **The AWS default security group is now locked down to deny-all on both VPCs** (CKV2_AWS_12). The `portal/vpc` and `range/vpc` modules each adopt the AWS-created default SG via `aws_default_security_group.this` with no `ingress` or `egress` rules, replacing the permissive AWS defaults (open intra-SG ingress, open egress). All real traffic continues to flow through named security groups; the default SG must never be attached to any workload. The two `#checkov:skip=CKV2_AWS_12` waivers are removed. (#221)- **`Instance.data` now encrypts NGFW secret values at rest, completing the
  field-level encryption story started for `Credential.data` in PR #1168.**
  `cms.services.create_ngfw` persists the *hydrated* `NGFWAppSpec` directly into
  `instance.data`, which carries the deployment-profile `authcode`, the SCM
  `scm_pin_value`, and the OTP-registration `otp_value`. Those three keys are
  now encrypted by `EncryptedInstanceDataField` (Fernet — AES-128-CBC +
  HMAC-SHA256, keyed by `FIELD_ENCRYPTION_KEY`); operational fields (`name`,
  `role`, `os_type`, `dc_config`, `agent`, `instance_type`) stay plaintext so
  admin views, log diagnostics, and JSON queries on operational metadata keep
  working. A new data migration (`0029_encrypt_sensitive_instance_data`)
  re-saves existing `Instance` rows so on-disk values move from plaintext to
  `enc:v1:`-prefixed ciphertext; the encrypt path is idempotent so the migration
  is safe to re-run. The underlying field machinery was generalised into an
  `EncryptedJSONField` base; the credential-data field and the new
  instance-data field bind their own `sensitive_keys` frozensets that mirror
  the secret-flagged fields on `SCMCredentialSpec`, `DeploymentProfileSpec`,
  and `NGFWAppSpec`. A contract test pins those key sets to the spec classes
  so any new credential type or NGFW field with a secret-shaped value forces
  explicit registration. (#693)- **Mission Control range lifecycle endpoints now write to the platform `AuditLog`
  with full HTTP request context.** `mission_control.views.launch_range`,
  `cancel_range`, `destroy_range`, `pause_range`, and `resume_range` each call
  `risk_register.services.audit_log_from_request` on success, capturing the
  acting user, source IP (including `X-Forwarded-For` from the ALB), user agent,
  and HTTP `X-Request-ID`. Entries record `AuditLog.EntityType.RANGE` with the
  matching action (`PROVISION` / `CANCEL` / `DEPROVISION` / `PAUSE` / `RESUME`)
  and stash the legacy `range_id` and/or the request UUID in `new_state` so
  either identifier is queryable. `cms.services.cancel_range` and
  `cancel_range_by_request_id` also gain a service-layer `AuditLog.Action.CANCEL`
  entry, filling the one range-lifecycle action that previously had no audit
  coverage. Failed requests (CMS errors, missing identifiers) are not audited,
  so the trail reflects state changes the platform actually performed. (#694)- **Server-side magic-byte inspection now runs before every S3 upload is
  finalized.** Three upload paths previously trusted only the client-side
  extension / magic-byte checks: CTF challenge attachments
  (`ctf.services.attachment.add_challenge_file`), agent installer uploads
  (`cms.services.complete_upload`), and experiment script uploads
  (`cms.experiments.services.complete_script_upload`). Each path now reads a
  bounded prefix of the uploaded content — inline from the file object for the
  Django-mediated CTF flow, and via a new `ObjectStorage.read_object_header`
  range-GET for the presigned-URL agent and script flows — and rejects the
  upload before tagging the object as completed or creating the database
  record. CTF attachments pick one of three policies per extension (positive
  magic-byte match, UTF-8 text with no binary signature, or OPAQUE for raw-byte
  containers like `.bin` / `.raw` / `.dd`). Agent installers reuse the existing
  `cms.assets.validation.ALLOWED_FORMATS` registry. Scripts must be UTF-8
  without a binary signature. The header byte budget is provider-neutral and
  configurable via `UPLOAD_INSPECTION_MAX_HEADER_BYTES` (default 512). (#696)- **Experiment script execution now passes every variable through a Pydantic-validated context.** `cms.experiments.orchestrator` previously interpolated `instance_name` and `s3_key` directly into shell text and only single-quote-escaped resolved Claude prompts — relying on staff-only access as the primary control. The new `cyberscript.script_context.ScriptExecutionContext` validates each value at the type boundary (EC2 instance ID `i-[0-9a-f]{8,17}`, S3 key whitelist with no `..` / leading `/`, IPv4 dotted-quad, prompt body free of null/control bytes) and exposes deterministic `render_command()` helpers. The orchestrator's `_build_python_command` / `_build_claude_command` are removed; the path identifier for `/tmp/script_*.py` is now the instance ID rather than the display name, which also fixes Python scripts targeting instances whose names contain spaces (`Workstation 1`, `Domain Controller`). Script upload key generation is tightened end-to-end so newly uploaded scripts always satisfy the execution validator, and a data migration (`experiments.0002`) renames any legacy `ScriptAsset.s3_key` rows whose characters fall outside the new whitelist (with a server-side S3 copy) so existing scripts continue to execute after the upgrade. (#700)- **Polaris A9 splice-relay no longer accepts password authentication.** The May
  2026 cohort lost the entire Bunker chain (1300 pts) because `root:splice2025`
  existed only in `scenario-dev/polaris/build/a9/Dockerfile` and was not
  discoverable from any in-range artifact. The range bootstrap now generates a
  per-range Ed25519 keypair, stages the private half on a14-kali at
  `/home/kali/.ssh/splice_relay` (mode `0600`) — the participant-discoverable
  artifact — and installs the public half into A9's
  `/root/.ssh/authorized_keys`. A9's `sshd_config` is `PasswordAuthentication no`,
  `PermitRootLogin prohibit-password`. The `scenario_smoketest` harness gained a
  challenge-31 adapter that proves the credential gate end-to-end (evidence
  present + mode 0600, ssh opens, Modbus device-id round-trip). (#707)- Terraform Checkov IaC scanning is now a blocking gate under ADR-004-R11.
  Pre-commit (`.pre-commit-config.yaml`) and CI (`security-iac` workflow)
  share `platform/terraform/.checkov.yaml`; `--soft-fail` is off. 141 of
  321 baseline first-party Terraform findings were fixed in-place
  (encryption-at-rest CMKs across CloudWatch / SQS / SNS / Firehose / ECR /
  Network Firewall / RDS / DynamoDB / EventBridge / Artifact Registry; EC2
  detailed monitoring + IMDSv2 + EBS optimization; CloudWatch retention
  ≥365 days; RDS force_ssl, query logging, enhanced monitoring, PI CMK;
  GKE auto-repair/auto-upgrade/workload-metadata-config; SG descriptions).
  The remaining principled exceptions live in `docs/adr/exceptions.yaml`
  with owner, reason, expiry, and affected paths; `adr_guard.py` rejects
  expired entries. Kubernetes Checkov stays soft-fail as a separately
  tracked workstream. (#757)- **`settings.ENVIRONMENT` now defaults to `"production"` (fail-closed) when the
  `ENVIRONMENT` env var is unset.** The previous `"development"` default meant
  a deployment that omitted or misset the env var silently activated
  `/dev-login/`. Source-IP/host gating in `config/dev_auth.py` already
  prevented public-ingress reachability, but the permissive default still
  turned configuration drift into a dev-auth surface. Deployed dev
  environments must now opt in explicitly by setting `ENVIRONMENT=development`. (#761)- Replace shared static guest passwords (`kali:kali`, `ubuntu:ubuntu`, `CortexSavesTheDay!`, the shared `GDC_*_PASSWORD` env vars) with per-instance random passwords generated at provisioning time and pushed onto each guest by the engine provisioner via `SetLocalPasswordPlan` (SSM Run Command on AWS / SSH on GDC VM Runtime). Values are stored in AWS Secrets Manager / GCP Secret Manager; the portal resolves them through `shared.cloud` at RDP-access time and fails closed when no reference is recorded. Packer scripts no longer bake credentials into AMIs and user_data never carries the password value. (#762)- **Defense-in-depth ownership checks added to organizer-scoped CTF challenge services.** `create_challenge`, `update_challenge`, `delete_challenge`, and `list_challenges_for_event` now require an `actor_id` keyword argument and raise `CTFPermissionError` when the actor does not own the event. This is a backstop for the existing view-layer `_check_event_ownership` check, so a future internal caller that bypasses the views still cannot mutate another organizer's event content. Cross-organizer regression tests added for the JSON challenge APIs. (#765)- **`api_scoreboard` now refuses to return rankings unless the caller owns the event (organizer) or is a registered participant of it.** Previously any user with any CTF role could read any event's scoreboard — including participant identifiers, names, team names, scores, solve counts, and last-solve timestamps — just by knowing the event UUID. The 404-before-403 ordering for unknown events is preserved so probe traffic does not gain an enumeration signal. (#768)- **Hint unlocks now enforce the same availability policy as flag submission and reject route/body challenge mismatches.** `ctf.services.hint.use_hint` now applies a shared `assert_challenge_available_for_participant` helper (event match, ACTIVE event, competition window, challenge visibility, release state, prerequisites) so participants cannot retrieve hint text for hidden, locked, unreleased, or out-of-window challenges, or for challenges in other events. `api_use_hint` additionally verifies that the URL's `challenge_id` and the optional body `hint_id` refer to the same challenge, closing a path where a participant could unlock a different challenge's hint by supplying its UUID. (#769)- **Experiment creation now enforces `ScenarioMetadata.enabled` and `staff_only`
  as authorization constraints, not presentation hints.** The GET form
  (`cms.experiments.views.experiment_create`) lists scenarios via
  `cms.scenarios.registry.list_all_scenarios(user=request.user)`, so disabled and
  staff-only scenarios are hidden from non-staff Threat Research users. The POST
  path (and the underlying `cms.experiments.services.create_experiment`) routes
  through `cms.scenarios.registry.check_scenario_access`, which rejects disabled
  or staff-only scenarios for non-staff users with `ExperimentValidationError`
  — closing the path where a non-staff Threat Research user could enumerate raw
  YAML IDs and POST one directly. Adds a view-layer regression test in
  `tests/cms/experiments/test_views.py` that drives the full POST flow as a
  Threat Research user against a hidden `scenario_id` and asserts it is
  rejected without reaching experiment creation. (#771)- **Production Django settings now enforce HTTPS and HSTS at the application layer.** `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` (default 1 year), and `SECURE_HSTS_INCLUDE_SUBDOMAINS` default to on when `DEBUG=False`; each is overridable via the matching environment variable. `SECURE_HSTS_PRELOAD` stays off by default — preload-list submission is near-irreversible, so it must be opted into via `SECURE_HSTS_PRELOAD=true` only once the domain is ready for chrome://net-internals submission. Combined with the existing `SECURE_PROXY_SSL_HEADER` config, the redirect is loop-safe behind a TLS-terminating load balancer. (#776)- **Established the policy-layer foundation on the `shifter-ops` MCP server.** Introduced `.shifter.yaml` at the repo root (`mcp_ops:` namespace) declaring capability classes, session profiles, environment policy, class defaults, and an audit log; added `mcp/ops/policy.js` with `parsePolicy`, `loadPolicy`, `profileFromEnv`, the `Policy` class, and a `registerTool` wrapper that gates tool registration by capability class and active session profile. ADR-014 reframed: R1 narrowed to general-purpose MCP servers, new R5 declares the operator-agent surface model and the structured-policy-gate requirement, new R6 prohibits bypass-procedure language in MCP tool descriptions. `mcp/ops/SECURITY.md` and the preflight architecture note rewritten to match. The actual defense gates (env confirm, dry-run, redaction, idempotency, audit, secret handles, two-phase plan→execute, rate caps, untrusted-input fencing, apex out-of-band approval, per-tool wiring, surface tests) land in follow-up issues #1198, #1199, #1200, #1201, #1202. (#777)- Constrained `shifter_platform` to `asyncssh>=2.23.0` and refreshed the lockfile to remove vulnerable `asyncssh` 2.22.0. (#868)- Bump the transitive `idna` dependency 3.13 → 3.18 in both
  `shifter/shifter_platform` and `shifter/engine/provisioner` (pulled in via
  the requests/httpx chain). Clears [GHSA-65pc-fj4g-8rjx][advisory]
  (CVE-2026-45409, moderate): specially crafted inputs to `idna.encode()`
  bypass length validation in `valid_contexto` and trigger excessive
  resource consumption (denial of service), an incomplete-remediation
  follow-up to CVE-2024-3651. First patched in idna 3.15.

  [advisory]: https://github.com/advisories/GHSA-65pc-fj4g-8rjx (#869)- Bump `hono` 4.12.18 → 4.12.23 in the `mcp/ngfw`, `mcp/ops`, and
  `mcp/planner` lockfiles (transitive via `@modelcontextprotocol/sdk`),
  clearing advisories GHSA-2gcr-mfcq-wcc3, GHSA-3hrh-pfw6-9m5x,
  GHSA-f577-qrjj-4474, and GHSA-xrhx-7g5j-rcj5 (all patched in 4.12.21). (#870)- **Patched transitive `qs` dependency copies in MCP packages and the GCP identity-platform function.** The affected lockfiles now resolve `qs` to the non-vulnerable 6.15.2 release, including the Express/body-parser tree used by the identity-platform blocking functions. (#871)- Harden the portal image dependency install to clear SonarCloud Security
  Rating C (`docker:S8541`, `docker:S8544`). Third-party dependencies are now
  installed wheel-only (`--only-binary :all:`) with versions pinned and hashes
  enforced (`--require-hashes`): the frozen `uv` lock is exported with hashes,
  and GCP extras resolve from a new pinned + hashed `requirements-gcp.lock`
  (compiled from `requirements-gcp.txt`). The first-party `cyberscript` and
  `installation` packages now ride on `PYTHONPATH` rather than a pip install,
  since first-party source has no external resolution to lock or hash. Only
  `py-ubjson` (sdist-only, no wheel) keeps a scoped, hash-verified source build. (#876)- Break the CodeQL `py/clear-text-logging-sensitive-data` dataflow at six log
  sites that CodeQL flagged as emitting secrets/passwords in clear text
  (`ngfw_terraform`, `gdc_vmruntime_assets`, the Guacamole RDP/SSH views, and the
  risk-register audit log). Each flagged value now routes through a
  `safe_log_fingerprint` helper — a per-process random nonce with no data
  dependency on the input (and deliberately not a hash, so it does not trip
  `py/weak-sensitive-data-hashing`) — which preserves cross-line correlation while
  removing the value from the log. The platform `shared.log_sanitize` module gains
  `safe_log_fingerprint`/`safe_log_id` to mirror the provisioner's `log_redact`,
  giving both layers one logging-redaction vocabulary. (#878)- **Baselined Django and PyJWT advisories are remediated.** The platform now
  requires Django 6.0.6 or newer and constrains transitive PyJWT resolution to
  2.13.0 or newer, allowing the dependency-policy baseline entries for issue 895
  to be cleared. (#895)- Render AWS range Terraform tfvars from per-environment GitHub secrets, document the matching local overlay model, and replace committed account-bound bucket plus deployment-specific PAN-OS AMI values with placeholders. (#916)- **Deploy workflows no longer route pull requests to self-hosted deploy runners.** AWS/GCP deploy jobs are push or manual-dispatch only, prod AWS deploys can be protected through the `aws-prod` GitHub Environment, and AWS ECR deploys now consume immutable digest-pinned images. (#935)- **GKE authorized-networks allowlist is now fail-closed at the Terraform layer,
  and both gates enforce the same parsed-prefix contract.** `gke_master_authorized_cidrs`
  in `platform/terraform/gcp/modules/platform-core/variables.tf` loses its
  `default = []` and gains a `validation` block expressing a four-part contract
  from the parsed prefix: the list is non-empty; every entry has an explicit
  `/N` suffix (no bare IPs); every entry parses as a CIDR (no garbage, bad
  octets, or bad prefixes); and the parsed prefix length is `> 0` (every
  spelling of `/0`, IPv4 or IPv6, is rejected by prefix number, not by
  string-suffix matching). So `terraform plan` / `terraform apply` /
  `terraform test` fail with a clear error otherwise, including a direct apply
  that bypasses the bootstrap preflight. `scripts/bootstrap/deploy.py`'s
  `validate_gcp_control_plane_security_inputs` is tightened to enforce the
  same four-part contract (`"/" in cidr`, `ipaddress.ip_network(..., strict=False)`,
  `network.prefixlen > 0`), so the two gates stay in lockstep. Coverage in
  `scripts/bootstrap/tests/test_deploy.py::TestGcpControlPlaneSecurityInputs`
  expands to the unsafe inputs both gates reject (bare IPs, garbage with and
  without slashes, bad octets/prefixes, IPv4 `/0`, IPv6 `/0`, mixed lists). The
  cluster runs with `enable_private_endpoint = false`, so
  `master_authorized_networks_config` is the only network-level restriction on
  the public Kubernetes API server; an empty, malformed, or world-open list
  would expose it to the entire internet. Recorded the design and the
  private-endpoint boundary in
  `docs/architecture/gke-control-plane-access-preflight.md` (listed as ADR-008
  evidence). (#957)- **GCP platform and range VPCs now have explicit least-privilege firewall
  policy with per-pool pod-CIDR isolation for the provisioner.** Range VPC
  ingress is deny-by-default; the only ingress allow rule is
  `range-allow-platform-provisioner`, sourced from a NEW dedicated
  secondary pod range (`var.gke_provisioner_pods_cidr`, default
  `10.46.0.0/20`) declared on the GKE subnet and attached to the
  provisioner node pool via `network_config.pod_range`. A compromised
  portal/worker/guacamole pod (running on the shared pod range) can no
  longer satisfy the range firewall rule. The platform VPC now carries an
  explicit deny rule against world-open SSH (22) and RDP (3389), and a
  tag-scoped allow rule for the Google LB health-check ranges so GKE
  backend probes continue to work. Optional break-glass direct admin SSH
  onto platform and range VMs is gated on the new `operator_admin_cidrs`
  module input (empty by default — dev relies on Workload Identity and
  IAM paths) and rides at priority 800, strictly higher precedence than
  the broad world-SSH/RDP deny at 900 so an explicit operator CIDR is not
  shadowed. These admin-SSH rules are direct source-CIDR rules — not IAP
  TCP forwarding rules — and the variable description reflects that. (#959)- **Cloud SQL deletion protection is now on by default for the platform
  control-plane database.** `google_sql_database_instance.platform` now reads
  its `deletion_protection` from the new `cloud_sql_deletion_protection`
  module input, which defaults to `true`. Intentionally disposable
  environments can opt out at the environment-root layer; dev gets the
  secure default automatically. A misclick `terraform destroy` against the
  shared platform database will now be rejected by the provider rather than
  silently wiping control-plane state. (#960)- **Recorded the GCP GCS bucket encryption decision: Google-managed keys
  remain the accepted posture.** ADR-008-R5 (`docs/adr/index.yaml`) is the
  durable record; the
  [gcp-gcs-cmek-preflight](../docs/architecture/gcp-gcs-cmek-preflight.md)
  note carries the rationale, scope, owner, and the explicit review trigger
  (an external compliance requirement). No CMEK / Cloud KMS resources are
  created in this release — CMEK adoption is a separate piece of work
  scoped to the day a compliance driver materializes, not a quiet follow-up. (#962)- **GCP Memorystore for the platform cache now runs on STANDARD_HA tier with
  AUTH and server TLS, end-to-end.** `google_redis_instance.platform` is
  `tier = STANDARD_HA`, `auth_enabled = true`,
  `transit_encryption_mode = "SERVER_AUTHENTICATION"`. The
  provider-generated AUTH token and the Memorystore server CA PEM both
  land in a new `redis` Secret Manager bundle (mirroring the DB-password
  shape) and are hydrated by `entrypoint.sh` as `REDIS_PASSWORD` and
  `REDIS_CA_PEM` — neither value appears in the runtime ConfigMap,
  generated env files, or process argv. Django Channels now builds a
  `channels_redis` dict-form host with a `rediss://` address,
  `ssl_cert_reqs = "required"`, and `ssl_ca_data` set to the Memorystore
  CA so the server certificate is verified against the actual instance CA
  rather than the system trust store. The helper fails closed if TLS is
  enabled without a hydrated password, so silent fallback to a plaintext
  connection is no longer reachable. Both the Helm chart NetworkPolicy and the
  Kustomize-base NetworkPolicy now permit egress on the Memorystore TLS
  port 6378 alongside the existing 6379 — the two cover the bootstrap
  (Helm) and `_gcp-dev.yml` (`kubectl apply -k`) deploy paths respectively.
  The platform-core module's `redis_tier` variable defaults to
  `STANDARD_HA` as the production high-availability posture; AUTH and TLS
  are enforced independently of tier, so a future disposable environment
  can override to `BASIC` without weakening the security contract. (#963)- Remove tracked Terraform plan artifacts from source control. Eight
  `tfplan` / `plan.out` files under `platform/terraform/environments/`
  have been deleted; `.gitignore` now covers Terraform plan outputs
  under both AWS and GCP environment trees. A new ADR-004-R8
  `no-tracked-generated-artifacts` guardrail in
  `scripts/adr_guard/adr_guard.py` fails closed when a plan-named file
  is re-introduced under those roots, including via `git add -f`. (#1180)- Block re-introduction of bootstrap license / authcode material under
  `temp/bootstrap/`. The existing `temp/` `.gitignore` entry covers
  unforced adds; the new ADR-004-R8 `no-tracked-generated-artifacts`
  guardrail in `scripts/adr_guard/adr_guard.py` fails closed when
  `authcodes` / `*.authcodes` are re-introduced under
  `temp/bootstrap/`, including via `git add -f`. The historical
  `temp/bootstrap/license/authcodes` file is not present on `dev` or
  `main`. (#1181)- **Aligned experiment and scenario editor authorization with the documented policy.** The view decorators advertise access for staff and the `Threat Research` group, but the service layer enforced staff-only — silently rejecting Threat Research users that the views had already admitted. The canonical predicate now lives in `shared.auth.can_edit_cms_authoring`, consumed by both `threat_research_required` and the experiment/scenario editor service layers, so the gate cannot drift. Per-scenario `enabled` / `staff_only` filtering via `cms.scenarios.registry.check_scenario_access` is unchanged. (#1183)- Stop injecting sensitive provisioner env vars as literal Kubernetes
  Job env vars. The GCP Job adapter
  (`shifter/shifter_platform/shared/cloud/gcp/task_runner.py`) now
  splits the provisioner `env_overrides` into sensitive vs.
  non-sensitive halves via a new
  `shared.cloud.gcp.sensitive_env.split_env()` classifier. Sensitive
  keys (`DB_PASSWORD`, `FIELD_ENCRYPTION_KEY`, `DC_DOMAIN_PASSWORD`,
  plus any name matching the `_PASSWORD` / `_PASSPHRASE` /
  `_PRIVATE_KEY` / `_API_TOKEN` / `_CREDENTIAL` / `_SECRET` suffix
  rules) are routed through `valueFrom.secretKeyRef` pointing at an
  ephemeral per-Job Secret. The Secret is created before the Job is
  submitted, garbage-collected via `ownerReferences` once the Job is
  deleted, and cleaned up on Job-creation failure. Pointer suffixes
  (`_ID`, `_REF`, `_ARN`, etc.) take precedence so identifiers like
  `GDC_ACCESS_SECRET_ID` remain literal env vars. (#1185)- Documented and pinned the AI experiment execution boundary for Claude Code runs. Experiment command dispatch now includes the `ai-experiment-execution-v1` policy payload for audit correlation, and regression tests guard the allowed `claude --dangerously-skip-permissions --output-format stream-json` invocation and transcript capture contract. (#1186)- **Experiment script dispatch no longer interpolates raw S3 keys or Claude prompts into remote shell syntax.** Script execution now uses fixed wrappers that decode validated payload data before invoking tools with structured argv. (#1187)- **CTF HTTP flag validators now pin outbound connections to a pre-validated IP.** Closes a DNS-rebinding window where a hostname could resolve to a public address during validation but to a loopback, private, link-local, or cloud-metadata address at request time. Every IPv4/IPv6 answer in the DNS reply must pass SSRF policy or the request is refused, and the TLS socket is opened to the validated address while SNI, certificate verification, and the `Host:` header retain the original hostname. (#1188)- Make provisioner field decryption fail closed. `decrypt_field()` in
  `shifter/engine/provisioner/config.py` no longer silently returns the
  input when `FIELD_ENCRYPTION_KEY` is missing or when the value fails to
  decrypt. A new `FieldDecryptError` is raised on missing key, malformed
  base64, and Fernet token failures (wrong key, malformed token); the
  exception message never carries the input value. Empty input still
  returns `""` as the absent-field sentinel. Adds tests covering each
  failure mode. (#1189)- Require verified TLS for the `mcp/ops` Postgres pool. The pool config
  in `mcp/ops/lib.js::buildPoolConfig` no longer disables TLS
  verification — `rejectUnauthorized` stays `true` and `ssl.servername`
  is set to the RDS endpoint discovered when the SSM tunnel started, so
  SNI and hostname verification fire against the real RDS endpoint
  instead of the localhost target of the port forward. The
  `mcp-ops-tls-strict` adr_guard check (ADR-014-R7) backstops any other
  file under `mcp/ops/` that would re-introduce `rejectUnauthorized:
  false`. The trust model and refresh procedure are documented in
  `mcp/ops/SECURITY.md` § "Database TLS". (#1190)- Make every Bandit SAST job blocking. `continue-on-error: true` is
  removed from the `packer`, `bootstrap`, `gcp-scripts`,
  `check-layer-imports`, and `installation` SAST jobs in
  `.github/workflows/_quality.yml`. All seven Bandit jobs now block
  merge on findings. A leading comment in the SAST section documents
  the scope and owner, and the policy that adding a new Bandit job
  must not reintroduce advisory mode without a fix-narrow-or-nosec
  exception. Verified against all five previously-advisory paths
  locally — current findings: zero. (#1193)- New `no-populated-secret-env-files` `adr_guard` check (ADR-004-R9)
  prevents reintroducing populated values into tracked `*-secrets.env`
  files under `platform/k8s/`. Allowed: comments, blank lines, empty
  assignments (`KEY=`), and a **fixed** synthetic-placeholder allowlist
  (`REPLACE_AT_DEPLOY`, `CHANGE_ME`, `PLACEHOLDER`, `EXAMPLE`, plus the
  matching bracketed forms `<replace-at-deploy>`, `<change-me>`,
  `<placeholder>`, `<example>`). The bracket allowlist is explicit
  rather than a `<...>` pattern so a real credential cannot hide as
  `<attacker-known-password>`. Parser splits on the first `=` so
  non-identifier key shapes (`db.password=...`, `api-token=...`,
  `export DB_PASSWORD=...`) still flow through the value check; inline
  `# ...` is not honored as a comment; non-`=` lines are flagged as
  malformed. Containment uses `git ls-files`, so gitignored local-dev
  files are intentionally not scanned. Violation messages name the path
  and variable name only, never the rejected value. Registered in
  `fast` and `ci` levels; backstops gitleaks for low-entropy credentials
  it ignores. The plaintext-removal content fix already shipped in
  #1207. (#1195)- Wire the Phase 2 policy gates atop `registerTool` in
  `mcp/ops/policy.js` (per parent issue #777). The wrapper now composes
  five class-driven gates around every handler: env policy
  (`confirm_env="prod"` required for prod calls), dry-run defaults
  (`infra_mutation`/`ssm_arbitrary`/`db_arbitrary` return preview unless
  `execute=true`), description redaction (`dev_bypass_tunnel` text
  replaced before `list_tools`), idempotency keys (`named_db_write`
  requires `idempotency_key`; same key returns cached result for 15
  minutes), and secret handles (`secret_handle` tools return
  `shf-secret:<uuid>` references; raw values resolvable only in-process
  via `resolveSecretHandle`). A new `mcp/ops/audit.js` writes one
  JSONL record per call to the path declared in `.shifter.yaml`'s
  `audit.path` with `audit.redact` list applied. The 45 tools in
  `mcp/ops/index.js` are still wired through `server.tool()` directly;
  Phase 5 (#1201) is what routes them through `registerTool`. (#1198)- Add Phase 3 mid-cost policy defenses to `mcp/ops`'s `registerTool`
  wrapper (per parent issue #777). The wrapper now composes three new
  gates around every handler in the two-phase classes:

  - **Two-phase `plan_<name>` → `execute_<name>`.** For
    `infra_mutation`, `ssm_arbitrary`, and `db_arbitrary` tools, the
    wrapper registers a paired `plan_<name>` (captures verbatim args,
    returns `{plan_id, summary, ttl_seconds: 60}`, no handler run) and
    `execute_<name>` (consumes the matching plan_id atomically, runs
    the stored handler args through rate-cap + apex-approval +
    idempotency). The plan store is in-process, volatile, bounded to 64
    entries, single-use, with a 60-second TTL; expired entries are
    reaped on every access.
  - **Per-class sliding-window rate caps.** Reads
    `class_defaults.<class>.rate_cap = {count, window_seconds}` (with
    per-tool overrides via `tools.<name>.overrides.rate_cap`) and
    refuses execute-side calls that would exceed the cap. The
    `infra_mutation` default is `{count: 3, window_seconds: 60}`. Plan
    calls do not consume capacity.
  - **Startup profile from env.** `index.js` now resolves
    `SHIFTER_OPS_PROFILE` via `profileFromEnv(process.env)` and passes
    it to `loadPolicy({path, profile})` at server startup; missing or
    malformed `.shifter.yaml` aborts startup before any tool is
    registered. (#1199)- Add Phase 4 expensive policy defenses to `mcp/ops`'s `registerTool`
  wrapper (per parent issue #777):

  - **Untrusted-input fencing.** Producer descriptors declare an
    `untrusted_source` label (from `.shifter.yaml`'s allowlisted
    `untrusted_sources:` list) and the wrapper post-processes the
    handler's text return into `[UNTRUSTED:<source>:BEGIN] ...
    [UNTRUSTED:<source>:END]`. Producers: `get_log_events`,
    `filter_log_events`, `tail_logs` (source `logs`), `get_s3_object`
    (`s3`), and `ssm_get_command_output` (`ssm_stdout`). Consumer
    descriptors declare an `untrusted_inputs: ["<field>"]` list; the
    wrapper scans only those declared fields for a fence pattern and
    refuses the call unless `acknowledge_untrusted_input: true` is set.
    Consumers: `query.sql`, `execute.sql`, `ssm_send_command.command`,
    `run_manage_command.command`.
  - **Apex out-of-band operator approval.** A new `apex_operations:`
    block in `.shifter.yaml` declares apex-gated rules by
    `{tool|class, env, operation_kind, requires_write?}`. Defaults:
    prod `terminate_ec2_instance`, prod `restart_ecs_service`, and prod
    `db_arbitrary` writes. The wrapper generates a random 32-char hex
    token, prints `[apex-approval] <tool> ... token=<...>` to stderr
    (never to MCP responses, audit args, plan summaries, argv, env, or
    `.shifter.yaml`), and parks the handler. A dedicated `approve`
    MCP tool consumes the token and releases the parked handler;
    unknown / already-consumed / expired tokens fail closed. A 60-second
    timeout rejects the parked handler, so headless / CI runs fail
    closed automatically. (#1200)- Migrate all 45 `mcp/ops` tool registrations from raw `server.tool(...)`
  to policy-gated `registerTool(ctx, {...})` descriptors (per parent
  issue #777, Phase 5). The descriptor is the authoritative source for
  each tool's capability class; `.shifter.yaml` remains the single
  source of truth for class defaults, profiles, environment policy,
  audit config, per-tool overrides, the `apex_operations` list, and the
  `untrusted_sources` allowlist.

  Class assignments per the Phase 5 preflight:

  - `observability` (17): `describe_log_streams`, `get_log_events`,
    `filter_log_events`, `tail_logs`, `list_ec2_instances`,
    `list_ecs_tasks`, `describe_ecs_service`, `describe_asg`,
    `describe_target_health`, `list_s3_buckets`, `list_s3_objects`,
    `get_s3_object`, `terraform_state`, `cost_summary`, `daily_spend`,
    `risk_dashboard`, `risk_matrix`.
  - `secret_handle` (2): `list_secrets`, `get_secret`.
  - `ssm_arbitrary` (2): `ssm_send_command`, `ssm_get_command_output`.
  - `ssm_named` (1): `run_manage_command`.
  - `dev_bypass_tunnel` (2): `start_portal_test_tunnel`,
    `stop_portal_test_tunnel`.
  - `infra_mutation` (5): `start_ec2_instance`, `stop_ec2_instance`,
    `terminate_ec2_instance`, `restart_ecs_service`, `reconcile_ranges`.
  - `db_arbitrary` (4): `list_tables`, `describe_table`, `query`,
    `execute` (with `is_write: true` so apex `requires_write` matchers
    fire on `execute` but not on read-only queries).
  - `named_db_read` (6): `list_risks`, `get_risk`, `risk_audit_log`,
    `list_ranges`, `get_range`, `list_subnet_allocations`.
  - `named_db_write` (6): `create_risk`, `update_risk`, `delete_risk`,
    `restore_risk`, `add_risk_comment`, `delete_risk_comment`.

  A new `approve` MCP tool (class `observability`) lets the operator's
  agent release pending apex-approval tokens. The server loads
  `.shifter.yaml` via `loadPolicy({path, profile: profileFromEnv(env)})`
  at startup and fails closed on missing or malformed policy.
  Operators who need destructive classes
  (`infra_mutation`, `ssm_arbitrary`, `db_arbitrary`,
  `dev_bypass_tunnel`) must set `SHIFTER_OPS_PROFILE=destructive` —
  the default `standard` profile no longer registers those tools. (#1201)- Add Phase 6 negative-surface tests for `mcp/ops` at
  `mcp/ops/tool-surface.test.js` (per parent issue #777). The suite is
  the load-bearing ADR-014-R3 / R5 / R6 invariant for this server: it
  exercises the live registration path — real `.shifter.yaml`, real
  `loadPolicy`, real `registerTool` — against a fake server and asserts:

  - Profile gating actually removes tools from the registered set
    (`read_only` / `standard` / `destructive`); a disabled class
    produces no `server.tool(...)` call at all (not "registered but
    refused").
  - Two-phase classes (`infra_mutation`, `ssm_arbitrary`,
    `db_arbitrary`) register `plan_<name>` / `execute_<name>` pairs
    only; the direct `<name>` is absent. `execute_<name>` without a
    `plan_id` arg throws `PolicyError`.
  - `class_defaults.secret_handle.return_mode = "handle"` is enforced
    by the live policy (the ADR-014-R5 structural invariant);
    `get_secret` is the only `secret_handle` registration on the
    surface (`list_secrets` is correctly `observability`).
  - Prod-touching tools refuse without `confirm_env="prod"` (gate
    applies class-wide, not tool-specific).
  - `dev_bypass_tunnel` descriptions are replaced with the
    `policy.js` `REDACTED_DESCRIPTION` constant verbatim; the
    defense-in-depth scan also checks for `/dev-login/`, `bypass`,
    `Cognito`, and `MFA` substrings.
  - Consumer tools (`plan_query`, `plan_execute`,
    `plan_ssm_send_command`) refuse fenced input unless
    `acknowledge_untrusted_input: true` is set; the registered schema
    exposes the control field.
  - Every `apex_operations[*].tool` rule in `.shifter.yaml` points at a
    registered `execute_<name>`; `validateApexCoverage` is the
    load-bearing gate, called from `registerAllOpsTools(ctx)`'s last
    step.

  `mcp/ops/index.js` gains a narrow seam for this: the
  `registerTool(ctx, {...})` block + `validateApexCoverage(policy)`
  move into an exported `registerAllOpsTools(ctx)` function, and
  `new McpServer` / `loadPolicy` / `await server.connect(...)` move
  behind an `async main()` guarded by
  `if (import.meta.url === pathToFileURL(process.argv[1]).href)`.
  Live behavior when run as `node mcp/ops/index.js` is unchanged. (#1202)- Bump vulnerable dependencies flagged by Dependabot. Python: `paramiko`
  4.0.0 → 5.0.0 and `urllib3` 2.6.3 → 2.7.0 in `shifter/engine/provisioner`;
  `django` 6.0.4 → 6.0.5, `paramiko` 4.0.0 → 5.0.0, `twisted` 25.5.0 →
  26.4.0, and `ujson` 5.12.0 → 5.12.1 in `shifter/shifter_platform`. npm:
  `hono`, `ip-address`, `fast-uri`, and `express-rate-limit` bumped in
  `mcp/ops` and `mcp/planner` via `npm audit fix`. Clears advisories around
  proxied redirect header leakage (urllib3), decompression-bomb safeguards
  (urllib3), DNS DoS (twisted), JWT NumericDate validation (hono), CSS
  declaration injection (hono), cache cross-user leakage (hono), HTML XSS
  (ip-address), and percent-encoded host/path confusion (fast-uri). (#1222)- **Credential SCM PINs and NGFW authcodes are now encrypted inside persisted CMS credential JSON data.** Existing plaintext credential secrets are migrated to encrypted values, while application reads continue to receive decrypted values for provisioning.- **Experiment and scenario editor services now enforce staff-only access in the service layer.** This duplicates the existing view-level checks so accidental future entry points cannot bypass staff authorization.- **SSH management paths now enforce host-key verification.** Terminal, NGFW provisioning, NGFW deprovisioning, and NGFW MCP commands no longer disable SSH server authentication.- **Scenario editor delete confirmation no longer embeds scenario names in inline JavaScript.** The scenarios list now binds delete confirmation handlers in a separate script and reads names from a safely escaped `data-scenario-name` attribute, preventing stored XSS via crafted scenario names.- **Stopped the NGFW provisioner from dumping full Terraform output dicts to the
  logs.** `ngfw_terraform.py` logged `json.dumps(output_data)` after both the AWS
  and GDC VM-Series applies; those output dicts carry a Secret Manager /
  Secrets Manager reference (`ssh_key_secret_id` / `ssh_key_secret_arn`), so the
  dump wrote the reference in clear text (CodeQL `py/clear-text-logging-sensitive-data`)
  and would have leaked any future sensitive output field. Both sites now log
  only the non-sensitive correlation IDs (`request_id`, `instance_id`) and an
  output-field count, via `log_redact.safe_log_value`.- **Stored XSS in CTF event form via scenario names is fixed.** `admin_event_create` and `admin_event_edit` no longer serialize scenario data with `json.dumps()` and pass it through `|safe` in the template. The views now pass a plain Python list and the template embeds it with Django's `json_script` filter, which escapes `<`, `>`, and `&` for safe inline script use. A scenario name containing `</script>` can no longer break out of the script block.- - Hardened `mcp/ngfw` by removing PAN-OS command execution tools from the MCP surface, so connected MCP clients can no longer run firewall admin commands or trigger Secrets Manager SSH key retrieval through this server.- Delete sensitive NGFW bootstrap S3 objects after the firewall reaches READY.- Hardened `mcp/planner` plan file access so `plan_id` must match the generated 8-character lowercase hex ID format, with path resolution containment checks that block traversal-based reads/deletes outside the planner directory.- Moved GCP dev VM guest password environment values out of the generated
  `platform-runtime` ConfigMap into a generated Kubernetes Secret and wired
  runtime Deployments to load those values via `secretRef`.- `SetupOrchestrator` now redacts known secret values from command stdout/stderr before writing setup logs.### Added

- **Terminal UI surfaces per-instance IP and range number.** The Mission Control
  terminal now shows each instance's internal IP next to its name in tabs,
  split-mode dropdowns, and pane headers, and appends `- Range N` after the
  scenario name in the header. This lets users correlate connected sessions with
  XDR/XSIAM alerts (which key off IP) and the XDR tenant view (which keys off
  range number). The IP is sourced through the existing `engine.services`
  runtime-state contract, projected into `InstanceContext` by CMS, and rendered
  via Django's `json_script` tag so the terminal payload no longer relies on
  inline JavaScript interpolation. (#370)- Added a CI-time lint that statically scans provisioner setup plans and fails when a script or `stdin_input` contains an unrendered `{{word}}` template token that is not a declared render-context key. This catches the placeholder collision (e.g. a stray `{{end}}`/`{{range}}`) before it fails on a live range at provisioning time. (#616)- **Pre-event Polaris scenario-content smoketest harness.** The new
  `scenario-dev/polaris/tests/scenario_smoketest/` package is an operator-run,
  on-demand verifier that walks each CTFd challenge's canonical participant path
  against a real staged range and checks the value it produces against the flag
  configured in `ctfd-challenges.json`. The challenge universe is derived from
  the board, so a challenge with no registered adapter is reported `uncovered`
  (a failure) rather than silently skipped. It additionally performs the
  read-only CTFd flag-row readback from `lessons-4.md` checklist item 4
  (`GET /challenges/{id}/flags`, asserting non-empty) that catches the regression
  where a `sync_polaris_ctfd.py` re-sync shipped 38/39 challenges unsubmittable.
  Flag bodies are redacted to stable digests in all output. Run with
  `python3 -m scenario_smoketest`; it is not wired to CI. (#617)- **Added an operator-triggered Polaris scenario AMI bake workflow.** The new
  `polaris-scenario-bake.yml` (`workflow_dispatch` only, mirroring `packer.yml`)
  builds the Polaris build tarball, stands up and health-checks a golden range,
  creates the `polaris-vm` AMI, and updates the SSM parameter. A
  repo→AMI content drift audit is documented in
  `docs/architecture/polaris-repo-to-ami-drift-audit.md`. (#618)- Added shared authenticated WebSocket notification infrastructure with topic subscriptions, persisted missed-event replay, and experiment status notification registration. (#679)- ### Added
  - Platform-level range egress IP allowlist (PLAT-220): `settings.range_egress` in `shifter.yaml` declares the policy once and is enforced uniformly on AWS (Network Firewall rule groups) and GCP (VPC firewall egress rules). The committed Terraform baseline carries an empty allowlist; operators write per-deployment CIDRs into a gitignored `local.auto.tfvars` so the repo no longer holds any deployment's allowlist. See `docs/architecture/range-egress-ip-allowlist.md` and ADR-017. (#775)- **Deploy control-plane gating is verified by one workflow-as-data model, with
  a new ADR-003-R5 hard check.** `adr_guard.py` now carries a single model that
  reads `deploy.yml` and the reusable deploy workflows as data and evaluates
  their `if:` gates, branch/event routing, and change filters semantically. A new
  `deploy-workflow-runner-exposure` adr_guard check enforces ADR-003-R5 at commit
  time: every self-hosted deploy job must fail closed on `pull_request`, proven by
  evaluating the job's `if:` for a pull_request event rather than substring
  matching (so a guard broadened with `|| always()` is caught). The consolidated
  test suite (`scripts/adr_guard/tests/test_deploy_workflow.py`) exercises the same
  model for the remaining invariants: deploy jobs fail closed when an upstream is
  `failure`/`cancelled` (#781), `workflow_dispatch` on `main` is the only
  production-apply path and no `pull_request` routes a provider deploy (#892), the
  `portal_image` (app image) and `shifter_platform` (Terraform) change filters
  stay split (#913), mutating jobs bind a GitHub Environment, and the engine deploy
  pins an immutable ECR digest. This replaces the earlier substring-based
  `test_deploy_workflow_security.py`, folding deploy-workflow verification into one
  home and one parser. (#921)- ### Added

  - Added an ADR guard boundary-mock policy that blocks new first-party internal mock patch targets while allowing the existing legacy test baseline to shrink over time.
  - Updated the SonarCloud CI job to use Node 24-backed action majors while preserving its coverage restore, scanner execution, and quality-gate reporting. (#927)- **AWS worker containers now self-heal and surface health to CloudWatch.** A host-level systemd-timer supervisor on the portal EC2 instance watches the `worker-cms`, `worker-engine`, `worker-mc`, and `ctf-scheduler` container health status, restarts any that go unhealthy (e.g. a wedged worker that is alive but not heartbeating), and emits a `Shifter/WorkerHealth` CloudWatch metric. A new `UnhealthyWorkers` alarm notifies the per-environment SNS alerts topic when a worker stays unhealthy. Previously `--restart unless-stopped` acted only on process exit, so a wedged worker stalled silently with no signal to CloudWatch. The supervisor is installed identically by both the fresh-boot (`user_data.sh`) and SSM-redeploy deploy paths. (#953)- **Added OSS Shifter UX research personas for the redesign foundation.** The new
  `docs/design/ux-003-oss-shifter-research-personas.md` artifact documents the
  core user archetypes, surface-by-surface jobs to be done, current-state pain
  points, and the APTL-derived dark operational visual direction that future UX
  issues can cite without introducing mockups or runtime UI changes. (#1092)- **OSS-release hygiene: community files, dependency automation, CI hardening, identifier strip, and a tfvars baseline + override refactor.** Added PANW org community templates verbatim (`SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`) and restructured `README.md` to follow the PANW open-source README example with a `Maintainers` section. Added `.github/dependabot.yml` enumerating every uv, npm, github-actions, and pre-commit package root (all targeting `dev`); a CodeQL workflow (`security-extended` suite, least-privilege permissions, no `pull_request_target`); and a PR-title-lint workflow validating conventional-commit titles. Stripped the SonarCloud project token from `README.md` badges and narrowed `.gitleaks.toml` allowlists previously needed only for that token. Replaced committed `keplerops.com` / `bedwards@paloaltonetworks.com` references with `example.com` placeholders outside the PANW-event-specific tooling under `scenario-dev/polaris/` and `platform/terraform/global/tssummit/`. Restructured `terraform.tfvars`: the four files in `dev/portal`, `prod/portal`, `gcp-dev`, and `ctfd-workshop` ship `example.com` baselines and deployment-specific values come from gitignored `local.auto.tfvars` (Terraform auto-loads `*.auto.tfvars`). CI deploy workflows (`_gcp-dev.yml`, `_shifter-platform.yml`) now source deployment values from GitHub secrets / repository variables instead of grepping committed tfvars; the full required surface is documented in `docs/dev/deploy-secrets.md`. Bootstrap email validator no longer hardcodes `@paloaltonetworks.com` — it derives the required domain from the Terraform `identity_allowed_email_domain` output (matching what the Identity Platform `beforeCreate` hook enforces). Generated kustomize files are kept as `REPLACE_AT_DEPLOY` placeholders where needed for static validation, with the deploy renderer overwriting at apply time. (#1196)- **Adopted [`towncrier`](https://towncrier.readthedocs.io/) for changelog management.** PRs no longer hand-edit `CHANGELOG.md`; they drop a tiny fragment under `changelog.d/<issue>.<type>.md` (with `<type>` one of `security` / `added` / `changed` / `deprecated` / `removed` / `fixed`), and the release process collates fragments into `CHANGELOG.md` via `uvx towncrier build`. Eliminates the merge-conflict pathology where every open PR had to be rebased — re-running the full `Deploy` workflow each time — every time another PR merged, just to move a `CHANGELOG.md` line. Includes `.gitattributes` `CHANGELOG.md merge=union` as belt-and-suspenders.### Changed

- Portal web process now runs Gunicorn with Uvicorn workers
  (`-k uvicorn_worker.UvicornWorker`) by default in the container
  `entrypoint.sh`, instead of a single Daphne process. An unhandled
  exception in a WebSocket consumer now crashes only one worker and
  Gunicorn restarts it, instead of taking the whole portal down. Worker
  count, bind address, and timeouts are env-owned:
  `PORTAL_WEB_WORKERS` (default `4`), `PORTAL_WEB_BIND`
  (default `0.0.0.0:8000`), `PORTAL_WEB_TIMEOUT` (default `90s`),
  `PORTAL_WEB_GRACEFUL_TIMEOUT` (default `30s`). `daphne` remains in
  `INSTALLED_APPS` for local Channels `runserver` integration. (#174)- **Polaris operator and CTFd sync scripts now share AWS/SSM and reconcile
  helpers instead of duplicating them.** `scripts/polaris-aws-range/common.py`
  owns the boto3 session, EC2 portal-instance discovery, SSM
  ``send_command``/poll loop, Django-shell-via-SSM transport, JSON envelope
  parsing, and a sensitive-output redaction helper; provisioning state,
  batch state-machine, and range-health probe model are now their own
  modules. `scripts/ctfd-workshop/ctfd_reconcile.py` owns the generic CTFd
  row-reconciliation surface (page/challenge upsert, flag/hint reconcile,
  manifest readers); `scripts/ctfd-workshop/polaris_manifest.py` owns
  Polaris-specific challenge ordering, validation, and prerequisite
  resolution. `seed_ctfd.py`, `sync_polaris_ctfd.py`,
  `sync_polaris_ctfd_onboarding.py`, `orchestrate_provisioning.py`,
  `check_range_health.py`, and `cleanup_non_keepers.py` are now thin CLI
  entrypoints over these shared helpers. (#691)- **Platform test suites now enforce smaller behavior-focused modules.** Oversized CMS, CTF, engine, Mission Control, and shared schema tests were split by API boundary, and a structural pytest guard now catches future test modules over 800 lines or `Test*` classes over 300 lines. (#693)- Scenario editor service internals are split by responsibility while preserving the existing public service API and YAML behavior. (#699)- **Scenario editor views now delegate form and YAML validation to the service layer while preserving existing routes and templates.** (#700)- Polaris onboarding: CTFd orientation page now leads with a `Start Here` hero CTA above the mission narrative; the briefing deck closing was reordered so the literal first-click path (magic-link → ENTER RANGE → Kali → Start Here on `polaris.keplerops.com`) is the final projected handoff; added a printable seat handout under `scenario-dev/polaris/briefing-deck/seat-handout.html` for each seat. Removes the "where do I start" tax called out in `scenario-dev/polaris/lessons-4.md` from the May 2026 cohort. (#704)- **Scenario template cleanup for OSS distribution.** The `cms/scenarios/templates/` set now ships only `basic`, `basic_ngfw`, `ad_attack_lab`, `ad_attack_lab_ngfw`, and `polaris`. `basic.yaml` and `ad_attack_lab.yaml` are the PANW-free variants (`ngfw: false`, `xdr_agent: false` on all instances); `basic_ngfw.yaml` and the new `ad_attack_lab_ngfw.yaml` are the PANW variants with NGFW segmentation and Cortex XDR on the Windows instances. `cortex_byot.yaml`, `cortex_deployment_experience.yaml`, and `agentic_workshop.yaml` have been removed along with their dedicated supporting assets (`shifter/packer/ctf-*.pkr.hcl`, `shifter/packer/scripts/ctf/`, `shifter/packer/tests/test_ctf_boxes.py`, `scripts/ctfd-workshop/agentic_workshop.json`, `scripts/ctfd-workshop/seed_ctfd.py`, `scripts/ctfd-workshop/sync_range_flags.py`, `docs/scenarios/cortex-byot.md`, `docs/features/ctf.md`, `docs/features/ctf-organizer-guide.md`, `docs/features/ctf-uvic-customization.md`) and the corresponding `ctf-*` AMI choices in the Packer build/promote workflows. (#780)- Browser SSH terminals now have per-process and per-user session caps, idle and maximum-duration timeouts, and a low-frequency output poll, so terminal websocket load no longer destabilizes the portal during live events. The limits are tunable via the `TERMINAL_MAX_SESSIONS`, `TERMINAL_MAX_SESSIONS_PER_USER`, `TERMINAL_IDLE_TIMEOUT_SECONDS`, `TERMINAL_MAX_SESSION_SECONDS`, and `TERMINAL_READ_POLL_SECONDS` environment variables. (#847)- **Decoupled the portal Django Channels backend from autoscaling mode.** The
  channel-layer backend is now an explicit, environment-owned posture
  (`CHANNEL_LAYER_BACKEND` / the Terraform `enable_redis` knob) instead of a side
  effect of `enable_autoscaling`: a single-instance portal can run on Redis, an
  environment can disable Redis without changing ASG posture, a `redis` posture
  fails closed when `REDIS_HOST` is missing rather than silently using the
  in-memory layer, and the active backend is logged once at startup. Defaults
  preserve current behavior (dev in-memory, prod Redis). See ADR-018. (#849)- - Provisioner internals now import their owning modules directly instead of routing through `main.py`, and the extracted provisioner modules are back in Sonar coverage. (#946)- Quality routing now runs validation by default for pull requests and `dev` pushes, with ordinary docs-only diffs as the only general skip path and guardrail documentation still treated as quality-relevant. (#954)- CI quality gates now run the previously orphaned support test suites, including cyberscript, Polaris AWS range helpers, scenario smoketests, migration proof coverage, and MCP planner checks. (#955)- ### Changed

  - Enforced the protected-branch CI baseline by removing the `[skip tests]` bypass, adding an always-on pre-commit hygiene/secret-scan job to `PR Gate`, and running CodeQL for both `main` and `dev` PRs. (#974)- **Hard per-function complexity gate via Ruff `C901` (ADR-012).** Every lint-scoped Python package now enforces a McCabe per-function complexity limit of 15 (matching SonarCloud's default cognitive-complexity threshold). The gate runs through the existing Ruff pre-commit hooks and the per-package `*-lint` jobs in `.github/workflows/_quality.yml`. A new `python-complexity-gate` adr_guard check backstops the runtime gate with prefix-aware validation of `select`/`extend-select`/`ignore`/`extend-ignore`/`per-file-ignores`, cross-checks `PYTHON_COMPLEXITY_GATE_PYPROJECTS` against the `id: ruff` hooks in `.pre-commit-config.yaml`, reconciles in-source `# noqa: C901` exemptions against `docs/adr/complexity-backlog.md`, and rejects bare `# noqa` on function definitions. Eleven existing offenders (6 in `shifter_platform`, 5 in `shifter/engine/provisioner`) carry explicit per-function `# noqa: C901` exemptions and are listed in the backlog doc; the threshold ratchets down as that backlog shrinks. (#1135)- `mcp/ngfw/SECURITY.md` rewritten to describe the current `list_ngfws`-only
  tool surface and to mark the previously-registered PAN-OS administration
  tools (`run_command`, `show_system_info`, `show_routes`) as explicitly
  historical. `mcp/ngfw/tool-surface.test.js` is now the bidirectional
  guard: it parses `server.tool(...)` registrations out of `index.js` and
  asserts the set equals exactly `{"list_ngfws"}`; it asserts the security
  doc references the test by name and lists every live tool; and it
  asserts removed tools cannot be described before the
  `## Removed administration tools` section. A future surface change must
  update both the test's expected set and the security doc in the same PR. (#1191)- ### Changed

  - Added minimum Django i18n infrastructure and routed platform template literals through the English gettext catalog. (#1257)- **Internal code-quality cleanup of the GCP/GDC provisioner and portal notification
  code.** Resolved the SonarCloud findings surfaced on the `dev` → `aws-dev`
  promotion: replaced bare `Any` hints with specific types (kubernetes client
  classes via `TYPE_CHECKING`, `botocore` `BaseClient`, Jinja `Template`, Django
  user types), added missing docstrings, wrapped over-length lines, de-duplicated
  string literals into constants, reduced over-parameterized helpers via small
  frozen-dataclass parameter objects, and lowered the cognitive complexity of the
  VPC-endpoint waiter. No runtime behavior change.- Consolidated Dependabot dependency updates across GitHub Actions, pre-commit hooks, and Python/npm packages.- Submission rate-limit errors for flag submissions now include a `retry_at` timestamp in the error details and message so clients can show participants exactly when they may submit again.### Removed

- **Removed the superseded Polaris post-bake hotfix scripts.**
  `apply_kali_bedrock_shard.py`, `apply_splice_watcher.py`, and
  `run_postprovision.sh` patched already-deployed ranges by SSM fan-out before
  their logic moved into `PolarisRangeBootstrapPlan`. They are deleted to end the
  dual-ownership the bootstrap plan now covers. (#618)### Fixed

- Grant `kms:Decrypt` on the portal Secrets Manager CMK to the provisioner ECS execution role and the portal EC2 instance role, fixing dev range provision/destroy/pause/resume tasks that aborted at startup with `AccessDeniedException: Access to KMS is not allowed` whenever the task definition referenced a secret encrypted with the post-2026-05-11 CMK. The portal `entrypoint.sh::fetch_runtime_secret` helper now propagates secret-fetch failures instead of silently returning empty strings, so a misconfigured runtime secret aborts container start rather than letting the container run with blank required env vars. A new `check-tf-kms-secrets-grant` pre-commit hook prevents the IAM regression from recurring. (#52)- - Applied the existing `PLATFORM_BOOTSTRAP_STAFF_EMAILS` /
    `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` admin elevation contract to the
    AWS/Cognito OIDC path and AWS platform deploy runtime. (#70)- **First-click RDP connections no longer redirect to the Guacamole login page.** The Mission Control broker now retries the Guacamole `/api/tokens` exchange with bounded exponential backoff for transient gateway/connection errors, closing a token-readiness race that surfaced as a failed first click followed by a successful second attempt. Tunable via `GUACAMOLE_TOKEN_RETRY_ATTEMPTS` and `GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS` (defaults: 3 attempts, 200ms base delay). (#395)- **Portal `/health` now reflects real dependency probes instead of always returning 200.** The endpoint runs the registered `django-health-check` database, cache, and storage checks and returns 500 when any probe fails. Load-balancer probes still admit past `ALLOWED_HOSTS` via a path-scoped Host-header normalization, and the public response stays coarse (a `working` / `unavailable` token per probe) so dependency failures do not leak DSNs, bucket names, or private hostnames. (#477)- **CTF scheduler startup now has a regression guard and the GCP scheduler pod can use the existing job-launcher RBAC when due event spin-up tasks submit provisioner Jobs.** (#484)- Hint-penalised CTF solves can now award `0` points instead of the historical `1`-point floor when the cumulative hint penalty reaches 100%, matching `CTF-203`'s "net score for a challenge solve shall never go below zero" clause. Also removed two stale `CTFSubmission.hint_used` references (admin participant-detail badge and a test factory dict key) that pointed at a field deleted in migration `0017`. (#519)- **Fixed the A0 Boreas annual report dropping its flag 6 payload.** The
  `build_pdfs.py` generator now sources flag 6 from the CTFd board
  (`ctfd-challenges.json`) and renders it on the Kursk Heavy Industries line of
  `boreas-annual-2025.pdf`, so a clean-checkout rebake can no longer reintroduce
  the "Follow the Money" Ottawa bug. A bake-time smoke (`verify_flags_baked.py`)
  and the A0 smoketest now assert the canonical flag is present in the artifact. (#619)- The Polaris CTFd board sync now reconciles flag, hint, and tag rows on every challenge upsert instead of only for a hard-coded subset of categories, so re-syncs no longer leave mission challenges unsubmittable. The sync also validates the source manifest before mutating CTFd and verifies flag/hint rows after sync, failing loudly when a challenge has none. (#702)- Polaris CTFd sync now aliases canonical `FLAG{<16-hex>}` static flags to one case-insensitive regex row per source flag that accepts either the wrapped form or the bare `<16-hex>`. Participants who copy only the inner hex from a recovered artifact submit successfully; the wrapped form keeps working. Source `FLAG{<16-hex>}` content in `ctfd-challenges.json` / `ctfd-onboarding.json` and in all walkthroughs/page copy is unchanged. Manifest validation now rejects malformed wrappers and any non-16-hex body before any live CTFd write so a short or non-hex source can never derive a trivially short accepted answer. (#705)- Move Guacamole RDP/SSH token bootstrap off the portal request path with bounded background workers and pollable session status. (#848)- **Code-branch merges no longer start deployment jobs.** `deploy.yml` now leaves
  deploy routing disabled for pull requests and pushes to `dev` or `main`; AWS/GCP
  deployment still runs from `aws-dev`, `gcp-dev`, or deliberate manual dispatch. (#892)- Pushes to AWS environment branches that change only portal application code (`shifter/shifter_platform/**`, `cyberscript`, `installation`) now build the portal image, update the SSM image-tag parameter, and converge the running fleet again. Terraform plan/apply still runs only for Terraform-relevant changes, and docs-only pushes still deploy nothing. (#913)- **Deploy verification now fails loud instead of reporting a false-green deploy.** The Guacamole stabilization wait fails the run on timeout instead of warning and exiting 0 (a broken `guacd` image no longer passes silently), and the engine ECS deploy fails when the task-definition family cannot be described instead of skipping forever on a typo'd family name. A genuine first-ever deploy to a fresh AWS environment can still skip the engine task-family check via the new strict-default `aws_first_deploy` manual-dispatch input. A new `deploy-verification-fail-loud` ADR guard check (ADR-003-R3) keeps the invariant from regressing. (#914)- ### Fixed

  - Derive AWS portal deployment mode from Terraform state, fail loud on topology drift, and document event-sized portal capacity as a deployment-secret overlay. (#915)- **AWS deploy workflows now queue Terraform applies and execute local saved plans.** Env-branch deploys no longer cancel an in-flight apply, core/range/platform Terraform operations wait on the backend lock, and apply jobs create and consume the exact local `tfplan` they apply instead of running a fresh unplanned apply. (#917)- Prevent AWS portal deploys from racing Django migrations across multi-instance boot by running a single deploy-owned migration before runtime containers start with boot migrations disabled. (#918)- **Portal readiness now checks Redis when Channels is Redis-backed, while ASG
  instance replacement health uses EC2 status checks instead of ALB readiness.**
  Shared DB/cache/Redis blips can still remove a target from ALB routing, but no
  longer cause ASG instance churn. (#919)- Portal WebSocket connections (terminal SSH sessions, range-status and notification sockets) now work in the production container image. The Gunicorn/Uvicorn ASGI workers were missing a WebSocket protocol backend, so the built image rejected every WebSocket upgrade (falling through to a 301) while `/health` still returned 200 — a container-only regression the new built-image stack smoke catches. (#922)- **AWS single-instance portal deploy logic is now a tracked, tested script.** The reusable platform workflow sends `scripts/portal-deploy/deploy_portal.sh` through SSM instead of carrying the instance deploy body as an inline heredoc, with subprocess tests covering its argument validation and repeatable worker-health installation. (#925)- **Agent workflow instructions now pin Shifter GitHub operations to
  `Brad-Edwards/shifter`.** Repo-local instructions and Ground Control plan
  rules identify `.ground-control.yaml` as the canonical source for GitHub
  issue, PR, CI, and traceability targets, and ADR guard now treats Ground
  Control config files as documented guardrail surfaces. (#976)- AWS platform pull-request planning now ignores Python-only application changes while still running Quality, and platform Terraform plans wait briefly for state locks instead of failing immediately. (#1176)- **GCP job-launching workloads now explicitly mount Kubernetes service account tokens.** The portal and engine worker pods can authenticate to create provisioner Jobs in-cluster while non-launching workloads remain tokenless. (#1184)- **Shifter Engine deploys no longer drop the ECS task definition's `volumes` block.** The `Update ECS task definition` step in `_shifter-engine.yml` re-registered the definition by cherry-picking individual fields, which silently discarded `volumes` once Terraform added them (#1103) — every deploy failed with `Unknown volume 'provisioner-workspace'`. The step now re-registers the whole definition with only the read-only fields stripped, so `volumes`, `mountPoints`, `runtimePlatform`, and `ephemeralStorage` carry forward verbatim. (#1244)- **AWS platform deploys now render real per-deployment configuration instead of the committed `example.com` baseline.** `_shifter-platform.yml`'s `plan` and `apply` jobs render a gitignored `local.auto.tfvars` from the `TF_VARS_<ENV>_PORTAL` GitHub secret before Terraform runs — previously every AWS platform deploy planned and applied the intentionally-broken OSS example baseline because only the GCP workflow had the render step. The secret is selected strictly on the target environment (no fall-through to the other environment's payload) and the step fails loud when it is unset. An `adr_guard` check (`aws-platform-renders-deploy-tfvars`, ADR-011-R7) regression-protects the render step. (#1249)- **The post-apply RDS pending-modifications check no longer fails AWS platform deploys with spurious "RDS instance not found" errors.** The `db_instance_id` Terraform outputs for the portal and Guacamole RDS instances were emitting `aws_db_instance.id`, which became the `DbiResourceId` (`db-XXXX`) under the AWS provider v6 bump; the check resolves instances by `DBInstanceIdentifier`. Both outputs now emit `aws_db_instance.identifier`. (#1252)- Form inputs and interactive controls across the CTF, scenario editor, mission control, and risk register UIs now have associated visible labels, improving screen-reader and voice-control accessibility. (#1256)## [3.101.5] - 2026-05-10

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

- **Polaris bedrock model** switched from `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
  (deprecated, unsubscribable) to `us.anthropic.claude-sonnet-4-6` across the engine,
  packer scripts, and local-dev `config-claude.sh`. Sonnet 4.5 was returning
  `AccessDeniedException` on every invoke for the dev account.
- **Removed claude smoke-test gate from `polaris_kali_bedrock_shard`**. The step
  still writes `/etc/profile.d/claude-bedrock.sh`, the `/etc/hosts` VPCE override,
  and resolves the bedrock-runtime private IP — but no longer runs
  `claude -p "ok"` as a 60s provisioning gate. Aligns with how every other
  scenario handles claude (no per-range smoke test).
- **In-browser terminal copy/paste**. xterm.js shows selection highlighting but
  never wired the system clipboard. Added a custom key handler:
  Ctrl+Shift+C copies the current selection via `navigator.clipboard.writeText`,
  Ctrl+Shift+V pastes via the existing `sendInput`. Both fall through silently
  on permission denial.
- **Polaris CTFd content trimmed to 5-mission event scope.** Index, mission-log,
  surfaces, and getting-unstuck pages no longer reference Missions 6–9 (Exposure,
  Counterintel, Delivery Denied, Safety Case) — those are CTFd-board-only and
  have no compose backing. Also removed Palo + Ottawa BSides Discord references
  (`discord.gg/N7S2ChA9`); event uses in-room support instead. The "Start Here"
  bullet on the orientation page is now a real link to `/challenges`.
- **Polaris briefing deck (`scenario-dev/polaris/briefing-deck/`)** trimmed
  to 5 missions; Board Access slide updated to reflect the per-cohort
  credential pattern (username = email, single shared password) instead of
  the BSides `meetup+N` convention; range-access slide replaced with a
  Mission-Control-flow instruction set instead of a stale 110-token grid.
- **Dev guacamole DB instance class** bumped from `db.t3.small` to
  `db.m5.xlarge` (`platform/terraform/environments/dev/portal/terraform.tfvars`).
  The t3.small was undersized at BSides Ottawa — sessions took 4–5 retries
  under sustained load. m5.xlarge gives 4 vCPU / 16 GiB and no burst-credit
  cliff. Note: rds module's `apply_immediately` defaults to false, so the
  class change is queued behind RDS's next maintenance window.

## [3.96.0] - 2026-05-07

### Added

- **`polaris_kali_bedrock_shard` step in `PolarisRangeBootstrapPlan`**
  (`shifter/engine/provisioner/plans/polaris_range_bootstrap.py`).
  Per-range step that resolves the bedrock-runtime VPC endpoint's
  private IP, writes `/etc/profile.d/claude-bedrock.sh` inside the
  a14-kali container with `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION`,
  `ANTHROPIC_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL`, drops a
  `/etc/hosts` override pointing the bedrock-runtime FQDN at the VPCE
  IP, and runs a `claude -p "reply ok"` smoke test. Without this step
  the kali container had no AWS credentials and `claude` failed with
  "Not logged in" because the container ships with no creds and on a
  default docker bridge network can't reach IMDS at `169.254.169.254`
  through the host. At BSides Ottawa this was a manual post-provision
  step (`scripts/polaris-aws-range/apply_kali_bedrock_shard.py`)
  operators ran by hand for every participant; integrating it into
  the bootstrap plan makes provisioning self-sufficient.
- **IMDS hop-limit bump in `_run_polaris_range_bootstrap`**
  (`shifter/engine/provisioner/main.py`). Calls
  `ec2.modify_instance_metadata_options(HttpPutResponseHopLimit=2)`
  on the polaris-vm before running the bootstrap plan. Default IMDS
  hop limit is 1, which blocks docker-bridge containers from reaching
  the link-local IMDS endpoint and makes the kali container unable to
  pick up the EC2 instance role's credentials. Hop limit 2 lets the
  container hop through the host network namespace to IMDS. Idempotent.
- **`Set-DnsServerForwarder 169.254.169.253` in
  `scripts/polaris-aws-range/a2_setup.ps1`.** Future polaris-dc bakes
  pick up the DNS forwarder at bake time so a fresh DC AMI launched
  into a non-default VPC can resolve external names (specifically
  `ssm.us-east-2.amazonaws.com`) without needing a post-launch fixup.
  Without this the DC's local DNS server has no upstream and the SSM
  agent never registers, so the engine provisioner times out waiting
  for SSM and tears the range down.

### Fixed

- **Engine DC SSM-wait timeout 600s → 1800s** (`_run_dc_setup` in
  `shifter/engine/provisioner/main.py`). The Packer-built shifter-dc
  AMI runs through 2-3 sysprep reboot cycles on first boot before
  SSM agent is reliably online — empirically 13-15 minutes between
  launch and stable SSM. The 600s ceiling caused the provisioner to
  give up early and tear ranges down. 1800s gives sysprep room; on
  a warm DC AMI the wait still returns in seconds.
- **Bucket name mismatch in `polaris_range_bootstrap.py`'s
  `polaris_fetch_tests` step.** `BUCKET="shifter-dev-user-storage-e3462f0c"`
  is the dev bucket from a previous AWS account. This account uses
  `shifter-dev-user-storage-<redacted-account-id>`, so range provisioning got
  403 on `s3://shifter-dev-user-storage-e3462f0c/polaris/tests/...`
  and the engine marked the range failed even though everything else
  had succeeded. Updated to the correct bucket; matches the
  `agent_s3_bucket` value already corrected in
  `platform/terraform/environments/dev/range/terraform.tfvars`.
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

- **Lint failures surfaced by ruff 0.15 upgrade in 3.95.0.** Pre-commit
  only lints staged files, so these pre-existing violations didn't
  surface until CI ran ruff over the whole tree on the first
  `aws-dev` deploy attempt.
  - `UP042` × 18 across `shifter/shifter_platform/ctf/enums.py`,
    `shifter/shifter_platform/cms/experiments/schemas.py`, and
    `shifter/cyberscript/enums.py`: rewrote `class Foo(str, Enum)` to
    `class Foo(StrEnum)`. Runtime semantics preserved on Python 3.12+
    (StrEnum members are still `str` subclasses; `MyEnum.FOO == "foo"`
    still evaluates True).
  - `E501` × 1 in `shifter/engine/provisioner/plans/polaris_range_bootstrap.py:219`:
    broke the inline `python3 -c '…'` invocation onto its own
    multi-line shell variable so the surrounding `docker exec` line
    stays under 120 chars without changing runtime behaviour.

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
- **Terraform AWS provider major bump** `~> 5.0` → `~> 6.0` across all
  17 root configurations and provisioner modules. The 16 `modules/*`
  subdirectories had already moved to aws 6.x via looser constraints;
  this aligns the consumers (`environments/{dev,prod}`,
  `global/{iam,github-runner,se-admins,tssummit,tssummit-ranges,
  ctfd-workshop,dev-box}`, `scripts/polaris-aws-range/`,
  `temp/ngfw-bootstrap-test/`) so everything resolves to **aws 6.43.0**.
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
- **`.terraform.lock.hcl` files now tracked in git** (was ignored by
  the root `.gitignore` plus two nested `.gitignore` files in
  `platform/terraform/global/dev-box/` and
  `scripts/polaris-aws-range/`). All 30 lock files committed at
  aws 6.43.0; the `temp/` tree remains intentionally excluded.
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

- **`polaris` cyberscript scenario** (`shifter_platform/cms/scenarios/templates/polaris.yaml`).
  Two-instance POLARIS range (polaris-vm host + Windows DC) that drives
  the full 38-flag BOREAS.LOCAL CTF through the production
  `cms.services.create_range` → `engine.services.create_range` → ECS
  Fargate provisioner path, replacing the one-shot
  `scripts/polaris-aws-range/` terraform. Pins `instance_type: m5.2xlarge`
  on the polaris-vm kali instance so the 17-container docker compose
  stack (Kali XFCE + xrdp + BIND + AD tools) gets the headroom it needs
  instead of falling back to the provisioner's `KALI_INSTANCE_TYPE=t3.large`
  global default.
- **Per-instance `instance_type` scenario override.** Additive field on
  `cms.scenarios.schema.InstanceConfig` and `cyberscript.schemas.range.InstanceSpec`;
  the provisioner's `build_tf_vars` (`shifter/engine/provisioner/main.py`)
  now honours a per-instance `instance_type` when set, falling back to
  the existing role/os-based env-var defaults otherwise. Every existing
  scenario yaml is unaffected (field is optional, default `None`).
- **`PolarisRangeBootstrapPlan`** (`shifter/engine/provisioner/plans/polaris_range_bootstrap.py`).
  Runs after LinuxBootstrapPlan on the polaris-vm host via SSM:
  rewrites `docker-compose.override.yml` with the range's actual DC IP
  and the per-instance kali SSH public key, force-recreates the `dns`
  and `a14-kali` containers so their entrypoints pick up the new env
  vars, then fetches the latest `scenario-dev/polaris/tests/` tree from
  `shifter-dev-user-storage-e3462f0c` so the organizer smoketest harness
  is materialised at `/opt/polaris/scenario-dev/polaris/tests/` on every
  freshly provisioned range without requiring an AMI rebake. Verify step
  proves the dns container resolves `dc01.boreas.local` to the range's
  real DC (not the bake-time range-0 IP) and that the a14-kali
  `authorized_keys` is present.
- **`shifter/.dockerignore`.** Excludes local dev cruft (`**/.env`,
  `__pycache__`, `.venv`, `.git`, IDE folders) from the portal image
  build context. Without this the local `shifter_platform/.env` —
  which sets `AWS_ENDPOINT_URL=http://localhost:4566` for LocalStack —
  was getting copied into `/app/.env`, and `settings.py`'s `load_dotenv()`
  poisoned the deployed portal's boto3 clients so every SQS/S3/SNS call
  tried to hit `localhost:4566` and failed.

### Fixed

- **POLARIS A0 smoketest flag 6 Kursk line extraction regression.**
  Commit `0ca1a18c0` added `poppler-utils` to the `a14-kali` Dockerfile,
  which made `pdftotext` available in the container. The A0 smoketest's
  `command -v pdftotext >/dev/null` branch fires first, and pdftotext's
  paragraph-based layout splits "Kursk Heavy Industries - actuator
  assemblies" onto a separate output line from "$12,000,000", so
  `grep -i kursk | head -1` only caught the company name and the check
  failed even though the PDF content is correct. Smoketest now prefers
  `pdf2txt.py` (pdfminer — what the walkthrough tells participants to
  use, and what produces a single-line output), falls back to pdftotext
  with ±3-line grep context so the split layout still correlates. Range
  content unchanged — participants following the walkthrough were never
  affected; only the organizer smoketest harness was.
- **`kali.sh.tpl` and `linux_bootstrap.py CONFIGURE_SSH_SCRIPT` assume
  a `kali` user exists on the host.** On the polaris-vm AMI (Ubuntu with
  the a14-kali docker container publishing SSH, not a real Kali host)
  there is no `kali` system user, so `chown -R kali:kali /home/kali/.ssh`
  and `systemctl start xrdp` would abort the bootstrap. Both templates
  now guard with `id $user` / `systemctl list-unit-files xrdp.service`
  presence checks and continue cleanly when the host isn't a real Kali
  box.

## [3.93.0] - 2026-04-13

### Fixed

- **polaris user_data IMDS credential race during cold first boot.**
  When the instance profile attaches but IMDS hasn't finished propagating
  credentials, the first `aws s3 cp` fails with
  `fatal error: Unable to locate credentials` and cloud-init's final
  stage exits non-zero — exactly what we hit on range 1 of the 3-range
  smoke bring-up. `user_data.sh.tpl` now polls `aws sts get-caller-identity`
  up to 30 times (4s spacing = 120s ceiling) before the S3 download, so
  the instance waits out the propagation window instead of failing hard.
- **polaris `dns` container zone file was hard-coded to
  `dc01 → 10.1.100.11`**, which is correct for range 0 but wrong for
  every subsequent range — range 1's kali resolved the AD DC name to
  range 0's DC and would have attacked the wrong forest. BIND zone file
  now has a `__DC01_IP__` placeholder, and the container has a new
  `entrypoint.sh` that `sed`-substitutes `$DC01_IP` (passed from
  `docker-compose.override.yml` via user_data) before exec'ing `named`.
  `user_data.sh.tpl` writes the override with `DC01_IP` set to the
  range's a2 private IP, plumbed through from the `aws_instance.polaris`
  `templatefile()` call via a new `a2_private_ip` per-range input
  (`each.value.a2_ip` in `ranges.tf`).

### Added

- **`scripts/polaris-aws-range/register_ranges_parallel.sh`** — batch
  registers every range in `terraform output range_indices` by pulling
  the per-index polaris instance id + subnet id + subnet cidr + private
  IP from `terraform output -json`, staging `register_range.py` once on
  the portal EC2, and running it per-range with the matching `POLARIS_*`
  env vars. Emits one JSON object per range on stdout
  (`{"attacker_uuid","range_id","range_index","participant_email"}`)
  so follow-up tooling (playwright harness, CTF invite) can consume
  the mapping without re-querying terraform.

## [3.92.0] - 2026-04-13

### Fixed

- **a14-kali xfce4-screensaver auto-lock during idle RDP sessions** —
  `xfce4-screensaver` (and `xfce4-power-manager`) are hard `Depends:` of
  `kali-desktop-xfce`, so `apt purge` is off the table. Instead, the
  Dockerfile now `dpkg-divert`s the two `/etc/xdg/autostart/*.desktop`
  entries and removes the originals, so the screen-locker daemon never
  spawns inside the xrdp session. `xset s off / s noblank / -dpms` is
  baked into both `xsession` and `startwm.sh` as belt-and-suspenders.
  Proven end-to-end on the live polaris VM: dpkg-divert list shows both
  `.desktop -> .distrib` diversions, `ps auxw` shows no
  `xfce4-screensaver` / `xfce4-power-manager` processes, `xset q -display
  :10` reports `timeout: 0`, and a fresh Playwright RDP click lands on a
  fully-rendered Xfce desktop with no unlock prompt.

### Changed

- **`a14-kali` operator SSH key injection moved from a one-shot
  `user_data` `docker exec` into the container entrypoint**, driven by a
  `KALI_AUTHORIZED_KEY` environment variable passed through
  `docker-compose.override.yml`. The old path ran once at first boot and
  silently left the container without an authorized_keys file after any
  `docker compose up -d --force-recreate a14-kali`, which broke the
  portal Terminal UI's SSH path. Now every container start re-asserts
  the key at correct ownership + perms (kali:kali 600).
- **`scripts/polaris-aws-range/` terraform module split into
  `main.tf` + `shared.tf` + `ranges.tf`**. Shared SG + IAM role + instance
  profile live in `shared.tf` as single global resources (one SG name
  per VPC, one IAM role name per account — same permissions every
  range would use anyway). Per-range resources (subnet, route table,
  routes, route-table association, polaris VM, A2 DC) live in
  `ranges.tf` behind `for_each = local.range_subnets`, which derives
  each range's /28 + pinned `.10` / `.11` private IPs from
  `cidrsubnet(var.polaris_cidr_block, 4, tonumber(idx))` and
  `cidrhost(...)`. `var.range_indices` defaults to `["0"]` so the
  single-range smoke still applies unchanged, and N-range deploys are
  just `terraform apply -var 'range_indices=["0","1","2"]'`. Outputs
  reformatted into maps keyed by range index.

### Added

- **`scripts/polaris-aws-range/a2_cold_bootstrap_parallel.sh`** — fan-out
  wrapper that runs one `a2_cold_bootstrap.sh` per A2 instance id in
  parallel, writes a per-instance log under `POLARIS_BOOTSTRAP_LOG_DIR`,
  and emits a success/failure summary + non-zero exit if any child
  fails. Reads targets from the command line OR from
  `terraform output -json range_a2_instance_ids` when called with no
  args. Safe to run N-wide because `a2_cold_bootstrap.sh` is per-instance
  idempotent and every SSM command is scoped to its target id.

## [3.91.0] - 2026-04-13

### Added

- **`scripts/polaris-aws-range/polaris_ctf_setup.py`** — creates an
  ACTIVE `CTFEvent` for `scenario_id=polaris_manual_test` and invites
  one participant through the real
  `ctf.services.participant.invite_participant`, which in turn
  auto-creates the Django User (with `username=email`), adds the user
  to `CTF_PARTICIPANT_GROUP`, and generates the
  `secrets.token_urlsafe(32)` invite token. Emits JSON on stdout with
  event_id, participant_id, and invite_token so the caller can wire
  the range + build the magic-link URL.
- **`scripts/polaris-aws-range/polaris_ctf_attach.py`** — reads
  `POLARIS_CTF_PARTICIPANT_ID` and `POLARIS_CMS_RANGE_INSTANCE_ID` from
  the environment and patches `CTFParticipant.range_instance_id`,
  `range_status="ready"`, and `status=ParticipantStatus.ACTIVE`. Lets
  us hand a participant a range that was registered manually (via
  `register_range.py`) instead of the normal
  `cms.services.create_range` pipeline.
- **`scripts/polaris-aws-range/polaris_ctf_cleanup.py`** —
  hard-deletes the CTFParticipant + CTFEvent + Django User created by
  the smoke test, after soft-destroying the participant's engine
  Range and cms RangeInstance rows so the dashboard doesn't keep a
  stale entry if the email is reused. Matches the explicit
  expectation that smoke-test rows leave no trace behind.
- Proved the full CTF magic-link flow end-to-end in the dev portal:
  `/ctf/register/?token=<t>` → Django login → redirect to
  `mission-control:dashboard` → participant-only nav (CTFd instead of
  Assets/Docs, no Launch-a-Range panel) → Terminal connects to the
  participant's Range 7 Kali → `whoami && hostname && dig +short
  dc01.boreas.local` returns `kali / operator / 10.1.100.11` → RDP
  button opens Guacamole to the same Kali Xfce desktop. Uses the live
  polaris range (`i-00474db099dd5344c` / 10.1.100.10) and the A2 DC
  (`i-0dc2a5a473c5058c6` / 10.1.100.11) from 3.90.0's cold rebuild.

## [3.90.0] - 2026-04-13

### Added

- **`scripts/polaris-aws-range/a2_cold_bootstrap.sh`** — end-to-end
  automation for promoting a fresh Windows Server 2022 EC2 to
  `BOREAS.LOCAL`. Waits for SSM agent, installs AD-Domain-Services +
  DNS via a wrapper that also queues the dc01 rename and registers a
  SYSTEM scheduled task for `a2_setup.ps1`, reboots, retries
  `Install-ADDSForest` on the renamed box, waits for the promotion
  reboot, then re-runs `a2_setup.ps1` idempotently against the live
  DC. Replaces the ad-hoc manual SSM steps that were required after
  `terraform apply` in 3.88.0. The run_powershell_file helper builds
  SSM `send-command` parameters via a python3 heredoc +
  `--cli-input-json file://...`; the previous printf-based
  PowerShell escape dance mangled `$`/`\` and failed at
  Install-ADDSForest with "Unexpected token '\$b'".
- **`scripts/polaris-aws-range/reset.sh`** — force-clean helper that
  bypasses `docker compose down --remove-orphans` (which leaks the
  `a15-ops-eng` container on re-up in compose v2.29) by directly
  `docker rm -f`-ing any `build_*` containers + pruning the
  `build_*` networks before `docker compose up -d`. Idempotent
  against a warm polaris VM.
- **`scripts/polaris-aws-range/user_data.sh.tpl`** now masks the
  shifter-ubuntu base-AMI services that collide with Kali's
  published ports: `ssh`, `xrdp`, `xrdp-sesman`, `apache2`, `smbd`,
  `nmbd`, `mysql`, `vsftpd`. Without this the host sshd holds port
  22 before docker-compose can publish `a14-kali` on the same port,
  so the portal Terminal UI landed on the Ubuntu host instead of
  Kali. Operator access to the VM is SSM Session Manager; host sshd
  is unused.
- **`kali_authorized_key` terraform variable** (`variables.tf`,
  `main.tf`, `user_data.sh.tpl`) — the portal Terminal UI key-auths
  into `a14-kali` as `kali` using a private key stored in Secrets
  Manager. `user_data` now injects the matching public key into
  `/home/kali/.ssh/authorized_keys` after `docker compose up -d`, so
  a cold `terraform destroy` + `apply` cycle no longer needs a
  manual SSM follow-up to re-wire portal terminal access.
- **`register_range.py` accepts `POLARIS_*` environment variables**
  for every per-run parameter (instance id, subnet id, subnet cidr,
  kali private ip, ssh secret ARN, etc.), so the cold-rebuild
  operator path is `docker exec -e POLARIS_KALI_INSTANCE_ID=... -i
  portal python - < register_range.py` — no source edit per cycle.

## [3.89.0] - 2026-04-13

### Fixed

- **rockyou.txt was gzipped on Kali by default.** The flag-17 Kerberoast
  chain in `flags-07-19-front-office.md` runs `john --wordlist=/usr/share/
  wordlists/rockyou.txt --format=krb5tgs` — Kali's default install ships
  only `/usr/share/wordlists/rockyou.txt.gz` (~50 MB compressed vs ~140
  MB decompressed), so the walkthrough command 404s out of the box and
  the participant has to `gunzip -k` first. `a14/Dockerfile` now
  explicitly adds `john`, `wordlists`, `ldap-utils`, `smbclient` to the
  apt install list and runs `gunzip -k /usr/share/wordlists/rockyou.txt.gz`
  at image-build time so the documented path works on first try.
- **A16 missing `strings` / `file` / `xxd`.** Flag 30's GPG chain
  walkthrough says "`strings full_integration_sim.mp4` reveals the
  Simulation ID header" and other lab flags use `strings` for binary
  triage on A16. `a16/Dockerfile` now installs `binutils file xxd` so
  those commands exist on the box.

## [3.88.0] - 2026-04-13

### Added

- **A2 Windows Server 2022 AD DC now deployed in-range.** New terraform
  `aws_instance.a2_dc` launches a stock
  `Windows_Server-2022-English-Full-Base` AMI into the same `10.1.100.0/28`
  polaris subnet at `10.1.100.11`, using the shared instance profile +
  security group. Minimal user-data (`a2_user_data.ps1.tpl`) sets the
  Administrator password, disables Windows Firewall on all profiles, and
  enables RDP; everything AD-specific then runs through SSM RunCommand so
  failures are observable/re-runnable.
- **`scripts/polaris-aws-range/a2_setup.ps1`** — idempotent post-promotion
  PowerShell that creates the POLARIS OUs, 17 domain users (with passwords
  matching the A1 mail / A3 wiki reuse chain), Lab-Access / Project-L /
  Research-Coordination / Engineering-Support / SCADA-Admins /
  Security-Staff groups, nests Project-L under
  `Research-Coordination -> Engineering-Support` for flag 14, pins
  `msDS-SupportedEncryptionTypes=4` (RC4-only) on svc-backup + svc-scada so
  GetUserSPNs returns `$krb5tgs$23$` hashes that `hashcat -m 13100` /
  john's `krb5tgs` format can crack, assigns Replicating Directory Changes
  + Replicating Directory Changes All on svc-backup (flag 17 DCSync chain),
  creates the `\\dc\badgelogs` share (Petrov anomaly CSV with flag 16) and
  the DA-only `\\dc\admin_flag` share (flag 17 pass-the-hash target), and
  sets the Project-L `info` attribute to `FLAG{2f8b4a6c1d9e7053}`.
- **`shifter/development/range/polaris-test-kali`** Secrets Manager entry
  (Windows side) — just a note: the Administrator password
  (`CortexSavesTheDay!`) is hard-coded in the terraform variable
  `a2_administrator_password` because the range is dev-only and the CTF
  narrative depends on participants reading that cleartext from
  walkthrough/shifter portal metadata.

### Fixed

- **POLARIS compose DNS now has recursion + forwarders** (named.conf in
  `scenario-dev/polaris/build/dns/`). Previously `recursion no`, so every
  non-`boreas.local` / non-`boreas-systems.ctf` lookup from inside the
  compose containers returned SERVFAIL — which meant `apt update` inside
  a14-kali (and any other container) could not resolve external archives.
  Recursion is scoped to `172.20.0.0/16 + 127.0.0.1` via `allow-recursion`
  so this server cannot be used as an open resolver from outside the range.
- **`dc01.boreas.local` DNS record.** Zone files in `build/dns/` now point
  at `10.1.100.11` (the new in-range A2 EC2) instead of the legacy
  `10.100.0.4` external-GCP-VM placeholder. `00-range-access-docker.md`,
  `flags-07-19-front-office.md`, `isolation-smoketest.sh`, and
  `A2-smoketest.sh` all updated to match.
- **a14-kali PDF extraction tools.** `a14/Dockerfile` now installs
  `poppler-utils` + `python3-pdfminer` at image-build time AND drops a
  `/etc/profile.d/polaris-tools.sh` that puts `/opt/tools/bin` on PATH for
  interactive SSH / `docker exec` login shells. Previous a14 image had
  `pdfminer.six` installed inside `/opt/tools/` but `pdf2txt.py` was not on
  PATH in login shells (the `ENV PATH=` line in the Dockerfile only
  affects the PID 1 environment), so the flags 1/8/9/13/19 PDF-extraction
  steps documented in the walkthroughs silently fell back to a hand-rolled
  ASCII85+Flate decoder. Symlinks `/usr/local/bin/pdf2txt.py` and
  `/usr/local/bin/impacket-smbclient.py` added for stability.
- **Flag 15 walkthrough wording** (`flags-07-19-front-office.md`) — now
  explicitly says Kowalski's "creds backup" email is in **INBOX** (he sent
  to his own address; Dovecot has no Sent folder for that user). Previous
  "(Kowalski sent it to himself)" parenthetical was ambiguous and led at
  least one walkthrough-runner to check a non-existent Sent folder first.
- **Flag 31 walkthrough path** (`flags-31-36-bunker.md`) — the
  pre-populated `/root/scan_results.txt` short-circuit is now the primary
  step; the live `nmap -sV -p 502,9100 172.20.50.0/24` is documented as
  the fallback because the service-version probe is slow over the splice
  pivot and can time out under automation.

## [3.87.0] - 2026-04-13

### Added

- **`scripts/polaris-aws-range/`** — terraform + bootstrap for a one-VM
  manual POLARIS range inside the existing dev range VPC. Creates a new
  `/28` subnet (`10.1.100.0/28`) with a dedicated route table that
  bypasses the domain-filtered Network Firewall (so `docker build` and
  `apt install` can reach the internet during bake), one `m5.2xlarge`
  Ubuntu instance, a permissive SG allowing VPC-internal + portal-peering
  ingress on 22/3389, and an instance profile that can read the polaris
  build tarball + SSM session manager.
- **`scripts/polaris-aws-range/user_data.sh.tpl`** — cloud-init bootstrap
  that installs Docker + the v2 compose plugin binary, masks host `ssh`
  / `apache2` / `smbd` / `vsftpd` / `xrdp` / `mysql` services (the
  `shifter-ubuntu-*` base AMI ships them pre-installed and they compete
  for the ports we need to publish from the Kali container), pulls the
  polaris build tarball from S3, writes a `docker-compose.override.yml`
  that publishes a14-kali's 22 + 3389 to the host, runs
  `docker compose up -d`, and starts everything under a systemd unit.
- **`scripts/polaris-aws-range/register_range.py`** — idempotent manual
  range registration script: fetches DB + Django + Cognito secrets from
  Secrets Manager, soft-destroys any stale ready-range rows for the dev
  user, and creates engine `Range` + cms `RangeInstance` rows pointing at
  the polaris VM with an attacker (kali) instance spec. Runs inside the
  portal docker container via SSM Run Command so no portal code change
  is needed to turn a hand-built range into a portal-visible one.
- **S3 bucket** `shifter-polaris-bake-<redacted-account-id>` — byte-stable
  `polaris/build-v1.tar.gz` of the `scenario-dev/polaris/build/` tree
  (includes `_shared/` GPG chain and research-analyst keypair so flag 30
  stays deterministic across rebuilds).
- **Secrets Manager entry** `shifter/development/range/polaris-test-kali`
  holds the RSA private key the portal SSHes with. Secret ARN matches
  the `shifter/*/range/*` wildcard the `dev-portal-ec2-role` already
  allowlists — no IAM policy change required.

## [3.86.0] - 2026-04-12

### Fixed

- **Flag 37 walkthrough payload** — the documented sudo-arg-injection
  example `--host "x; cat /root/.scada/hmi.json"` did not actually
  work because `scada_diag.sh` `eval`s `curl -sS http://$HOST:8080/ping`
  — so without a trailing comment the injection expands into
  `cat /root/.scada/hmi.json:8080/ping` and `cat` errors on the
  concatenated filename. Walkthrough now shows the working form with
  the trailing `#` that comments out the `:8080/ping` suffix.
- **A9 nmap service-detection** — `nmap -sV -p 502,9100 172.20.50.0/24`
  in flag 31 step 1 failed with `could not locate nse_main.lua`
  because the alpine `nmap` package doesn't ship the NSE data files
  as a dependency. A9 Dockerfile now adds `nmap-scripts` alongside
  `nmap`, so `-sV` runs cleanly. Pre-populated `/root/scan_results.txt`
  remains as the sanctioned alternative.
- **Flag 30 step 2 (`gpg-agent.conf` read)** — walkthrough previously
  said `cat /home/e.vasik/.gnupg/gpg-agent.conf` without naming an
  account. `~e.vasik/.gnupg/` is mode 700, so the A16 `research-analyst`
  key cannot read it. Walkthrough now explicitly pivots to A6 as
  `e.vasik` (`Reactor#Core9`, discoverable from the A1 mailbox trail)
  for that hop.
- **Flag 26 openpyxl host** — walkthrough previously said "in Python:
  openpyxl → check sheet_state" without specifying where Python runs.
  A16 does not ship openpyxl; A6 does. Walkthrough now explicitly says
  run the Python snippet from inside the SSH session on A6 as
  `p.nielsen` (where `python3-openpyxl` is preinstalled), with a note
  that `scp`-ing the xlsx back to Kali is the fallback if the tester
  prefers to parse locally.

### Changed

- **A7 Gitea stripped from the `shared` network — lab-only.** Previously
  A7 was multi-homed on `shared` + `lab`, letting Kali reach Gitea
  directly and bypass the Lab pivot for flags 24 and 29. A7 now only
  lives on `lab` (172.20.30.20); every Gitea interaction must go
  through the A16 research-analyst pivot, matching every other Lab
  asset. `docker-compose.yml`, DNS zone files
  (`dns/db.boreas.local`, `dns/db.boreas-systems.ctf` both now resolve
  `git.boreas.local` → 172.20.30.20), walkthrough flag 24/29/30 steps,
  bunker walkthrough prerequisites (bunker flags now explicitly
  require A7 content to have been cloned earlier during the Lab
  phase, since A9 and Kali cannot reach A7), `00-range-access-docker.md`
  reachability table, and `isolation-smoketest.sh` all updated.
- **A16 Dockerfile** gains `git`, `curl`, and `gnupg` so it can run the
  full A7 cloning + flag 30 GPG decrypt chain as the on-ramp container.
  `run-all-smoketests.sh` now routes the A7 smoketest through
  `a16-research-analyst` instead of `a14-kali`.
- **A14 smoketest** no longer asserts A7 Gitea is directly reachable
  from Kali (that's a design-forbidden path now); it asserts A15,
  A16, and the splice-link to A9 instead.
- **Fixed the Gitea anonymous-clone false-negative** in
  `A7-smoketest.sh`: the previous "anonymous clone of private repo
  should fail" assertion was being evaluated from `a14-kali` which had
  cached credentials in its filesystem — moving the runner to the
  freshly-built `a16-research-analyst` container makes the anonymous
  clone actually anonymous, so the hygiene check passes correctly.

### Proofs

- **Full smoketest sweep**: 18 / 18 asset sweeps PASS (including A7
  now), isolation smoketest 90 / 90 boundary assertions PASS.
- **Lab full E2E via A16**: all 12 Lab flags (38 + 20–30) recovered
  end-to-end from inside a14-kali, pivoting only via the real
  participant chain `SSH p.shah@analyst01 → {ssh, psql, git, gpg}`.
  No docker-exec into any Lab target. Flag 30's full A6 → A8 → A7 →
  gpg-decrypt chain works through A16 including pulling the encrypted
  file from research-analyst on A6, psql as `vasik` (Reactor#Core9)
  for the compartment_b key blob, `.netrc`-authed git clone of
  `aurora/weapons-integration` for the passphrase, and gpg
  `--import` + `--decrypt` all inside Shah's shell on A16.
- **SCADA chain via A15**: flag 37 / 18 / 19 recovered end-to-end via
  `SSH s.ivanov@ops-eng01` → sudo-arg-injection → `hmi.json` loot →
  inline Modbus writes from the A15 shell → critical-failure page.

## [3.85.0] - 2026-04-12

### Added

- **POLARIS CTF range: A15 Ops Engineer Workstation** and **A16 Research
  Data Analyst Workstation** introduced as dedicated Front Office pivot
  hosts, with two new flags (37, 38) that gate the SCADA and Lab chains
  respectively. Total flag count: 36 → 38.
  - A15 (`ops-eng01.boreas.local`, 172.20.10.50 + 172.20.40.20) — Sergei
    Ivanov's workstation. Multi-homed on `corporate` + `scada`. Attack
    chain: OSINT (A0 leadership + A4 HR org_chart) → `Welcome1` default
    password → SSH as `s.ivanov` → `sudo -l` reveals
    `/opt/ops/scada_diag.sh` NOPASSWD → sudo arg-injection exploits the
    unquoted `curl` sink → read root-owned `/root/.scada/hmi.json` which
    contains both `svc-scada / Sc@da#2025!` and **flag 37**
    (`FLAG{5c3e7a9f1b8d4602}`, Hard, 200pts, M3). A15 has `pymodbus`
    preinstalled so flags 18 and 19 execute from inside the A15 shell.
  - A16 (`analyst01.boreas.local`, 172.20.10.60 + 172.20.30.60) — Priya
    Shah's research data analyst workstation. Multi-homed on `corporate`
    + `lab`. Deliberately simpler chain than A15 (no privesc): OSINT
    (A4 HR only, NOT A0) → `Welcome1` default → SSH as `p.shah` → read
    `~/.reports/ANALYST_TOKEN` for **flag 38**
    (`FLAG{8b2d4f1a0c5e7396}`, Medium, 100pts, M2). Home dir also
    carries `~/.pgpass` (lab_general), a passphrase-less SSH key +
    `~/.ssh/config` alias for `research-analyst@eng-ws01.boreas.local`
    on A6, and an example `daily_integration_report.py`.
  - New `research-analyst` read-only posix account on A6 (key-only
    auth; public key pre-generated at `_shared/research-analyst-key/`
    and COPY'd into A6 during image build). Can read `/opt/builds/`,
    `/home/r.tanaka/simulations/standard/`, and `/tmp/.deleted/`.
    **Cannot** read `/home/r.tanaka/simulations/midnight/`,
    `/home/p.nielsen/designs/`, or `/home/jenkins/.credentials` (now
    chmod 600). Flags 25, 26, 28 still require independent
    nielsen/tanaka cred discovery; flag 20 still requires jenkins.
- **New smoketests**: `tests/smoketests/A15-smoketest.sh` walks the
  flag 37 compromise chain from inside `a14-kali`, validates the
  sudo-arg-injection root path, extracts the hmi.json loot, and
  proves A15 → `scada-gw` HMI + Modbus reachability.
  `tests/smoketests/A16-smoketest.sh` walks the flag 38 chain, then
  validates A16 → A8 psql and A16 → A6 `research-analyst` SSH pivots
  plus the read/no-read scope of the `research-analyst` account.

### Changed

- **A3 intranet reduced to `corporate`-only.** Legacy multi-home onto
  `scada` and `lab` (used as a one-box pivot shortcut) has been
  removed from `docker-compose.yml`. A3 is once again what its
  hostname says: a corporate wiki server. SCADA reach is now A15,
  Lab reach is now A16.
- **`svc-scada` credential single-sourced through A15.** The
  `service_account_vault.pdf` on A4 no longer lists the `svc-scada`
  password in plaintext — the row now points at "held by ops, see
  ivanov" as a breadcrumb. The only participant path to
  `Sc@da#2025!` is the flag 37 privesc chain.
- **A4 org chart updated** to include Sergei Ivanov (Ops Engineer —
  Plant Systems) and Priya Shah (Senior Research Data Analyst). These
  are the HR-share breadcrumbs for A15 + A16 discovery.
- **A1 mail server seeded** with Sergei Ivanov's inbox (HR
  welcome-back reset confirmation + Dariusz thread about the SCADA
  cred cache). `s.ivanov / Welcome1` added to the A1 user list and
  Dovecot passdb.
- **A0 leadership page** adds Sergei Ivanov under a new "Department
  Leads" section; contact page adds a Plant Operations mailto.
- **A6 entrypoint** creates the `research-analyst` user, drops the
  pre-generated public key into its `authorized_keys`, enforces
  `jenkins/.credentials` at mode 600, and makes `/tmp/.deleted/`
  world-traversable for the flag 30 chain.
- **Flags 18 + 19 walkthrough** rewritten to run from inside the A15
  SSH session after flag 37 rather than hand-waving a pivot. All
  Modbus writes, HMI fetches, and maintenance-manual lookups are
  routed through A15 or Kali as appropriate.
- **Flags 20–30 walkthrough** rewritten to use A16 as the Lab
  on-ramp. Each flag section now names its specific SSH/psql target
  and which account is required. Flag 38 section added at the top
  as the Lab entry point.
- **Isolation smoketest** updated for the new topology: A3 no longer
  reaches scada/lab; A15 reaches corporate+scada only; A16 reaches
  corporate+lab only; A14 has permitted reach to A15 + A16 on
  corporate and to A9 via the pre-wired `splice-link`.
- **`run-all-smoketests.sh`** updated to route the A5 smoketest
  through `a15-ops-eng`, and A6/A8 smoketests through
  `a16-research-analyst`, instead of `a3-intranet`. A15 and A16
  smoketests added.
- **Design docs**: new `design/assets/A15-ops-workstation.md` and
  `design/assets/A16-research-analyst.md`. `design/architecture.md`,
  `design/assets/A3-web-app.md`, `design/assets/A5-scada-generator.md`,
  `design/assets/A6-engineering-workstation.md`, and
  `design/shared-constants.md` updated to reflect the new topology,
  flag table (38 total), pivot ownership, and employee credential
  index.

## [3.84.0] - 2026-04-12

### Fixed

- **Walkthroughs brought current to live range state.** The four
  flag-group walkthroughs and the range-access doc came over from
  `shifter-k8s/temp/tests/smoketests/` in the last consolidation
  and had drift from multiple old test environments baked in.
  All corrections:
  - `00-range-access.md` deleted — fully stale, documented the old
    VM-based test environment (localhost ports, loose Python
    processes, `/tmp/*-content/` file paths).
  - `00-range-access-docker.md` — Administrator row updated to say
    "use PTH" with pointer to `smbclient.py -hashes`; Gitea
    `e_vasik` password `TestPass123!` → `Reactor#Core9`;
    credentials table reconciled with actual AD password reuse;
    "Managing the Range" section rewritten to use the new
    `tests/setup.sh` / `tests/reset.sh` / `tests/run-all-smoketests.sh`
    orchestration + `-p range` project naming against the compose
    file at `build/docker-compose.yml`.
  - `flags-01-06-osint.md` flag 2: `org_chart.txt` → `org_chart.pdf`
    with `exiftool`/`pdfinfo` Author extraction; flag 6: quarterly
    and annual reports `.txt` → `.pdf` with `pdftotext`/`pdf2txt.py`
    extraction path.
  - `flags-07-19-front-office.md` flag 16: removed
    `/tmp/badge.csv` parenthetical leftover from the VM env;
    flag 17: rewritten around pass-the-hash (`smbclient.py -hashes`)
    since Administrator's cleartext is random.
  - `flags-20-30-lab.md` flags 24, 29, 30: Gitea password
    `TestPass123!` → AD-pattern passwords (`e_vasik:Reactor#Core9`,
    `d_kowalski:P@ssw0rd123`) with `.netrc` guidance to dodge
    URL-encoding `#`/`@`.
  - `flags-31-36-bunker.md` — every IP reference corrected.
    Bunker network was documented as `172.20.40.x` (wrong,
    that's actually the SCADA network) and controllers as
    `10.10.40.x` (wrong, that's from the VM env). All fixed to
    `172.20.50.x` / hostnames (`tail-ctrl`, `leg-ctrl`,
    `arms-ctrl`, `brain-main`) with `splice-relay` at 172.20.50.5.
    Scan range `10.10.40.0/24` → `172.20.50.0/24`.

- **Build-content IP drift** in parallel with the walkthroughs:
  - `A4-file-share/build_documents.py`: network_diagram.pdf VLAN
    subnets and server_inventory.xlsx per-host IPs switched from
    `10.10.x.x` VM-era IPs to `172.20.x.x` docker network IPs so
    the OSINT content participants find matches what they'll
    actually route to.
  - `A1-mail-server/build_mail.py`: Kowalski's SCADA VLAN ticket
    email `scada-gw.internal (10.10.40.10)` → `(172.20.40.10)`.
  - `A13-brain/server.py`: `subsystems` command output — the
    controller/brain table showing connected hosts — switched
    from `10.10.40.x` to `172.20.50.x`.
  - `A9-splice-landing/modbus_client.py` help text examples and
    `README.txt` relay description: `10.10.40.x` → `172.20.50.x`.
  - `A9-splice-landing/scan_results.txt` (the pre-populated JTF-2
    nmap output participants find on A9): full IP rewrite.

- **a1-mail Roundcube serving at web root.** The Debian roundcube
  package's `/etc/apache2/conf-enabled/roundcube.conf` ships the
  `Alias /roundcube` line commented out, so a fresh install
  serves the Apache default page at `/` with Roundcube
  effectively unreachable. `a1/Dockerfile` now changes the
  default site DocumentRoot to `/var/lib/roundcube/public_html`
  and adds a roundcube-root conf via `a2enconf` so
  `http://mail.boreas.local/` lands directly on the Roundcube
  login page (required by the A1 smoketest and the walkthrough).

### Changed

- **Design doc content-directory paths updated** (approved by
  user). 15 design docs under `design/assets/A*.md` had
  "Content directory: `docs/ctf/mechag/A*-*/`" lines left over
  from before the consolidation. All 15 rewritten to point at
  `scenario-dev/polaris/build/A*-*/`. `benchmark-report.md`
  similarly rewritten (design doc filenames are now at
  `scenario-dev/polaris/design/assets/A*.md` instead of
  `docs/ctf/mechag/A*.md`).

- **`tests/setup.sh` + `tests/reset.sh`** taught about the new
  nested layout: `COMPOSE_FILE` env override with default
  `$RANGE_DIR/build/docker-compose.yml` and legacy flat-layout
  fallback to `$RANGE_DIR/docker-compose.yml`. Project name
  explicitly pinned to `range` via `-p range` so network and
  container names stay stable across layout moves.

### Verified

- Golden rebuild + full sweep against the new nested layout on
  `ctf-range-builder`: **16/16 PASS**, `NORTHSTORM full range: PASS`.
- Final `reset.sh` run leaves a5/a10/a11/a12/a13 in clean
  pre-unlock state for participant use.

## [3.83.0] - 2026-04-12

### Changed

- Consolidated all POLARIS / NORTHSTORM scenario work into
  `scenario-dev/polaris/`. Prior to this, scenario artifacts
  were scattered across `docs/ctf/`, `docs/ctf/mechag/`, and
  a sibling `shifter-k8s/temp/` worktree. New layout:
  - `scenario-dev/polaris/design/` — authoritative spec (source
    of truth): `architecture.md`, `range-diagram.md`,
    `benchmark-report.md`, `shared-constants.md`, plus per-asset
    design docs under `design/assets/`.
  - `scenario-dev/polaris/build/` — `docker-compose.yml`,
    `ctfd-challenges.json`, `dns/`, `a0/`-`a14/` (Dockerfiles +
    runtime configs), and `A0-boreas-website/`-`A14-kali/`
    content dirs (intact to avoid touching Dockerfile COPY paths).
  - `scenario-dev/polaris/tests/` — `setup.sh`, `reset.sh`,
    `run-all-smoketests.sh`, `isolation-smoketest.sh`,
    flattened `smoketests/` (A0-smoketest.sh … A14-smoketest.py),
    and `walkthroughs/` (copied from `shifter-k8s/temp/tests/smoketests/`
    — the four flag-group happy-path guides plus range-access
    prereqs).
  - `scenario-dev/polaris/notes/` — spike notes and
    HANDOFF/BUILD-TODO (copied from `shifter-k8s/temp/`).
  - `scenario-dev/polaris/README.md` — entry point with layout
    map and "getting started" deploy/test commands.
- Moves were `git mv` wherever possible to preserve history.
  Files from `shifter-k8s/` are copies (different repo, no
  shared git history).
- `run-all-smoketests.sh` updated: new variables `SMOKETESTS_DIR`,
  `RESET_SCRIPT`, `ISOLATION_SCRIPT` with sane defaults for the
  new layout and fallback to the old flat layout if detected.
  Per-test paths switched from `<Content-Dir>/smoketest.ext`
  to `A<N>-smoketest.ext` reflecting the flattened tests/smoketests/.
- `docs/ctf/` and `docs/ctf/mechag/` are now empty and removed.

### Known drift (deferred, needs approval per design-is-source-
of-truth rule)

- 15 design docs under `design/assets/A*.md` still reference
  `docs/ctf/mechag/A*-*/` as the "Content directory". Those
  references are now stale — the content dirs moved to
  `scenario-dev/polaris/build/A*-*/`. Paths are semantic per
  feedback_design_is_source_of_truth.md so they need user
  approval before editing the design to match the new layout.

## [3.82.0] - 2026-04-12

### Fixed

- Close out remaining repo path drift for a1, a3, a4, a5. These
  four Dockerfiles still used the old single-context build
  pattern (`COPY server.py`, `COPY build_mail.py`, etc) with
  files that only existed on the range VM via duplication, not
  in the repo. Migrated all four to parent-context builds to
  match a0/a6/a7/a8/a9/a10/a11/a12/a13/a14:
  - `a1/Dockerfile`: COPYs from `A1-mail-server/build_mail.py`
    and `a1/{postfix-main.cf,dovecot-local.conf,entrypoint.sh}`.
  - `a3/Dockerfile`: COPYs from `A3-web-app/server.py`.
  - `a4/Dockerfile`: COPYs from `A4-file-share/build_documents.py`
    and `a4/{smb.conf,entrypoint.sh}`.
  - `a5/Dockerfile`: COPYs from `A5-scada-generator/server.py`.
  - `docker-compose.yml`: a1-mail, a3-intranet, a4-fileshare,
    a5-scada all switched to `context: .` with `dockerfile:
    ./aN/Dockerfile`. All 14 docker-managed services in
    docker-compose.yml now use the parent-context convention
    (dns is self-contained and stays `build: ./dns`).

  Golden rebuild verification: full teardown,
  `docker compose build` from clean, `docker compose up -d`,
  `run-all-smoketests.sh` → 16/16 PASS, final `reset.sh` for
  clean participant state. Range is now reproducible from a
  fresh repo clone for every service.

## [3.81.0] - 2026-04-12

### Added

- `docs/ctf/mechag/setup.sh`: NORTHSTORM range setup orchestrator.
  Runs `docker compose build` + `up -d`, waits for all 15 services
  to report Running, then polls key readiness ports (a7 gitea
  3000, a1 IMAP 143, a3 80, a4 445, a0 80) via a14-kali before
  returning. Single entry point to take a freshly-synced
  `/home/atomik/range/` to a live range.
- `docs/ctf/mechag/reset.sh`: sticky-state reset. Force-recreates
  the five services with one-shot unlock state (a5-scada thermal
  runaway, a10/a11/a12 flag-register unlocks, a13-brain for
  parity), then polls each one's primary port on its own
  container's localhost until the embedded server is actually
  accepting connections. localhost polling avoids the
  cross-network unreachability problem where a single probe
  container couldn't see every docker bridge.
- `docs/ctf/mechag/run-all-smoketests.sh`: full-range test
  sweep orchestrator. Calls reset.sh pre-flight, then copies
  each per-asset smoketest into its designated runner container
  (a14-kali / a3-intranet / a9-splice) in the correct pivot
  order, executes with the correct interpreter (bash / python3 /
  sh), captures per-asset PASS/FAIL, then runs the host-side
  isolation smoketest, and aggregates a final summary. Proven
  deterministic with three consecutive 16/16 PASS runs against
  the live range (15 asset smoketests + isolation sweep = 475
  underlying checks).

### Changed

- VM cleanup pass on `/home/atomik/range/`: removed stale
  file duplicates left over from before the parent-context
  Dockerfile migration. Top-level copies of build-a6-content.sh
  and build-gpg-chain.sh, plus per-asset copies of build
  scripts / server.py / 01-init.sql / bare-repos.tar.gz /
  bootstrap.sh / content files that now live in the A*-
  content directories. `/home/atomik/range/a*/` now contains
  only the Dockerfile and runtime configs.

## [3.80.0] - 2026-04-12

### Added

- `docs/ctf/mechag/isolation-smoketest.sh`: cross-cutting
  network isolation smoketest (70 checks) that validates the
  full NORTHSTORM topology boundary enforcement. Runs from
  the range host. For every (source, target) pair the design
  specifies, tests TCP reachability via `docker exec` +
  python3 sockets. Every designed pivot path proven to work,
  every forbidden path proven to fail. Covers a14-kali
  (shared+corporate), a3-intranet (THE PIVOT: corporate+
  scada+lab), a7-gitea (shared+lab), a1-mail/a4-fileshare
  (corporate only), a6-workstation (lab only), a5-scada
  (scada only), and a9-splice/a13-brain (bunker-ot only).
  Result: 70/70 PASS. The docker bridge topology enforces
  the design boundaries purely by network attachment,
  without iptables ACLs.

## [3.79.0] - 2026-04-12

### Fixed

- A14 Kali repo path drift (last of the A* assets):
  `a14/Dockerfile` COPYs content files from context root but
  they live in `A14-kali/`, and it referenced `modbus_client.py`
  which only exists in `A9-splice-landing/`. Moved `a14-kali`
  compose build context to `.` with `dockerfile: ./a14/Dockerfile`
  and updated all Dockerfile COPY paths. Now builds from a
  fresh repo checkout.

### Added

- `docs/ctf/mechag/A14-kali/smoketest.sh`: A14 attack platform
  readiness smoketest (47 checks). A14 has no flags (it's the
  participant's attack box, not a target) so the smoketest
  verifies the platform is ready for use: home directory
  content (README, mission_brief.pdf/.txt, flag_submit.sh,
  modbus_scan.py, Claude system prompt), kali user and
  sshd/xrdp services running, standard Kali offensive tools
  (nmap, msfconsole, sqlmap, john, hashcat, gobuster, ffuf,
  nc, curl, wget, python3, smbclient), full Impacket suite
  at /opt/tools/bin (GetUserSPNs, secretsdump, psexec,
  smbclient.py, lookupsid), Python libraries (pymodbus,
  impacket, pdfminer.six, openpyxl, pdf2txt.py), Claude Code
  CLI, TCP reachability of all 7 permitted targets (A0, A1,
  A3, A4, A7, A2 via GCP, DNS), internal DNS resolution, and
  AXFR zone transfer returning the _flag TXT record (flag 5
  discovery path).

## [3.78.0] - 2026-04-12

### Fixed

- A13 repo path drift: `a13/Dockerfile` COPYs `server.py`
  from context root. Moved `a13-brain` compose build context
  to parent dir.

### Added

- `docs/ctf/mechag/A13-brain/smoketest.py`: A13 Mecha-Godzilla
  brain end-to-end smoketest (17 checks). Runs from a9-splice.
  Executes the full boss chain: TCP connect on port 9100,
  receive 8-byte binary challenge, derive XOR key via
  `SHA256("AHS-T-00482" + "AHS-L-00483" + "AHS-A-00484")[:8]`
  (from A10/A11/A12 serials), send handshake response,
  authenticate as `vasik` with `BRAIN_AUTH_TOKEN` from A7
  navigation-controller config (not vasik's AD password),
  run `status` and extract flag 35 from the SYSTEM
  AUTHORIZATION TOKEN line, run `schematic` verifying
  LEVIATHAN ASCII art, run `ai status` verifying DORMANT
  state awaiting primary power, reject wrong override code,
  and submit the full override code `7741-MN07-AL42`
  (assembled from A0 registration / A6 MIDNIGHT-7 sim ID /
  A8 assembly log metadata) to extract flag 36 with the
  OPERATION NORTHSTORM COMPLETE seizure message.

## [3.77.0] - 2026-04-12

### Fixed

- A12 repo path drift: `a12/Dockerfile` COPYs `server.py`
  from context root. Moved `a12-arms` compose build context
  to parent dir.

### Added

- `docs/ctf/mechag/A12-arms-controller/smoketest.py`: A12
  arms controller end-to-end smoketest (17 checks). Runs
  from a9-splice. Verifies default register reads (joints,
  actuator force, mode 0=stowed, primary effector status=0
  offline / max=2400 MW / draw=1800 MW, kinetic caliber
  500mm, 12 rounds/mag), flag zero pre-unlock, wrong
  challenge write rejected before diagnostics, diagnostics
  enable via coil 50, rolling nonce appears on input reg 60
  (4-digit), XOR nonce with PO-2847 (cross-zone intel from
  A4), confirmation readback reg 201 = 1, and ASCII decode
  of reg 100-121 matching `FLAG{f0d8b2e6a4c71935}`.

## [3.76.0] - 2026-04-12

### Fixed

- A11 leg controller Modbus server was silently dropping
  response PDUs for any read that spanned the ankle position
  registers. Root cause: `LEFT_JOINTS` and `RIGHT_JOINTS`
  initialised ankle position/target to `-5` (degrees). Modbus
  holding registers are uint16; pymodbus 3.12 refuses to pack
  negative Python ints and fails silently with no response,
  no log entry. Changed init to `[0, 0, 15, 15, 5, 5]`
  (leg straight, ankles neutral). Confirmed A9's earlier
  probes happened to use reads that didn't cross the negative
  offset, which is why this only surfaced under the A11
  smoketest's exhaustive register reads.
- A11 repo path drift: `a11/Dockerfile` COPYs `server.py` from
  context root. Moved `a11-leg` compose build context to
  parent dir.

### Added

- `docs/ctf/mechag/A11-leg-controller/smoketest.py`: A11 leg
  controller end-to-end smoketest (19 checks). Runs from
  inside a9-splice. Verifies default register reads (joints,
  hydraulic pressures, gait mode 0=stationary, step length
  4200mm, cycle 85s, per-leg mass 24000t, max force 200t
  matching PO-2847), flag registers zero pre-unlock, wrong
  sequence rejection, correct gait sequence 0->1->2->0 to
  reg 30 releasing calibration code 4783 on input reg 60,
  challenge write to reg 99 with calibration code, and
  ASCII decode of reg 100-121 matching `FLAG{c7a1e3f9d0b52864}`.

## [3.75.0] - 2026-04-12

### Fixed

- A10 repo path drift: `a10/Dockerfile` COPYs `server.py` from
  context root but the file lives in `A10-tail-controller/`.
  Moved `a10-tail` compose build context to parent dir.

### Added

- `docs/ctf/mechag/A10-tail-controller/smoketest.py`: A10 tail
  controller end-to-end smoketest (13 checks). Runs from inside
  a9-splice (bunker OT entry point). Verifies default register
  reads (motor positions, torque, mode=1 balance, length=120m,
  mass=8500t), flag registers zero pre-unlock, the flag 32
  unlock sequence (write reg 20=3 diagnostic mode, then write
  reg 99=482 serial-derived challenge), ASCII decode of
  registers 100-121 matching `FLAG{9b3e7c1d0f5a2846}`, mode
  reset on wrong challenge, and all 10 motor enable coils ON.
  Device identification test deferred to A9 smoketest which
  already covers A10/A11/A12 via modbus_client.py devid.

## [3.74.0] - 2026-04-12

### Fixed

- A9 repo path drift (same pattern as A6/A7/A8):
  `a9/Dockerfile` COPYs README, scan_results, modbus_client.py
  from context root but they live in `A9-splice-landing/`.
  Moved `a9-splice` docker-compose build context to `.` with
  `dockerfile: ./a9/Dockerfile` so the build works from a
  fresh repo checkout.

### Added

- `docs/ctf/mechag/A9-splice-landing/smoketest.sh`: A9 splice
  landing box end-to-end smoketest (17 checks). Runs from
  inside a9-splice (the only container on bunker-ot so no
  pivot available). Verifies the JTF-2 field relay artifacts
  (README POLARIS FIELD RELAY text, scan_results nmap dump,
  modbus_client.py), the field tool set (python3, nmap,
  ncat, tcpdump, ssh, pymodbus), TCP reachability of all 4
  bunker hosts (A10-A13), Modbus FC 43 device identification
  queries against A10/A11/A12 returning the expected
  ProductName values (AHS-TAIL-7741, AHS-LEG-MN07,
  AHS-ARM-AL42), and the flag 31 concatenation answer string
  `AHS-TAIL-7741AHS-LEG-MN07AHS-ARM-AL42` that CTFd accepts.

## [3.73.0] - 2026-04-12

### Fixed

- A8 repo path drift (same pattern as A6/A7): `a8/Dockerfile`
  COPYs `01-init.sql` from context root but the file lives in
  `A8-research-database/`. Moved `a8-database` docker-compose
  build context to `.` with `dockerfile: ./a8/Dockerfile` so
  the build works from a fresh repo checkout.

### Changed

- `a3/Dockerfile`: added `postgresql-client` so a3-intranet can
  run `psql` against A8 as the designed pivot host (A8 is on
  lab VLAN 30, not reachable from a14-kali directly).

### Added

- `docs/ctf/mechag/A8-research-database/smoketest.sh`: A8
  research database end-to-end smoketest (16 checks). Runs
  from a3-intranet via psql. Verifies lab_general auth via
  A3 /.env discovery path, compartment isolation
  (lab_general denied on compartment_b/c, lab_mfg denied on
  compartment_b), flag 21 in compartment_a.structural_specs
  frame_dorsal_plate row, both flag 27 paths (vasik direct
  via AD password reuse + SECURITY DEFINER SQL injection in
  research_public.search_research as lab_general) with
  verification that the function actually has SECURITY
  DEFINER, flag 28 via JSONB path
  `metadata->'integration'->>'flag'` in compartment_c.assembly_log
  as lab_mfg (A6 .pgpass pivot), A13 override-code piece
  AL42 via `metadata->'integration'->>'code'`, and A6 flag 30
  chain prerequisite (Vasik GPG private key base64 blob in
  compartment_b.key_storage).

## [3.72.0] - 2026-04-12

### Fixed

- A7 Gitea bootstrap drift (design vs build mismatch):
  - `bootstrap.sh` user creation was missing `login_name` in the
    POST payload, so Gitea stored users with empty login_name
    and basic-auth failed ("user's password is invalid"). Added
    `login_name` + `source_id` to the POST, plus a PATCH fallback
    that corrects existing users on re-runs.
  - Gitea user passwords were all hardcoded to `TestPass123!`
    with no discovery path. Updated to match the A1/A2/A6 AD
    credentials (e_vasik/Reactor#Core9, r_tanaka/SimEngine#42,
    p_nielsen/Hydraulics1, m_webb/Welcome1, d_kowalski/P@ssw0rd123)
    so the password-reuse pattern participants discover in the
    Front Office also unlocks Gitea. k_yamamoto and f_okoye
    (Lab-Access members without prior AD mapping) get
    Sensor2025 / AIModel2025 respectively.
- A7 repo path drift: `a7/Dockerfile` COPYs `bootstrap.sh` and
  `bare-repos.tar.gz` but they live in `A7-source-repo/`. Moved
  `a7-gitea` docker-compose build context to `.` with
  `dockerfile: ./a7/Dockerfile` and updated COPY paths so the
  image can be built from a fresh repo checkout.

### Added

- `docs/ctf/mechag/A7-source-repo/smoketest.sh`: A7 end-to-end
  smoketest (20 checks) runnable from a14-kali (A7 is
  multi-homed on shared+lab so a14-kali reaches it directly via
  shared). Verifies Gitea API, public org/repo discovery,
  visibility boundaries (anonymous cannot see `aurora` org or
  its repos; anonymous cannot clone private repos), authenticated
  clone of all 4 aurora repos, flag 24 via `git log -p` on
  navigation-controller removed CI token, flag 29 via
  `git show <parent>:schematic.svg` recovery on leviathan-assembly,
  LEGACY_PASSPHRASE cross-asset breadcrumb for A6 flag 30 in
  weapons-integration/src/crypto_config.py, deploy_combat_ai.yml
  playbook in manufacturing-orchestrator, and password-reuse
  validation for r_tanaka and p_nielsen.

## [3.71.0] - 2026-04-12

### Fixed

- A6 repo drift: `build-a6-content.sh` and `build-gpg-chain.sh`
  existed on the range VM but were never committed to the repo,
  so `a6/Dockerfile` could not build from a fresh clone. Added
  both scripts to `A6-engineering-workstation/` alongside
  `build_cog_xlsx.py`, moved `a6-workstation` docker-compose
  build context to `.` with `dockerfile: ./a6/Dockerfile`, and
  updated the Dockerfile COPY paths so it can reach both the
  build dir (`a6/`) and the content dir
  (`A6-engineering-workstation/`) at build time. Rebuilt and
  recreated a6-workstation on the range successfully.

### Changed

- `a3/Dockerfile`: added `openssh-client`, `sshpass`, and
  `ca-certificates` so a3-intranet functions as a realistic
  post-compromise pivot host. This is the only practical path
  for a14-kali to reach the Lab VLAN (30) and SCADA VLAN (40)
  per the design (A3 is the only asset multi-homed to all
  three). Rebuilt and recreated a3-intranet.

### Added

- `docs/ctf/mechag/A6-engineering-workstation/smoketest.sh`:
  A6 engineering workstation end-to-end smoketest (22 checks).
  Runs from inside a3-intranet and uses SSH pivot to reach
  eng-ws01.boreas.local on lab VLAN 30. Verifies jenkins /
  r.tanaka / p.nielsen logins, flag 20 in jenkins .credentials,
  flag 22 in /opt/builds/latest/reactor_interface_spec, flag 23
  as string in stress_test_44.dat binary (with bipedal
  cross-references in logs 28/31/44), flag 25 in
  MIDNIGHT-7_results.dat plus MN07-INTEG-20251028 simulation
  ID (A13 override code piece), flag 26 in the hidden
  Integration sheet of center_of_gravity_analysis.xlsx
  extracted via stdlib `zipfile`, restricted perms on
  r.tanaka/simulations/midnight and p.nielsen/designs,
  p.nielsen .pgpass A8 cred breadcrumb, flag 30 prerequisites
  (encrypted file + public key + gpg-agent.conf hint), and
  simulation.log narrative content. Flag 30's full decryption
  chain requires A7 passphrase + A8 private key blob so it's
  deferred to the cross-asset verification task.

## [3.70.0] - 2026-04-12

### Added

- `docs/ctf/mechag/A5-scada-generator/smoketest.py`: A5 SCADA
  generator HMI + Modbus PLC end-to-end smoketest (19 checks).
  Runs from inside a3-intranet (the multi-homed corporate+scada
  pivot — A14 cannot reach A5 directly per design). Uses only
  stdlib (socket + urllib) so it needs no pymodbus install in
  the container. Verifies: flag 18 in dashboard footer;
  architecture page reveals Modbus port 502 / HR 100 interlock
  / HR 200 maintenance key; system logs contain D. Kowalski
  sensor drift incident; `svc-scada` / `Sc@da#2025!` auth gated
  on /control with wrong-password rejection; raw Modbus TCP
  reads the register map; wrong maintenance key to HR 200 is
  rejected; correct key 7734 bypasses HR 100 interlock and
  disables thermal safety; fuel=100 + cooling=0 triggers
  thermal runaway; flag 19 on the destroyed CRITICAL page.
  Test is idempotent for destroyed containers (extracts flags
  from the final page) but requires a fresh a5-scada container
  to re-prove the attack chain.

## [3.69.0] - 2026-04-12

### Added

- `docs/ctf/mechag/A4-file-share/smoketest.sh`: A4 file share
  end-to-end smoketest (33 checks). Exercises every share ACL and
  every flag path from the a14-kali container: anonymous read of
  Public share and flag 11 from `cafeteria_menu_april.pdf` PDF
  Author metadata; authenticated read of HR as `v.harlan` with
  flag 9 on page 2 of `chen_james_termination.pdf` Case Reference
  Number field; Procurement read with PO-2847 "Special
  Instructions" cross-reference followed into
  `specs/actuator_requirements_v4.pdf` for flag 13; IT share
  anonymous-deny plus `svc-fileshare` (A1 Kowalski creds pivot)
  authenticated read of `backup_verification.log` for flag 15;
  Executive share read. Verifies design-specified share contents
  (network_diagram, server_inventory, PO-3102/3455, reactor
  invoice, org chart, Chen NDA, board minutes, budget summary).

## [3.68.0] - 2026-04-12

### Fixed

- `docs/ctf/mechag/a3/Dockerfile`: create `/var/www/docs` base
  directory with two placeholder files. Without this, both the
  legit `/download?file=*` feature and the design-specified path
  traversal attack (`/download?file=../../../etc/passwd`) failed
  because Python's `os.path.realpath` lexically normalizes `..`
  components on non-existent paths (resolving `/var/www/docs/..`
  to `/var/www` then `/var` etc), so the traversal target
  resolved to `/var/etc/passwd` instead of `/etc/passwd`. Fix
  makes both legit downloads and the intended attack path work.

### Added

- `docs/ctf/mechag/A3-web-app/smoketest.sh`: A3 intranet/wiki
  end-to-end smoketest (24 checks). Verifies public pages,
  username enumeration via `/forgot`, flag 7 in `/.env` and
  `/config.bak` (plus A8 research DB cred breadcrumb),
  admin/admin login, flag 12 in `/wiki/project-coordination`
  HTML comment, all 4 wiki pages, IT KB internal hostnames
  (dc01, scada-gw), LEVIATHAN Assembly Schedule draft visible
  in admin panel with `[MOVED TO SECURE SYSTEM]` body, SQL
  injection via `/search` dumping the users table, and path
  traversal in `/download` reading `/etc/passwd`. Runnable from
  the a14-kali container.

## [3.67.0] - 2026-04-12

### Added

- `docs/ctf/mechag/A1-mail-server/smoketest.py`: A1 end-to-end
  smoketest (27 checks). Exercises IMAP auth for all 6 mailboxes,
  Roundcube webmail login flow, flag 10 retrieval from Kowalski's
  welcome email, flag 8 extraction from Vasik's PDF attachment via
  `pdf2txt.py`, the A4 cred pivot breadcrumb (svc-fileshare /
  F1l3Sh@r3Svc! in Kowalski's "creds backup" email), and every
  narrative thread the design specifies (MIDNIGHT-7, PO-2847,
  Petrov anomaly, Kursk shipment, Novikov reactor). Runnable from
  the a14-kali container.
- `docs/ctf/mechag/A2-domain-controller/smoketest.sh`: A2 Windows
  DC end-to-end smoketest (22 checks). Sweeps AD ports on
  `dc01.boreas.local`, verifies `e.vasik` (A1 password reuse)
  authenticates, Kerberoasts svc-backup via `GetUserSPNs.py`,
  cracks the hash offline with john to `Password1`, DCSyncs the
  Administrator NTLM hash via `secretsdump.py`, pass-the-hashes
  into `\\dc01\admin_flag\` for flag 17, retrieves flag 16 from
  `\\dc01\badgelogs\access_log_march_2026.csv` (Petrov Underground
  Hatch entries), and confirms flag 14 via LDAP `(cn=Project-L)`
  info attribute. Also verifies the Engineering-Support >
  Research-Coordination > Project-L group nesting.

## [3.66.0] - 2026-04-11

### Changed

- A0 Boreas Systems website rebuilt to match `A0-boreas-website.md`
  design spec. Replaces the Flask prototype with `nginx:alpine` serving
  static HTML + reportlab-generated PDFs via a multi-stage build:
  - `a0/Dockerfile` now multi-stage (`python:3.12-slim` content-builder
    feeding `nginx:alpine`), `a0/nginx.conf` added.
  - `docker-compose.yml` a0-website build context moved to `.` with
    `dockerfile: ./a0/Dockerfile` so the image can COPY from both
    `a0/` and `A0-boreas-website/`.
  - `A0-boreas-website/site/`: 14 static HTML pages + CSS (home,
    about, leadership with CSS-gradient avatars, careers,
    careers_apply, contact, news, status, robots.txt, admin/, portal/,
    old/index, old/clients, internal/index).
  - `A0-boreas-website/build_pdfs.py`: reportlab generator for
    org_chart.pdf (flag 2 in Author metadata), boreas-Q1-2025.pdf,
    boreas-Q2-2025.pdf, and boreas-annual-2025.pdf with the Kursk
    Heavy Industries $12,000,000 line buried in 40 expense items.
  - `/internal/` uses a hand-written `index.html` so the annual
    report PDF lives on disk but is not listed — participants must
    fuzz the filename pattern to find it.
  - `A0-boreas-website/smoketest.sh` added — 22-check end-to-end
    attacker-perspective test runnable from the a14-kali container.

### Removed

- `A0-boreas-website/server.py` — obsolete Flask prototype.

## [3.65.0] - 2026-04-11

### Added

- NORTHSTORM CTF range carry-over from the `shifter-k8s` branch onto
  the new `polaris-ctf` branch. Brings in:
  - All 16 mecha-asset build directories under
    `docs/ctf/mechag/{a0..a14,dns}/` (Dockerfiles, entrypoints,
    content, Modbus servers, scenario assets).
  - All 14 design content folders under
    `docs/ctf/mechag/A0-boreas-website/` … `A9-splice-landing/`
    (mission briefs, prepared scripts, fixture data).
  - `docs/ctf/mechag/docker-compose.yml`,
    `ctfd-challenges.json`, `shared-constants.md`.
- A14 Kali container rebuilt against the AWS packer scripts in
  `shifter/packer/scripts/kali/`: `kali-linux-headless` metapackage,
  XFCE + xrdp on 3389, sshd on 22, Claude Code CLI via npm, kali user,
  CTF content overlay under `/home/kali/`. Mission brief generated as
  PDF (`docs/ctf/mechag/A14-kali/mission_brief.pdf`).
- Project DNS sidecar verified end-to-end: AXFR-enabled BIND with
  `boreas-systems.ctf` and `boreas.local` zones, multi-homed onto
  shared/corporate/lab networks.

### Changed

- All 15 mecha asset design docs (`docs/ctf/mechag/A0-…A9-…md`) and
  `docs/ctf/northstorm-architecture.md` updated to match the
  shifter-k8s branch state. A14-kali design no longer specifies
  per-participant rate limiting (false constraint), uses the `kali`
  user (matching the AWS AMI), and documents RDP access in place of
  the ttyd/Guacamole sidecar approach.

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
