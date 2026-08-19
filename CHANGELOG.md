# CHANGELOG

<!-- version list -->

## v2.1.6 (2026-08-19)

### Bug Fixes

- **cli**: Escape error messages so Rich cannot rewrite or crash them
  ([#334](https://github.com/shawnoster/aya/pull/334),
  [`a47815d`](https://github.com/shawnoster/aya/commit/a47815db07ff24b5d7645010c275bcd0d40c9e7a))

- **install**: Make the missing-plugin remedy runnable as written
  ([#333](https://github.com/shawnoster/aya/pull/333),
  [`2cf1f75`](https://github.com/shawnoster/aya/commit/2cf1f757ce94c62dda6b4b1289ffcf558f508967))

- **install**: Resolve the OpenCode plugin source so it can actually install
  ([#333](https://github.com/shawnoster/aya/pull/333),
  [`2cf1f75`](https://github.com/shawnoster/aya/commit/2cf1f757ce94c62dda6b4b1289ffcf558f508967))

- **release**: Read pyproject in binary mode so the locale cannot break the release
  ([#336](https://github.com/shawnoster/aya/pull/336),
  [`ed3f81b`](https://github.com/shawnoster/aya/commit/ed3f81b1170ade64e9e110d8e13ca34f5eebbd0f))

- **release**: Stop the build command installing aya itself
  ([#336](https://github.com/shawnoster/aya/pull/336),
  [`ed3f81b`](https://github.com/shawnoster/aya/commit/ed3f81b1170ade64e9e110d8e13ca34f5eebbd0f))

### Chores

- **aya**: Enable warn_unreachable and delete the dead returns it found
  ([#330](https://github.com/shawnoster/aya/pull/330),
  [`8b16993`](https://github.com/shawnoster/aya/commit/8b16993ca8ac8836015514728db43e7cb1d8d930))

- **aya**: Express the unvalidated-shape guards in the type, not an ignore
  ([#330](https://github.com/shawnoster/aya/pull/330),
  [`8b16993`](https://github.com/shawnoster/aya/commit/8b16993ca8ac8836015514728db43e7cb1d8d930))

- **aya**: Re-lock after the 2.1.5 bump ([#330](https://github.com/shawnoster/aya/pull/330),
  [`8b16993`](https://github.com/shawnoster/aya/commit/8b16993ca8ac8836015514728db43e7cb1d8d930))

- **aya**: Widen watch_target's config local so its guard survives the flag
  ([#330](https://github.com/shawnoster/aya/pull/330),
  [`8b16993`](https://github.com/shawnoster/aya/commit/8b16993ca8ac8836015514728db43e7cb1d8d930))

### Continuous Integration

- Keep uv.lock in sync across releases, and fail loudly when it is not
  ([#332](https://github.com/shawnoster/aya/pull/332),
  [`6bb473e`](https://github.com/shawnoster/aya/commit/6bb473eded6770d89a342af5dd2605b549c66da2))

- Run the lock check before uv sync, and freeze the sync
  ([#332](https://github.com/shawnoster/aya/pull/332),
  [`6bb473e`](https://github.com/shawnoster/aya/commit/6bb473eded6770d89a342af5dd2605b549c66da2))

- **gateway**: Check the lockfile there too ([#332](https://github.com/shawnoster/aya/pull/332),
  [`6bb473e`](https://github.com/shawnoster/aya/commit/6bb473eded6770d89a342af5dd2605b549c66da2))


## v2.1.5 (2026-08-19)

### Bug Fixes

- Address PR #331 review feedback ([#331](https://github.com/shawnoster/aya/pull/331),
  [`c9490cf`](https://github.com/shawnoster/aya/commit/c9490cff4e3e01c4a2bce2093146810a35b7691d))

- **scheduler**: Cover the surface that motivated this, and the sibling markup bug
  ([#331](https://github.com/shawnoster/aya/pull/331),
  [`c9490cf`](https://github.com/shawnoster/aya/commit/c9490cff4e3e01c4a2bce2093146810a35b7691d))

- **scheduler**: Show what a watch is watching ([#331](https://github.com/shawnoster/aya/pull/331),
  [`c9490cf`](https://github.com/shawnoster/aya/commit/c9490cff4e3e01c4a2bce2093146810a35b7691d))

### Chores

- Update uv.lock to reflect aya-ai-assist 2.1.4 ([#331](https://github.com/shawnoster/aya/pull/331),
  [`c9490cf`](https://github.com/shawnoster/aya/commit/c9490cff4e3e01c4a2bce2093146810a35b7691d))


## v2.1.4 (2026-08-19)

### Bug Fixes

- **relay**: Gate the trusted badge on a verified signature
  ([#329](https://github.com/shawnoster/aya/pull/329),
  [`44f4c18`](https://github.com/shawnoster/aya/commit/44f4c18ca0f5c7bf2d6304e55388f79c72b29d7b))

- **relay**: Verify quietly when listing packets
  ([#329](https://github.com/shawnoster/aya/pull/329),
  [`44f4c18`](https://github.com/shawnoster/aya/commit/44f4c18ca0f5c7bf2d6304e55388f79c72b29d7b))

- **relay**: Withhold the peer label from an unauthenticated sender
  ([#329](https://github.com/shawnoster/aya/pull/329),
  [`44f4c18`](https://github.com/shawnoster/aya/commit/44f4c18ca0f5c7bf2d6304e55388f79c72b29d7b))


## v2.1.3 (2026-08-19)

### Bug Fixes

- **install**: Fail closed when the crontab cannot be read
  ([#328](https://github.com/shawnoster/aya/pull/328),
  [`b30bc39`](https://github.com/shawnoster/aya/commit/b30bc393be9ac4a6cc930b504382be3f40e0a341))

### Documentation

- **github**: Rework the PR template around evidence and scope
  ([#327](https://github.com/shawnoster/aya/pull/327),
  [`32d3aaa`](https://github.com/shawnoster/aya/commit/32d3aaa932f9a082cebe75940d5a43aeb13126c9))


## v2.1.2 (2026-08-18)

### Bug Fixes

- **scheduler**: Report crontab state truthfully, and check it
  ([#326](https://github.com/shawnoster/aya/pull/326),
  [`9456dfd`](https://github.com/shawnoster/aya/commit/9456dfd57e51f8dab900eadc9687fd2b52a29927))

- **scheduler**: Stop the suite deleting the crontab, and report its state truthfully
  ([#326](https://github.com/shawnoster/aya/pull/326),
  [`9456dfd`](https://github.com/shawnoster/aya/commit/9456dfd57e51f8dab900eadc9687fd2b52a29927))

- **tests**: Address PR review — loud fixture, real assertions, doc gap
  ([#326](https://github.com/shawnoster/aya/pull/326),
  [`9456dfd`](https://github.com/shawnoster/aya/commit/9456dfd57e51f8dab900eadc9687fd2b52a29927))

- **tests**: Stop the suite deleting the developer's crontab
  ([#326](https://github.com/shawnoster/aya/pull/326),
  [`9456dfd`](https://github.com/shawnoster/aya/commit/9456dfd57e51f8dab900eadc9687fd2b52a29927))

### Refactoring

- **install**: Expose aya_cron_installed, and test the test guard
  ([#326](https://github.com/shawnoster/aya/pull/326),
  [`9456dfd`](https://github.com/shawnoster/aya/commit/9456dfd57e51f8dab900eadc9687fd2b52a29927))


## v2.1.1 (2026-08-18)

### Bug Fixes

- **scheduler**: Deliver tick-ingested alerts through the hook
  ([#325](https://github.com/shawnoster/aya/pull/325),
  [`1a048ef`](https://github.com/shawnoster/aya/commit/1a048ef86d1d24ed01c403a94f5cb0e0249f09f5))


## v2.1.0 (2026-08-18)

### Bug Fixes

- **cli**: Derive the watch dry-run preview from validate_watch
  ([#324](https://github.com/shawnoster/aya/pull/324),
  [`6defc4b`](https://github.com/shawnoster/aya/commit/6defc4b3668e835c639e4e71e833ca45c7ae653c))

- **scheduler**: Stop the relay-inbox alert naming the count twice
  ([#324](https://github.com/shawnoster/aya/pull/324),
  [`6defc4b`](https://github.com/shawnoster/aya/commit/6defc4b3668e835c639e4e71e833ca45c7ae653c))

### Features

- **scheduler**: Add a relay-inbox watch provider
  ([#324](https://github.com/shawnoster/aya/pull/324),
  [`6defc4b`](https://github.com/shawnoster/aya/commit/6defc4b3668e835c639e4e71e833ca45c7ae653c))


## v2.0.3 (2026-08-18)

### Bug Fixes

- **scheduler**: Record poll attempts at all three poll sites
  ([#323](https://github.com/shawnoster/aya/pull/323),
  [`963ab0e`](https://github.com/shawnoster/aya/commit/963ab0e61c3d9ac8c8926001d3153a414375ff32))

- **scheduler**: Show failed polls in the schedule list too
  ([#323](https://github.com/shawnoster/aya/pull/323),
  [`963ab0e`](https://github.com/shawnoster/aya/commit/963ab0e61c3d9ac8c8926001d3153a414375ff32))

- **scheduler**: Stop a failing watch from spinning silently
  ([#323](https://github.com/shawnoster/aya/pull/323),
  [`963ab0e`](https://github.com/shawnoster/aya/commit/963ab0e61c3d9ac8c8926001d3153a414375ff32))

### Chores

- **deps**: Bump astral-sh/setup-uv from 9.0.0 to 10.0.1
  ([#320](https://github.com/shawnoster/aya/pull/320),
  [`1dfb7a6`](https://github.com/shawnoster/aya/commit/1dfb7a67ee58fd6ed3d0d837b621e8371721f705))

- **deps-dev**: Bump ruff from 0.16.2 to 0.16.3 ([#321](https://github.com/shawnoster/aya/pull/321),
  [`fb14072`](https://github.com/shawnoster/aya/commit/fb140729be6c603e88724e165bc38bab47b9d736))


## v2.0.2 (2026-08-17)

### Bug Fixes

- **scheduler**: Make ci-checks watches actually poll
  ([#322](https://github.com/shawnoster/aya/pull/322),
  [`d124ea1`](https://github.com/shawnoster/aya/commit/d124ea173580027c74bc34c9b9c61dccb77db2d3))

- **scheduler**: State the gh contract without narrating the bug
  ([#322](https://github.com/shawnoster/aya/pull/322),
  [`d124ea1`](https://github.com/shawnoster/aya/commit/d124ea173580027c74bc34c9b9c61dccb77db2d3))


## v2.0.1 (2026-08-12)

### Bug Fixes

- **aya**: Stop five handlers swallowing failures, and enable BLE001
  ([#319](https://github.com/shawnoster/aya/pull/319),
  [`ed6df02`](https://github.com/shawnoster/aya/commit/ed6df02418afd3522558e93ad73797b45e07609c))

- **aya**: Validate MCP tool arguments, which mcp 2.0 stopped doing
  ([#318](https://github.com/shawnoster/aya/pull/318),
  [`eb829a9`](https://github.com/shawnoster/aya/commit/eb829a9b0ec4b3b952082bd76870bca7aa67fab8))

### Chores

- **lint**: Add the two guards that cost nothing, decline the four that do not
  ([#318](https://github.com/shawnoster/aya/pull/318),
  [`eb829a9`](https://github.com/shawnoster/aya/commit/eb829a9b0ec4b3b952082bd76870bca7aa67fab8))

- **release**: Hand the changelog to semantic-release, fix the parser deprecation, and upgrade the
  gateway ([#318](https://github.com/shawnoster/aya/pull/318),
  [`eb829a9`](https://github.com/shawnoster/aya/commit/eb829a9b0ec4b3b952082bd76870bca7aa67fab8))

- **release**: Let semantic-release own the changelog, and drop the angular parser
  ([#318](https://github.com/shawnoster/aya/pull/318),
  [`eb829a9`](https://github.com/shawnoster/aya/commit/eb829a9b0ec4b3b952082bd76870bca7aa67fab8))

### Documentation

- **aya**: Fix stale claims, split by audience, and add CONTRIBUTING
  ([#317](https://github.com/shawnoster/aya/pull/317),
  [`0899ba7`](https://github.com/shawnoster/aya/commit/0899ba7e8def3845f36224efe7dee0999791d85c))

- **security**: Fix relay trust description to include interactive confirmation
  ([#317](https://github.com/shawnoster/aya/pull/317),
  [`0899ba7`](https://github.com/shawnoster/aya/commit/0899ba7e8def3845f36224efe7dee0999791d85c))

### Testing

- **aya**: Trim six tests that duplicated or asserted nothing
  ([#316](https://github.com/shawnoster/aya/pull/316),
  [`c944f0f`](https://github.com/shawnoster/aya/commit/c944f0ff38f6d5325034c69ba34667d8ec2f2fa5))


## v2.0.0 (2026-08-11)

### Bug Fixes

- **ci**: Improve token probe and reopen closed release-failure issues
  ([#313](https://github.com/shawnoster/aya/pull/313),
  [`8dee563`](https://github.com/shawnoster/aya/commit/8dee5633dbe4fadf343c99d3796e55318f0d4582))

### Chores

- **deps**: Update all Python dependencies, and migrate to the mcp 2.0 server API
  ([#315](https://github.com/shawnoster/aya/pull/315),
  [`bd0cf2e`](https://github.com/shawnoster/aya/commit/bd0cf2e942f8d4b853852c67f2fee38a7f00a014))

### Continuous Integration

- **release**: Fail legibly on a bad token, and file the failure where it is seen
  ([#313](https://github.com/shawnoster/aya/pull/313),
  [`8dee563`](https://github.com/shawnoster/aya/commit/8dee5633dbe4fadf343c99d3796e55318f0d4582))

### Testing

- **aya**: Drive the MCP stdio transport in CI ([#315](https://github.com/shawnoster/aya/pull/315),
  [`bd0cf2e`](https://github.com/shawnoster/aya/commit/bd0cf2e942f8d4b853852c67f2fee38a7f00a014))


## v1.45.2 (2026-08-11)

### Bug Fixes

- Correct read_view docstring — 'identity' → 'id'
  ([#314](https://github.com/shawnoster/aya/pull/314),
  [`a066f0d`](https://github.com/shawnoster/aya/commit/a066f0d06727e260eb35ed99722c9cd694d1115e))

- **aya**: Promote the relay pairing used, and write down the relay rules
  ([#314](https://github.com/shawnoster/aya/pull/314),
  [`a066f0d`](https://github.com/shawnoster/aya/commit/a066f0d06727e260eb35ed99722c9cd694d1115e))

- **aya**: Promote the relay pairing used, stop failing fresh installs, unify read
  ([#314](https://github.com/shawnoster/aya/pull/314),
  [`a066f0d`](https://github.com/shawnoster/aya/commit/a066f0d06727e260eb35ed99722c9cd694d1115e))

### Documentation

- **aya**: Write down the relay rules that only existed in the code
  ([#314](https://github.com/shawnoster/aya/pull/314),
  [`a066f0d`](https://github.com/shawnoster/aya/commit/a066f0d06727e260eb35ed99722c9cd694d1115e))


## v1.45.1 (2026-08-10)

### Bug Fixes

- **aya**: Close the last two CLI/MCP divergences
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Cross-reference ack/send and state read's ingest prerequisite
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Keep ANSI out of machine output, and colour out of the tests
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Make relay failures loud, then remove the structure that hid them
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Make relay polling fail loudly instead of returning empty
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Make the not-ingested error name its remedy
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Stop the send summary reading the same for full and partial delivery
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Type-check the whole package ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

### Chores

- **ci**: SHA-pin third-party actions, add job timeouts
  ([#311](https://github.com/shawnoster/aya/pull/311),
  [`a53fe00`](https://github.com/shawnoster/aya/commit/a53fe001c0fd5cd58e288f727a63cb73da7e3b21))

- **deps**: Bump actions/checkout from 6 to 7 ([#304](https://github.com/shawnoster/aya/pull/304),
  [`eaec003`](https://github.com/shawnoster/aya/commit/eaec00328a9f286f8904dad37a988339358fb183))

- **deps**: Bump astral-sh/setup-uv from 8.1.0 to 8.2.0
  ([#296](https://github.com/shawnoster/aya/pull/296),
  [`f942f19`](https://github.com/shawnoster/aya/commit/f942f191ecbd217baac5f4f77ebb349876b6efd3))

- **deps**: Bump astral-sh/setup-uv from 8.2.0 to 9.0.0
  ([#310](https://github.com/shawnoster/aya/pull/310),
  [`031d7f0`](https://github.com/shawnoster/aya/commit/031d7f081a78bc64ad5ef7895f23ee898d990d06))

- **deps**: Bump cryptography from 48.0.0 to 49.0.0
  ([#302](https://github.com/shawnoster/aya/pull/302),
  [`9546814`](https://github.com/shawnoster/aya/commit/95468142e801a7fff20282ef33b1f1823e00e192))

- **deps**: Bump mcp from 1.27.2 to 1.28.0 ([#306](https://github.com/shawnoster/aya/pull/306),
  [`3308dc6`](https://github.com/shawnoster/aya/commit/3308dc6d949a0c3617866742a6cbbd6c165ea57e))

- **deps**: Bump typer from 0.26.4 to 0.26.7 ([#298](https://github.com/shawnoster/aya/pull/298),
  [`6a887af`](https://github.com/shawnoster/aya/commit/6a887af41bf2ab1e715a8f63c9e3fc7cb7c81735))

- **deps-dev**: Bump pylint from 4.0.5 to 4.0.6 ([#300](https://github.com/shawnoster/aya/pull/300),
  [`c5670d4`](https://github.com/shawnoster/aya/commit/c5670d4cfc58bfc40c8a7ebfc140c1c8c9f6a140))

- **deps-dev**: Bump pytest from 9.0.3 to 9.1.1 ([#305](https://github.com/shawnoster/aya/pull/305),
  [`a73266b`](https://github.com/shawnoster/aya/commit/a73266b10e6c9b18f188a1056ada7df7e4f400a0))

- **deps-dev**: Bump ruff from 0.15.15 to 0.15.16
  ([#297](https://github.com/shawnoster/aya/pull/297),
  [`3b4d342`](https://github.com/shawnoster/aya/commit/3b4d3420d4cf70708caea96c6bda2dea93b26ead))

- **deps-dev**: Bump ruff from 0.15.16 to 0.15.18
  ([#307](https://github.com/shawnoster/aya/pull/307),
  [`025b65e`](https://github.com/shawnoster/aya/commit/025b65e37179998e793d59d8e71ad50cf35632e0))

### Documentation

- **aya**: Correct two layer docstrings flagged in review
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Fix the same stale-doc defect in three more places
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Record the restructure in the changelog, architecture map and README
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Remove the superpowers design specs ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **skills**: Pin aya refresh to Python 3.13 (coincurve/cffi wheel gap on 3.14)
  ([#299](https://github.com/shawnoster/aya/pull/299),
  [`a54f57f`](https://github.com/shawnoster/aya/commit/a54f57fc3d98f80a240ebbea4e8bacba172b3adb))

### Features

- **aya**: Add outbound log and per-relay delivery reporting
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Keep the relay that pairing proved ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

### Refactoring

- **aya**: Add relay_ops and move the MCP surface onto it
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Delete dead code and back-compat shims
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Extract a service layer and break the CLI/MCP cycle
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Lay the package out in Clean Architecture layers
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Lift the watch-chain state machine out of the CLI
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Move CLI inbox onto relay_ops and unify the listing shape
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Move profile persistence out of the entity
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Move the CLI onto relay_ops; separate inputs from renderers
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Patch the relay where it lives, not through the CLI
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Read the clock through one seam ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Resolve paths on access instead of at import
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Split relay_cmds by direction, and rendering out of the kernel
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Split the CLI into one module per command group
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

- **aya**: Split the packet ledgers out of the keystore
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))

### Testing

- **aya**: Stop the suite writing to real ~/.aya, and guard tool parity
  ([#312](https://github.com/shawnoster/aya/pull/312),
  [`7a1dd62`](https://github.com/shawnoster/aya/commit/7a1dd62052f9b2c03a9186261a763c1770d82a1e))


## v1.45.0 (2026-06-10)

### Bug Fixes

- Address PR #295 review feedback ([#295](https://github.com/shawnoster/aya/pull/295),
  [`9638e26`](https://github.com/shawnoster/aya/commit/9638e2662425cdd22180b07929f0427e18aab6e2))

### Chores

- Clean up watch chain alert typing ([#295](https://github.com/shawnoster/aya/pull/295),
  [`9638e26`](https://github.com/shawnoster/aya/commit/9638e2662425cdd22180b07929f0427e18aab6e2))

- Extract watch chain heartbeat default ([#295](https://github.com/shawnoster/aya/pull/295),
  [`9638e26`](https://github.com/shawnoster/aya/commit/9638e2662425cdd22180b07929f0427e18aab6e2))

- Update uv.lock editable install version to 1.43.0
  ([#295](https://github.com/shawnoster/aya/pull/295),
  [`9638e26`](https://github.com/shawnoster/aya/commit/9638e2662425cdd22180b07929f0427e18aab6e2))

### Code Style

- Format cli gate message ([#295](https://github.com/shawnoster/aya/pull/295),
  [`9638e26`](https://github.com/shawnoster/aya/commit/9638e2662425cdd22180b07929f0427e18aab6e2))

### Features

- Add watch chain hook support ([#295](https://github.com/shawnoster/aya/pull/295),
  [`9638e26`](https://github.com/shawnoster/aya/commit/9638e2662425cdd22180b07929f0427e18aab6e2))

- **scheduler**: Hook-driven watch chain progression with per-stage autonomy and heartbeats
  ([#295](https://github.com/shawnoster/aya/pull/295),
  [`9638e26`](https://github.com/shawnoster/aya/commit/9638e2662425cdd22180b07929f0427e18aab6e2))


## v1.44.0 (2026-06-10)

### Bug Fixes

- Address PR #294 review feedback ([#294](https://github.com/shawnoster/aya/pull/294),
  [`241a3f7`](https://github.com/shawnoster/aya/commit/241a3f780bee09c99622f8a24a9f34189c3872bd))

### Features

- Accept pushed watch updates ([#294](https://github.com/shawnoster/aya/pull/294),
  [`241a3f7`](https://github.com/shawnoster/aya/commit/241a3f780bee09c99622f8a24a9f34189c3872bd))

- **cli**: Add push-driven watch updates to aya hook watch
  ([#294](https://github.com/shawnoster/aya/pull/294),
  [`241a3f7`](https://github.com/shawnoster/aya/commit/241a3f780bee09c99622f8a24a9f34189c3872bd))

### Refactoring

- Index pushed watch updates ([#294](https://github.com/shawnoster/aya/pull/294),
  [`241a3f7`](https://github.com/shawnoster/aya/commit/241a3f780bee09c99622f8a24a9f34189c3872bd))


## v1.43.1 (2026-06-10)

### Bug Fixes

- Address PR #293 review feedback ([#293](https://github.com/shawnoster/aya/pull/293),
  [`9ad3253`](https://github.com/shawnoster/aya/commit/9ad325362e3a2c7529fab3dda6a874ed7f6a4378))

### Code Style

- Ruff format tests/test_scheduler_providers.py ([#293](https://github.com/shawnoster/aya/pull/293),
  [`9ad3253`](https://github.com/shawnoster/aya/commit/9ad325362e3a2c7529fab3dda6a874ed7f6a4378))

### Performance Improvements

- **scheduler**: Collapse _check_github_pr from 4 REST calls to 1 GraphQL call
  ([#293](https://github.com/shawnoster/aya/pull/293),
  [`9ad3253`](https://github.com/shawnoster/aya/commit/9ad325362e3a2c7529fab3dda6a874ed7f6a4378))

- **scheduler**: Replace 4 REST calls in _check_github_pr with single GraphQL call
  ([#293](https://github.com/shawnoster/aya/pull/293),
  [`9ad3253`](https://github.com/shawnoster/aya/commit/9ad325362e3a2c7529fab3dda6a874ed7f6a4378))


## v1.43.0 (2026-06-07)

### Chores

- **deps**: Bump mcp from 1.27.1 to 1.27.2 ([#290](https://github.com/shawnoster/aya/pull/290),
  [`5c5705a`](https://github.com/shawnoster/aya/commit/5c5705a9d98ffc486f3e02089b8e69a31190a88c))

- **deps**: Bump typer from 0.25.1 to 0.26.4 ([#291](https://github.com/shawnoster/aya/pull/291),
  [`640426d`](https://github.com/shawnoster/aya/commit/640426d2d8521dacf5a6587eb50d579fb1809813))

- **deps-dev**: Bump pytest-asyncio from 1.3.0 to 1.4.0
  ([#289](https://github.com/shawnoster/aya/pull/289),
  [`3b40d82`](https://github.com/shawnoster/aya/commit/3b40d82a4aa6e75ed8104710c4d59f5c0239f622))

### Features

- **opencode**: Add GitHub Actions workflow for opencode integration
  ([#292](https://github.com/shawnoster/aya/pull/292),
  [`8f0454d`](https://github.com/shawnoster/aya/commit/8f0454dd7cb7345cb3117d3ab534d99f8258aee8))


## v1.42.2 (2026-05-29)

### Bug Fixes

- **aya**: Correct OpenCode plugin event handler pattern
  ([`de376e0`](https://github.com/shawnoster/aya/commit/de376e030420361eaf8ffc7e56551fa769f8d11c))


## v1.42.1 (2026-05-29)

### Bug Fixes

- **aya**: Bundle opencode plugin inside package for installed builds
  ([`dae79e9`](https://github.com/shawnoster/aya/commit/dae79e9837ad7d053b6a9b09f3f06b37dc194dd2))


## v1.42.0 (2026-05-29)

### Chores

- **deps**: Bump cryptography from 47.0.0 to 48.0.0
  ([#280](https://github.com/shawnoster/aya/pull/280),
  [`cd1c63c`](https://github.com/shawnoster/aya/commit/cd1c63c697a9cbecf82333ab57d06df2eb25762d))

- **deps**: Bump mcp from 1.27.0 to 1.27.1 ([#279](https://github.com/shawnoster/aya/pull/279),
  [`c985f24`](https://github.com/shawnoster/aya/commit/c985f24034bb015b43a6b613a400aba92bcbc44b))

- **deps**: Bump pydantic from 2.13.3 to 2.13.4 ([#282](https://github.com/shawnoster/aya/pull/282),
  [`4b8e515`](https://github.com/shawnoster/aya/commit/4b8e5152a01fe5451c42d5e2dcdd27b768715bc7))

- **deps-dev**: Bump mypy from 1.20.2 to 2.1.0 ([#283](https://github.com/shawnoster/aya/pull/283),
  [`67a7c24`](https://github.com/shawnoster/aya/commit/67a7c24454d7296ef76e595dcbf5f381bd90d701))

- **deps-dev**: Bump ruff from 0.15.12 to 0.15.15
  ([#284](https://github.com/shawnoster/aya/pull/284),
  [`d55afce`](https://github.com/shawnoster/aya/commit/d55afcea87b1448d653a6a2ec9af3d5856d9587d))

### Features

- **aya**: Add OpenCode plugin for proactive reminder surfacing
  ([`bad5554`](https://github.com/shawnoster/aya/commit/bad5554777811d13fe39c5fcf8c70172e310a230))


## v1.41.0 (2026-05-28)

### Bug Fixes

- **scheduler**: Address PR #286 review feedback
  ([#286](https://github.com/shawnoster/aya/pull/286),
  [`2967486`](https://github.com/shawnoster/aya/commit/29674860a1b0566e67ac6bee300a7f8786cd8e00))

### Chores

- **deps**: Bump typer from 0.25.0 to 0.25.1 ([#278](https://github.com/shawnoster/aya/pull/278),
  [`3347a4e`](https://github.com/shawnoster/aya/commit/3347a4eb7f7862a6f53e6792637a91407b528969))

- **deps-dev**: Bump ruff from 0.15.11 to 0.15.12
  ([#277](https://github.com/shawnoster/aya/pull/277),
  [`c572b7d`](https://github.com/shawnoster/aya/commit/c572b7d66f2b5a4504ada8d7158683c534f66962))

### Features

- **scheduler**: Add new_comments condition to github-pr watch provider
  ([#286](https://github.com/shawnoster/aya/pull/286),
  [`2967486`](https://github.com/shawnoster/aya/commit/29674860a1b0566e67ac6bee300a7f8786cd8e00))


## v1.40.0 (2026-05-01)

### Bug Fixes

- **gateway**: Address review — robust kitt termination + dedupe auth
  ([#276](https://github.com/shawnoster/aya/pull/276),
  [`4a6aca0`](https://github.com/shawnoster/aya/commit/4a6aca0da1afb84870bbd66dd0c9d69c1cafcb31))

### Features

- **gateway**: POST /effects/kitt route, fire-and-forget subprocess
  ([#276](https://github.com/shawnoster/aya/pull/276),
  [`4a6aca0`](https://github.com/shawnoster/aya/commit/4a6aca0da1afb84870bbd66dd0c9d69c1cafcb31))

- **gateway**: POST /effects/kitt route, fire-and-forget subprocess (closes #266)
  ([#276](https://github.com/shawnoster/aya/pull/276),
  [`4a6aca0`](https://github.com/shawnoster/aya/commit/4a6aca0da1afb84870bbd66dd0c9d69c1cafcb31))


## v1.39.0 (2026-05-01)

### Bug Fixes

- Address PR #274 review feedback ([#274](https://github.com/shawnoster/aya/pull/274),
  [`3a8855a`](https://github.com/shawnoster/aya/commit/3a8855a8329ad6a860291ad5246e34f8a157d914))

- **gateway**: Address review — strip env-var token before use
  ([#275](https://github.com/shawnoster/aya/pull/275),
  [`07d3b6a`](https://github.com/shawnoster/aya/commit/07d3b6a18c9e145e4493919d4008b0493eb0f856))

- **gateway**: Address review — sync stale references to old compose
  ([#273](https://github.com/shawnoster/aya/pull/273),
  [`9bfb1b5`](https://github.com/shawnoster/aya/commit/9bfb1b548292cc42e3f8fafa499386f5530547df))

### Chores

- Update uv.lock (aya-ai-assist 1.36.3 → 1.38.0)
  ([#274](https://github.com/shawnoster/aya/pull/274),
  [`3a8855a`](https://github.com/shawnoster/aya/commit/3a8855a8329ad6a860291ad5246e34f8a157d914))

- **gateway**: Align Babar deploy with DSM Container Manager flow
  ([#273](https://github.com/shawnoster/aya/pull/273),
  [`9bfb1b5`](https://github.com/shawnoster/aya/commit/9bfb1b548292cc42e3f8fafa499386f5530547df))

### Documentation

- **gateway**: Runbook fixes from Babar install — paths, persistence, env_file form
  ([#274](https://github.com/shawnoster/aya/pull/274),
  [`3a8855a`](https://github.com/shawnoster/aya/commit/3a8855a8329ad6a860291ad5246e34f8a157d914))

### Features

- **gateway**: Bundle nanoleaf-kitt in image, NANOLEAF_TOKEN via env_file
  ([#275](https://github.com/shawnoster/aya/pull/275),
  [`07d3b6a`](https://github.com/shawnoster/aya/commit/07d3b6a18c9e145e4493919d4008b0493eb0f856))

- **gateway**: Bundle nanoleaf-kitt in image, NANOLEAF_TOKEN via env_file (closes #265)
  ([#275](https://github.com/shawnoster/aya/pull/275),
  [`07d3b6a`](https://github.com/shawnoster/aya/commit/07d3b6a18c9e145e4493919d4008b0493eb0f856))


## v1.38.0 (2026-04-30)

### Bug Fixes

- **gateway**: Clarify README — env_file is host-side, not bind-mounted
  ([`625a4e0`](https://github.com/shawnoster/aya/commit/625a4e0d722b04b5fa96290db7ff8b87223d9008))

- **gateway**: Cover lifespan fail-fast for missing/blank GATEWAY_BEARER
  ([`625a4e0`](https://github.com/shawnoster/aya/commit/625a4e0d722b04b5fa96290db7ff8b87223d9008))

- **gateway**: Disable /docs, /redoc, /openapi.json so only /health is unauthed
  ([`625a4e0`](https://github.com/shawnoster/aya/commit/625a4e0d722b04b5fa96290db7ff8b87223d9008))

- **gateway**: Drop misleading Quickstart curl that hits a 404 endpoint
  ([`625a4e0`](https://github.com/shawnoster/aya/commit/625a4e0d722b04b5fa96290db7ff8b87223d9008))

- **gateway**: Stop leaking bearer token through shell argv in deploy runbook
  ([#272](https://github.com/shawnoster/aya/pull/272),
  [`148aaf7`](https://github.com/shawnoster/aya/commit/148aaf72396c26081d4a714282c6bc07c8639e50))

- **gateway**: Use secrets.compare_digest for constant-time token check
  ([`625a4e0`](https://github.com/shawnoster/aya/commit/625a4e0d722b04b5fa96290db7ff8b87223d9008))

- **gateway**: Wrap troubleshooting docker commands with ssh babar context
  ([#272](https://github.com/shawnoster/aya/pull/272),
  [`148aaf7`](https://github.com/shawnoster/aya/commit/148aaf72396c26081d4a714282c6bc07c8639e50))

### Chores

- **gateway**: Collapse nested with-statements (ruff SIM117)
  ([`625a4e0`](https://github.com/shawnoster/aya/commit/625a4e0d722b04b5fa96290db7ff8b87223d9008))

### Documentation

- **gateway**: Fix deploy runbook — credential field, single-shot secrets write
  ([#272](https://github.com/shawnoster/aya/pull/272),
  [`148aaf7`](https://github.com/shawnoster/aya/commit/148aaf72396c26081d4a714282c6bc07c8639e50))

### Features

- **gateway**: Deploy runbook for Babar ([#272](https://github.com/shawnoster/aya/pull/272),
  [`148aaf7`](https://github.com/shawnoster/aya/commit/148aaf72396c26081d4a714282c6bc07c8639e50))

- **gateway**: Deploy runbook for Babar (closes #264)
  ([#272](https://github.com/shawnoster/aya/pull/272),
  [`148aaf7`](https://github.com/shawnoster/aya/commit/148aaf72396c26081d4a714282c6bc07c8639e50))


## v1.37.0 (2026-04-29)

### Bug Fixes

- **gateway**: Address review — bound HEALTHCHECK urlopen with timeout=2
  ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

- **gateway**: Install Docker image deps from uv.lock, not unpinned pip
  ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

- **makefile**: Unlink-skills now verifies symlink target before removing
  ([`51a6797`](https://github.com/shawnoster/aya/commit/51a679715058071e4598529d5f35f81739251d54))

### Chores

- Initial plan for test coverage improvements ([#269](https://github.com/shawnoster/aya/pull/269),
  [`fc5485c`](https://github.com/shawnoster/aya/commit/fc5485cc201eea77d9f1826b08362168cb0068df))

- **ci**: Bump astral-sh/setup-uv from v7 to v8 ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

- **ci**: Bump astral-sh/setup-uv to v8.1.0 ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

### Code Style

- **tests**: Fix ruff lint and format violations from CI
  ([#269](https://github.com/shawnoster/aya/pull/269),
  [`fc5485c`](https://github.com/shawnoster/aya/commit/fc5485cc201eea77d9f1826b08362168cb0068df))

### Continuous Integration

- **gateway**: Add Gateway CI workflow with path filter on push
  ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

### Documentation

- **gateway**: Pin local dev to port 8080 to match Dockerfile/compose
  ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

### Features

- **gateway**: Bootstrap FastAPI skeleton with /health
  ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

### Testing

- Add comprehensive tests for profile, scheduler providers, display, and more
  ([#269](https://github.com/shawnoster/aya/pull/269),
  [`fc5485c`](https://github.com/shawnoster/aya/commit/fc5485cc201eea77d9f1826b08362168cb0068df))

- Fix hardcoded date in display tests to use relative timedelta
  ([#269](https://github.com/shawnoster/aya/pull/269),
  [`fc5485c`](https://github.com/shawnoster/aya/commit/fc5485cc201eea77d9f1826b08362168cb0068df))

- **gateway**: Address review — assert /health version contract
  ([#270](https://github.com/shawnoster/aya/pull/270),
  [`887a4b3`](https://github.com/shawnoster/aya/commit/887a4b3b65e25ba2ee4da73f422f614e69d30b1a))

- **scheduler**: Drop dead datetime call; harden returns_within_window
  ([#269](https://github.com/shawnoster/aya/pull/269),
  [`fc5485c`](https://github.com/shawnoster/aya/commit/fc5485cc201eea77d9f1826b08362168cb0068df))

- **scheduler**: Make test_custom_hours_window actually assert empty result
  ([#269](https://github.com/shawnoster/aya/pull/269),
  [`fc5485c`](https://github.com/shawnoster/aya/commit/fc5485cc201eea77d9f1826b08362168cb0068df))

- **scheduler**: Make test_does_not_return_future_reminders actually assert
  ([#269](https://github.com/shawnoster/aya/pull/269),
  [`fc5485c`](https://github.com/shawnoster/aya/commit/fc5485cc201eea77d9f1826b08362168cb0068df))


## v1.36.3 (2026-04-28)

### Bug Fixes

- Address PR #249 review feedback ([#249](https://github.com/shawnoster/aya/pull/249),
  [`a28a873`](https://github.com/shawnoster/aya/commit/a28a8731a4792b92d95bc8cf12b2e726531d604c))

- Apply ruff formatting to mcp_server.py to pass CI lint check
  ([#260](https://github.com/shawnoster/aya/pull/260),
  [`4b7f38c`](https://github.com/shawnoster/aya/commit/4b7f38c6ad6c2f2dbe6b205c4cdfc33cf719d789))

- MCP aya_inbox diverges from CLI inbox — missing dropped_ids filter and trusted flag
  ([#260](https://github.com/shawnoster/aya/pull/260),
  [`4b7f38c`](https://github.com/shawnoster/aya/commit/4b7f38c6ad6c2f2dbe6b205c4cdfc33cf719d789))

- MCP aya_inbox now filters dropped_ids and includes trusted flag
  ([#260](https://github.com/shawnoster/aya/pull/260),
  [`4b7f38c`](https://github.com/shawnoster/aya/commit/4b7f38c6ad6c2f2dbe6b205c4cdfc33cf719d789))

- Rename pending_packets to new_packets per review feedback
  ([#260](https://github.com/shawnoster/aya/pull/260),
  [`4b7f38c`](https://github.com/shawnoster/aya/commit/4b7f38c6ad6c2f2dbe6b205c4cdfc33cf719d789))

- **changelog**: Correct delegation direction (review)
  ([#250](https://github.com/shawnoster/aya/pull/250),
  [`338a8c5`](https://github.com/shawnoster/aya/commit/338a8c5758df9fa2b1f8ea064da2a2b7c285da0b))

- **read**: Wrap panel body in Text() to preserve brackets (review)
  ([#251](https://github.com/shawnoster/aya/pull/251),
  [`1340c06`](https://github.com/shawnoster/aya/commit/1340c06ca3da330746fe31d35d853c314f414c75))

- **skills**: Clarify wire-up framing for non-home consumers
  ([#248](https://github.com/shawnoster/aya/pull/248),
  [`4ef4fe7`](https://github.com/shawnoster/aya/commit/4ef4fe7915d0ee1d34877deacbd0b3671e8e353b))

- **skills**: Drop misleading AGENTS.md cross-reference in refresh
  ([#248](https://github.com/shawnoster/aya/pull/248),
  [`4ef4fe7`](https://github.com/shawnoster/aya/commit/4ef4fe7915d0ee1d34877deacbd0b3671e8e353b))

- **skills**: Restore ATLASSIAN_* env-var note for jira watches
  ([#248](https://github.com/shawnoster/aya/pull/248),
  [`4ef4fe7`](https://github.com/shawnoster/aya/commit/4ef4fe7915d0ee1d34877deacbd0b3671e8e353b))

- **skills**: Restore jira-ticket row in watch provider table
  ([#248](https://github.com/shawnoster/aya/pull/248),
  [`4ef4fe7`](https://github.com/shawnoster/aya/commit/4ef4fe7915d0ee1d34877deacbd0b3671e8e353b))

- **skills**: Use placeholder for editable-clone path
  ([#248](https://github.com/shawnoster/aya/pull/248),
  [`4ef4fe7`](https://github.com/shawnoster/aya/commit/4ef4fe7915d0ee1d34877deacbd0b3671e8e353b))

### Chores

- **cli**: Tier 1 prune — drop legacy commands and deprecated flags
  ([#250](https://github.com/shawnoster/aya/pull/250),
  [`338a8c5`](https://github.com/shawnoster/aya/commit/338a8c5758df9fa2b1f8ea064da2a2b7c285da0b))

- **cli**: Tier 2 consolidation — drop pack, show, schedule check
  ([#251](https://github.com/shawnoster/aya/pull/251),
  [`1340c06`](https://github.com/shawnoster/aya/commit/1340c06ca3da330746fe31d35d853c314f414c75))

- **deps**: Bump cryptography from 46.0.7 to 47.0.0
  ([#252](https://github.com/shawnoster/aya/pull/252),
  [`1ca9057`](https://github.com/shawnoster/aya/commit/1ca90575b409b58c7cb975cfa334c0506218f3bf))

- **deps**: Bump pydantic from 2.13.2 to 2.13.3 ([#253](https://github.com/shawnoster/aya/pull/253),
  [`42b6496`](https://github.com/shawnoster/aya/commit/42b6496a0aef7ba333c9865bd9ad543267a7c649))

- **deps**: Bump typer from 0.24.1 to 0.25.0 ([#256](https://github.com/shawnoster/aya/pull/256),
  [`ef3b3e6`](https://github.com/shawnoster/aya/commit/ef3b3e68fc7bfe2bb8c00eb507fd7589a42346bf))

- **deps-dev**: Bump mypy from 1.20.1 to 1.20.2 ([#254](https://github.com/shawnoster/aya/pull/254),
  [`4949b65`](https://github.com/shawnoster/aya/commit/4949b6517ac74e312c0d3c46637caf3bf7df2307))

- **deps-dev**: Bump pre-commit from 4.5.1 to 4.6.0
  ([#255](https://github.com/shawnoster/aya/pull/255),
  [`6bf842b`](https://github.com/shawnoster/aya/commit/6bf842b154d1e869454715ac1d09cb6ca808b549))

### Documentation

- Consistency + accuracy + enablement pass ([#249](https://github.com/shawnoster/aya/pull/249),
  [`a28a873`](https://github.com/shawnoster/aya/commit/a28a8731a4792b92d95bc8cf12b2e726531d604c))

- Drop deprecated-alias notes after Tier 1 prune
  ([#257](https://github.com/shawnoster/aya/pull/257),
  [`4010c17`](https://github.com/shawnoster/aya/commit/4010c179dbf35d7fb3b4528acca94254ed391aa8))

- **skills**: Clarify wiring patterns and broaden relay invocation phrases
  ([#248](https://github.com/shawnoster/aya/pull/248),
  [`4ef4fe7`](https://github.com/shawnoster/aya/commit/4ef4fe7915d0ee1d34877deacbd0b3671e8e353b))

- **skills**: Wiring patterns, relay phrases, editable refresh
  ([#248](https://github.com/shawnoster/aya/pull/248),
  [`4ef4fe7`](https://github.com/shawnoster/aya/commit/4ef4fe7915d0ee1d34877deacbd0b3671e8e353b))


## v1.36.2 (2026-04-24)

### Bug Fixes

- **ingest**: Address review — validate packet.id before path construction
  ([#245](https://github.com/shawnoster/aya/pull/245),
  [`8f8bc40`](https://github.com/shawnoster/aya/commit/8f8bc405b5276d18368e3d33d411a57b01a347cd))

- **lint**: Apply ruff format to cli.py and ingest.py
  ([#245](https://github.com/shawnoster/aya/pull/245),
  [`8f8bc40`](https://github.com/shawnoster/aya/commit/8f8bc405b5276d18368e3d33d411a57b01a347cd))

- **mcp**: Address review — correct stale comment on ingest failure mode
  ([#245](https://github.com/shawnoster/aya/pull/245),
  [`8f8bc40`](https://github.com/shawnoster/aya/commit/8f8bc405b5276d18368e3d33d411a57b01a347cd))

- **receive**: Remove since cursor that permanently excluded pending packets
  ([#247](https://github.com/shawnoster/aya/pull/247),
  [`c8d5944`](https://github.com/shawnoster/aya/commit/c8d5944737d9b2a175698805a4650f0bd6d9c049))

- **test**: Address review — enforce keyword-only quiet in ingest stub
  ([#245](https://github.com/shawnoster/aya/pull/245),
  [`8f8bc40`](https://github.com/shawnoster/aya/commit/8f8bc405b5276d18368e3d33d411a57b01a347cd))

### Refactoring

- **ingest**: Lift _ingest out of cli.py into shared aya.ingest module
  ([#245](https://github.com/shawnoster/aya/pull/245),
  [`8f8bc40`](https://github.com/shawnoster/aya/commit/8f8bc405b5276d18368e3d33d411a57b01a347cd))

- **ingest**: Lift `_ingest` out of `cli.py` into shared `aya.ingest` module
  ([#245](https://github.com/shawnoster/aya/pull/245),
  [`8f8bc40`](https://github.com/shawnoster/aya/commit/8f8bc405b5276d18368e3d33d411a57b01a347cd))


## v1.36.1 (2026-04-23)

### Bug Fixes

- **mcp**: Address review — skip cursor advance when persist fails
  ([#243](https://github.com/shawnoster/aya/pull/243),
  [`ec01179`](https://github.com/shawnoster/aya/commit/ec01179a37a5a799d8019a39d4f1a2af9518123e))

- **mcp**: Persist packet body on aya_receive ([#243](https://github.com/shawnoster/aya/pull/243),
  [`ec01179`](https://github.com/shawnoster/aya/commit/ec01179a37a5a799d8019a39d4f1a2af9518123e))

### Chores

- **deps**: Bump pydantic from 2.12.5 to 2.13.2 ([#242](https://github.com/shawnoster/aya/pull/242),
  [`d7c18b0`](https://github.com/shawnoster/aya/commit/d7c18b0ee109a717a2a1e52b442184b08893e3af))

- **deps**: Sync uv.lock to 1.36.0 ([#239](https://github.com/shawnoster/aya/pull/239),
  [`05e906d`](https://github.com/shawnoster/aya/commit/05e906dc3faa6564b29fe908785297973123079e))

- **deps-dev**: Bump ruff from 0.15.10 to 0.15.11
  ([#241](https://github.com/shawnoster/aya/pull/241),
  [`941bd5a`](https://github.com/shawnoster/aya/commit/941bd5a78fea6445a46ee7c22f56fb85aa64c6e7))

- **install**: Remove aya log auto hooks from PostToolUse
  ([#238](https://github.com/shawnoster/aya/pull/238),
  [`7f8e959`](https://github.com/shawnoster/aya/commit/7f8e959476c5ca8ca59b01875b1f4622de410944))

- **mcp**: Address review — update _ingest docstring, tighten test
  ([#243](https://github.com/shawnoster/aya/pull/243),
  [`ec01179`](https://github.com/shawnoster/aya/commit/ec01179a37a5a799d8019a39d4f1a2af9518123e))


## v1.36.0 (2026-04-17)

### Bug Fixes

- **relay-skill**: Address review — --relay overrides defaults, no fallback
  ([#236](https://github.com/shawnoster/aya/pull/236),
  [`2e13ec1`](https://github.com/shawnoster/aya/commit/2e13ec1ecd4c1805658dcd3b08f091b6d69191f7))

- **skills**: Address review — correct aya_receive and aya_read output shapes
  ([#237](https://github.com/shawnoster/aya/pull/237),
  [`9dc4775`](https://github.com/shawnoster/aya/commit/9dc4775a04125ab647165d262901c06a89eae5c3))

- **skills**: Address review — qualify instance=<label> applicability
  ([#237](https://github.com/shawnoster/aya/pull/237),
  [`9dc4775`](https://github.com/shawnoster/aya/commit/9dc4775a04125ab647165d262901c06a89eae5c3))

- **skills**: Address review — use aya_relay_status.trusted_keys for DID→label
  ([#237](https://github.com/shawnoster/aya/pull/237),
  [`9dc4775`](https://github.com/shawnoster/aya/commit/9dc4775a04125ab647165d262901c06a89eae5c3))

### Documentation

- **relay-skill**: Thread explicit --relay on every send/receive
  ([#236](https://github.com/shawnoster/aya/pull/236),
  [`2e13ec1`](https://github.com/shawnoster/aya/commit/2e13ec1ecd4c1805658dcd3b08f091b6d69191f7))

### Features

- **skills**: Prefer MCP tools over CLI in relay and aya skills
  ([#237](https://github.com/shawnoster/aya/pull/237),
  [`9dc4775`](https://github.com/shawnoster/aya/commit/9dc4775a04125ab647165d262901c06a89eae5c3))


## v1.35.2 (2026-04-17)

### Bug Fixes

- **aya-skill**: Narrow output style rule scope — relay-poll is a special case
  ([#235](https://github.com/shawnoster/aya/pull/235),
  [`5af4bf5`](https://github.com/shawnoster/aya/commit/5af4bf5f8fc282460f1d54ae549e728394ac4c0a))

- **aya-skill**: Quiet session cron output — silent logging, message-only reminders
  ([#235](https://github.com/shawnoster/aya/pull/235),
  [`5af4bf5`](https://github.com/shawnoster/aya/commit/5af4bf5f8fc282460f1d54ae549e728394ac4c0a))


## v1.35.1 (2026-04-17)

### Bug Fixes

- **scheduler**: Detect system timezone instead of hardcoding America/Denver
  ([#233](https://github.com/shawnoster/aya/pull/233),
  [`b397639`](https://github.com/shawnoster/aya/commit/b397639317fed3957dfef8ad7ff058e6c3217c53))

- **scheduler**: Simplify tz detection — remove dead code, use logger
  ([#233](https://github.com/shawnoster/aya/pull/233),
  [`b397639`](https://github.com/shawnoster/aya/commit/b397639317fed3957dfef8ad7ff058e6c3217c53))


## v1.35.0 (2026-04-17)

### Bug Fixes

- **mcp**: Clamp packets limit, safe mtime, filter relay last_checked
  ([#232](https://github.com/shawnoster/aya/pull/232),
  [`ed01cc4`](https://github.com/shawnoster/aya/commit/ed01cc4f3139dcc4f0477810e4f2df2887b44c2f))

### Features

- **mcp**: Add read, config, packets, and relay-status tools
  ([#232](https://github.com/shawnoster/aya/pull/232),
  [`ed01cc4`](https://github.com/shawnoster/aya/commit/ed01cc4f3139dcc4f0477810e4f2df2887b44c2f))

### Testing

- **mcp**: Add tests for new MCP tools ([#232](https://github.com/shawnoster/aya/pull/232),
  [`ed01cc4`](https://github.com/shawnoster/aya/commit/ed01cc4f3139dcc4f0477810e4f2df2887b44c2f))


## v1.34.0 (2026-04-16)

### Bug Fixes

- **docs**: Update AGENTS.md slash command table for consolidated skills
  ([#231](https://github.com/shawnoster/aya/pull/231),
  [`71e5955`](https://github.com/shawnoster/aya/commit/71e5955d4f71b95cbb4243de49c0522c29d316c1))

- **docs**: Update README plugin section for /aya + /relay skills
  ([#231](https://github.com/shawnoster/aya/pull/231),
  [`71e5955`](https://github.com/shawnoster/aya/commit/71e5955d4f71b95cbb4243de49c0522c29d316c1))

- **skill**: Address PR #231 review — receive flags, skill refs, tick interval
  ([#231](https://github.com/shawnoster/aya/pull/231),
  [`71e5955`](https://github.com/shawnoster/aya/commit/71e5955d4f71b95cbb4243de49c0522c29d316c1))

### Features

- Consolidate slash commands into /aya router skill
  ([#231](https://github.com/shawnoster/aya/pull/231),
  [`71e5955`](https://github.com/shawnoster/aya/commit/71e5955d4f71b95cbb4243de49c0522c29d316c1))


## v1.33.0 (2026-04-16)

### Bug Fixes

- Address PR #230 review — stale dispatch references and typo
  ([#230](https://github.com/shawnoster/aya/pull/230),
  [`54d19b6`](https://github.com/shawnoster/aya/commit/54d19b6113d91adf3d059f83fd26aa0bc873a400))

- **relay**: Validate instance via _resolve_instance and add --as tests
  ([#230](https://github.com/shawnoster/aya/pull/230),
  [`54d19b6`](https://github.com/shawnoster/aya/commit/54d19b6113d91adf3d059f83fd26aa0bc873a400))

### Features

- Rename dispatch → send, old send → send-raw ([#230](https://github.com/shawnoster/aya/pull/230),
  [`54d19b6`](https://github.com/shawnoster/aya/commit/54d19b6113d91adf3d059f83fd26aa0bc873a400))

- **cli**: Rename dispatch → send, old send → send-raw
  ([#230](https://github.com/shawnoster/aya/pull/230),
  [`54d19b6`](https://github.com/shawnoster/aya/commit/54d19b6113d91adf3d059f83fd26aa0bc873a400))

- **relay**: Add `relay status` subcommand ([#230](https://github.com/shawnoster/aya/pull/230),
  [`54d19b6`](https://github.com/shawnoster/aya/commit/54d19b6113d91adf3d059f83fd26aa0bc873a400))

### Testing

- **relay**: Add tests for relay status command ([#230](https://github.com/shawnoster/aya/pull/230),
  [`54d19b6`](https://github.com/shawnoster/aya/commit/54d19b6113d91adf3d059f83fd26aa0bc873a400))


## v1.32.0 (2026-04-16)

### Bug Fixes

- **relay**: Validate instance via _resolve_instance and add --as tests
  ([#229](https://github.com/shawnoster/aya/pull/229),
  [`a13dd70`](https://github.com/shawnoster/aya/commit/a13dd7018aed06d832c713e6302923f4051013c1))

### Features

- **relay**: Add `relay status` subcommand ([#229](https://github.com/shawnoster/aya/pull/229),
  [`a13dd70`](https://github.com/shawnoster/aya/commit/a13dd7018aed06d832c713e6302923f4051013c1))

- **relay**: Add relay status subcommand ([#229](https://github.com/shawnoster/aya/pull/229),
  [`a13dd70`](https://github.com/shawnoster/aya/commit/a13dd7018aed06d832c713e6302923f4051013c1))

### Testing

- **relay**: Add tests for relay status command ([#229](https://github.com/shawnoster/aya/pull/229),
  [`a13dd70`](https://github.com/shawnoster/aya/commit/a13dd7018aed06d832c713e6302923f4051013c1))


## v1.31.2 (2026-04-16)

### Bug Fixes

- Improve error handling for missing crontab and gh CLI
  ([#228](https://github.com/shawnoster/aya/pull/228),
  [`93dd42a`](https://github.com/shawnoster/aya/commit/93dd42a4715636299615f032910a4ec4996ef98f))

- **install**: Catch FileNotFoundError for crontab on WSL
  ([#228](https://github.com/shawnoster/aya/pull/228),
  [`93dd42a`](https://github.com/shawnoster/aya/commit/93dd42a4715636299615f032910a4ec4996ef98f))

- **install**: Improve crontab missing error message
  ([#228](https://github.com/shawnoster/aya/pull/228),
  [`93dd42a`](https://github.com/shawnoster/aya/commit/93dd42a4715636299615f032910a4ec4996ef98f))

- **scheduler**: Add type annotation and use module logger consistently
  ([#228](https://github.com/shawnoster/aya/pull/228),
  [`93dd42a`](https://github.com/shawnoster/aya/commit/93dd42a4715636299615f032910a4ec4996ef98f))

- **scheduler**: Warn when gh CLI is missing instead of silent failure
  ([#228](https://github.com/shawnoster/aya/pull/228),
  [`93dd42a`](https://github.com/shawnoster/aya/commit/93dd42a4715636299615f032910a4ec4996ef98f))


## v1.31.1 (2026-04-16)

### Bug Fixes

- Batch quick fixes from E2E audit (#217, #219, #222)
  ([#227](https://github.com/shawnoster/aya/pull/227),
  [`5963f42`](https://github.com/shawnoster/aya/commit/5963f42ab4c575fd45dcffcd4e92912906bcb726))

- **cli**: Add next-steps guidance to aya init output
  ([#227](https://github.com/shawnoster/aya/pull/227),
  [`5963f42`](https://github.com/shawnoster/aya/commit/5963f42ab4c575fd45dcffcd4e92912906bcb726))

- **docs**: Use concrete command in Python 3.14 note
  ([#227](https://github.com/shawnoster/aya/pull/227),
  [`5963f42`](https://github.com/shawnoster/aya/commit/5963f42ab4c575fd45dcffcd4e92912906bcb726))

- **skill**: Add hook re-install step to aya-refresh
  ([#227](https://github.com/shawnoster/aya/pull/227),
  [`5963f42`](https://github.com/shawnoster/aya/commit/5963f42ab4c575fd45dcffcd4e92912906bcb726))

### Documentation

- Document Python 3.14 limitation in README ([#227](https://github.com/shawnoster/aya/pull/227),
  [`5963f42`](https://github.com/shawnoster/aya/commit/5963f42ab4c575fd45dcffcd4e92912906bcb726))


## v1.31.0 (2026-04-16)

### Bug Fixes

- **test**: Use module-level runner and assert exit_code == 0
  ([#215](https://github.com/shawnoster/aya/pull/215),
  [`19f685c`](https://github.com/shawnoster/aya/commit/19f685cb2075665818e69fbef60567f55ad5f35c))

### Features

- **cli**: Add cross-references between send, pack, and dispatch help text
  ([#215](https://github.com/shawnoster/aya/pull/215),
  [`19f685c`](https://github.com/shawnoster/aya/commit/19f685cb2075665818e69fbef60567f55ad5f35c))


## v1.30.1 (2026-04-16)

### Bug Fixes

- Use `gh repo view` instead of regex for GitHub remote URL parsing
  ([#214](https://github.com/shawnoster/aya/pull/214),
  [`4cca589`](https://github.com/shawnoster/aya/commit/4cca5897a604cab0eb433d003e8c3f3db374f19f))

- **cli**: Use gh repo view instead of regex for GitHub remote URL parsing
  ([#214](https://github.com/shawnoster/aya/pull/214),
  [`4cca589`](https://github.com/shawnoster/aya/commit/4cca5897a604cab0eb433d003e8c3f3db374f19f))

### Testing

- Add tests for gh-repo-view-based owner/repo parsing
  ([#214](https://github.com/shawnoster/aya/pull/214),
  [`4cca589`](https://github.com/shawnoster/aya/commit/4cca5897a604cab0eb433d003e8c3f3db374f19f))


## v1.30.0 (2026-04-13)

### Bug Fixes

- Address PR #213 review feedback ([#213](https://github.com/shawnoster/aya/pull/213),
  [`bafa134`](https://github.com/shawnoster/aya/commit/bafa134e9f1c452ab8405d926a9c48092d9c7ca5))

### Chores

- Update uv.lock for 1.29.0 ([#213](https://github.com/shawnoster/aya/pull/213),
  [`bafa134`](https://github.com/shawnoster/aya/commit/bafa134e9f1c452ab8405d926a9c48092d9c7ca5))

### Features

- **cli**: Add aya relay subcommand for managing default_relays
  ([#213](https://github.com/shawnoster/aya/pull/213),
  [`bafa134`](https://github.com/shawnoster/aya/commit/bafa134e9f1c452ab8405d926a9c48092d9c7ca5))

- **cli**: Aya relay subcommand for managing default_relays
  ([#213](https://github.com/shawnoster/aya/pull/213),
  [`bafa134`](https://github.com/shawnoster/aya/commit/bafa134e9f1c452ab8405d926a9c48092d9c7ca5))

### Testing

- **cli**: Add relay URL validation coverage + tighten whitespace check
  ([#213](https://github.com/shawnoster/aya/pull/213),
  [`bafa134`](https://github.com/shawnoster/aya/commit/bafa134e9f1c452ab8405d926a9c48092d9c7ca5))


## v1.29.0 (2026-04-13)

### Bug Fixes

- Address PR #205 review feedback ([#205](https://github.com/shawnoster/aya/pull/205),
  [`d8d1fb9`](https://github.com/shawnoster/aya/commit/d8d1fb9aab61a5f433f43fcacdc7f8fbe455cf57))

- **credentials**: Pass tuples at construction sites for frozen dataclass
  ([#205](https://github.com/shawnoster/aya/pull/205),
  [`d8d1fb9`](https://github.com/shawnoster/aya/commit/d8d1fb9aab61a5f433f43fcacdc7f8fbe455cf57))

### Chores

- **deps**: Bump cryptography from 46.0.6 to 46.0.7
  ([#207](https://github.com/shawnoster/aya/pull/207),
  [`25b37c9`](https://github.com/shawnoster/aya/commit/25b37c993d1d7d4c87687bad4e72a98e9fe00367))

- **deps**: Bump rich from 14.3.3 to 15.0.0 ([#206](https://github.com/shawnoster/aya/pull/206),
  [`69ce076`](https://github.com/shawnoster/aya/commit/69ce0761c30aa021246ef18e4eb4af7f16bfd1cc))

- **deps-dev**: Bump mypy from 1.20.0 to 1.20.1 ([#208](https://github.com/shawnoster/aya/pull/208),
  [`3afac08`](https://github.com/shawnoster/aya/commit/3afac0880e6aca92dc75b71e40fe8ecc07636225))

- **deps-dev**: Bump pytest from 9.0.2 to 9.0.3 ([#209](https://github.com/shawnoster/aya/pull/209),
  [`e097e61`](https://github.com/shawnoster/aya/commit/e097e6125a74dc905042ad5649af74f6cc6b2d96))

- **deps-dev**: Bump respx from 0.22.0 to 0.23.1
  ([#210](https://github.com/shawnoster/aya/pull/210),
  [`cb90348`](https://github.com/shawnoster/aya/commit/cb903488e9161abdcca71ba574a291a51c6929d1))

### Features

- **status**: Add credential ACK for common service integrations
  ([#205](https://github.com/shawnoster/aya/pull/205),
  [`d8d1fb9`](https://github.com/shawnoster/aya/commit/d8d1fb9aab61a5f433f43fcacdc7f8fbe455cf57))


## v1.28.0 (2026-04-13)

### Bug Fixes

- **skill**: Address Copilot review on relay skill
  ([#211](https://github.com/shawnoster/aya/pull/211),
  [`0e7be84`](https://github.com/shawnoster/aya/commit/0e7be84a6b0942fae4374a1998bc403eb9da7cac))

### Features

- **skill**: Add content curation and intent inference to relay skill
  ([#211](https://github.com/shawnoster/aya/pull/211),
  [`0e7be84`](https://github.com/shawnoster/aya/commit/0e7be84a6b0942fae4374a1998bc403eb9da7cac))


## v1.27.4 (2026-04-13)

### Bug Fixes

- Address PR #204 review feedback — emit RELAY_UNREACHABLE for connection failures
  ([#204](https://github.com/shawnoster/aya/pull/204),
  [`c39c3d6`](https://github.com/shawnoster/aya/commit/c39c3d69953feb1e9e41262da6d9c8f1a2bfd6eb))

- **cli**: Aya drop relay fetch is now time-bounded
  ([#204](https://github.com/shawnoster/aya/pull/204),
  [`c39c3d6`](https://github.com/shawnoster/aya/commit/c39c3d69953feb1e9e41262da6d9c8f1a2bfd6eb))

### Chores

- Update uv.lock to reflect current package version
  ([#204](https://github.com/shawnoster/aya/pull/204),
  [`c39c3d6`](https://github.com/shawnoster/aya/commit/c39c3d69953feb1e9e41262da6d9c8f1a2bfd6eb))

### Code Style

- **relay**: Ruff format after RelayUnreachableError addition
  ([#204](https://github.com/shawnoster/aya/pull/204),
  [`c39c3d6`](https://github.com/shawnoster/aya/commit/c39c3d69953feb1e9e41262da6d9c8f1a2bfd6eb))


## v1.27.3 (2026-04-12)

### Bug Fixes

- **cli**: Aya read passes structured body through in JSON mode
  ([#203](https://github.com/shawnoster/aya/pull/203),
  [`02105d3`](https://github.com/shawnoster/aya/commit/02105d3b2f31018c8383789cf56ac9d5ebce5fea))


## v1.27.2 (2026-04-12)

### Bug Fixes

- **cli,install**: Enforce 5s minimum tick interval; surface aya send re-sign
  ([#202](https://github.com/shawnoster/aya/pull/202),
  [`e98b5db`](https://github.com/shawnoster/aya/commit/e98b5db29a9d155ff4ba024f379c0b729d2ab875))


## v1.27.1 (2026-04-12)

### Bug Fixes

- **scheduler**: Address code review findings on PRs #195-198
  ([#201](https://github.com/shawnoster/aya/pull/201),
  [`f31a97f`](https://github.com/shawnoster/aya/commit/f31a97f59439200d7a6fa40551f99059b973a708))


## v1.27.0 (2026-04-12)

### Bug Fixes

- **scheduler**: Address PR #199 review feedback
  ([#199](https://github.com/shawnoster/aya/pull/199),
  [`4056f20`](https://github.com/shawnoster/aya/commit/4056f20c4d9b258f5ff8cf287597bd98bed3be9d))

- **scheduler**: Single rewake emit + always create alerts on watch change
  ([#199](https://github.com/shawnoster/aya/pull/199),
  [`4056f20`](https://github.com/shawnoster/aya/commit/4056f20c4d9b258f5ff8cf287597bd98bed3be9d))

### Documentation

- **aya**: Unified watch + asyncRewake design spec
  ([#199](https://github.com/shawnoster/aya/pull/199),
  [`4056f20`](https://github.com/shawnoster/aya/commit/4056f20c4d9b258f5ff8cf287597bd98bed3be9d))

### Features

- **scheduler**: Unify watch + asyncRewake — any watch wakes Claude mid-session
  ([#199](https://github.com/shawnoster/aya/pull/199),
  [`4056f20`](https://github.com/shawnoster/aya/commit/4056f20c4d9b258f5ff8cf287597bd98bed3be9d))


## v1.26.1 (2026-04-12)

### Bug Fixes

- **scheduler**: Mid-session recurring crons now fire via PostToolUse hook
  ([#198](https://github.com/shawnoster/aya/pull/198),
  [`3c64401`](https://github.com/shawnoster/aya/commit/3c64401c95dae4529e79eb94771c6fc3fe564085))


## v1.26.0 (2026-04-12)

### Features

- **install**: Configurable tick interval for aya schedule install
  ([#197](https://github.com/shawnoster/aya/pull/197),
  [`0555688`](https://github.com/shawnoster/aya/commit/0555688c14a575a0e33a45ab171dfbc21f2b7beb))


## v1.25.1 (2026-04-12)

### Bug Fixes

- **cli**: Aya send validates signature and re-signs local-authored packets
  ([#196](https://github.com/shawnoster/aya/pull/196),
  [`f727d32`](https://github.com/shawnoster/aya/commit/f727d32d5a6e6253dcfa4209b1b05c8ee27d7937))

- **cli**: Aya send validates signature, re-signs local-authored packets
  ([#196](https://github.com/shawnoster/aya/pull/196),
  [`f727d32`](https://github.com/shawnoster/aya/commit/f727d32d5a6e6253dcfa4209b1b05c8ee27d7937))


## v1.25.0 (2026-04-12)

### Bug Fixes

- Address PR #195 review feedback ([#195](https://github.com/shawnoster/aya/pull/195),
  [`032ed54`](https://github.com/shawnoster/aya/commit/032ed5413477964460e85a9bfc743133568bb811))

- **identity**: Defensive validation for Profile.dropped_ids on load
  ([#195](https://github.com/shawnoster/aya/pull/195),
  [`032ed54`](https://github.com/shawnoster/aya/commit/032ed5413477964460e85a9bfc743133568bb811))

### Chores

- **deps**: Bump coincurve from 20.0.0 to 21.0.0
  ([#191](https://github.com/shawnoster/aya/pull/191),
  [`a26c7cb`](https://github.com/shawnoster/aya/commit/a26c7cb45748b5a3e069d412e2c8ed34db92cefa))

- **deps-dev**: Bump mypy from 1.19.1 to 1.20.0 ([#190](https://github.com/shawnoster/aya/pull/190),
  [`cf03035`](https://github.com/shawnoster/aya/commit/cf030353988e14375b71368522c6ab5c68fba9c5))

- **deps-dev**: Bump ruff from 0.15.8 to 0.15.9 ([#189](https://github.com/shawnoster/aya/pull/189),
  [`7746ef5`](https://github.com/shawnoster/aya/commit/7746ef56a400764d0a718f9b351a3da40d00c465))

### Documentation

- Refresh README to match real plugin and CLI behavior
  ([#194](https://github.com/shawnoster/aya/pull/194),
  [`d618d9c`](https://github.com/shawnoster/aya/commit/d618d9cb3eff308ef8e31f29a704ee32ce2d5a65))

- Refresh README to match the actual plugin and CLI behavior
  ([#194](https://github.com/shawnoster/aya/pull/194),
  [`d618d9c`](https://github.com/shawnoster/aya/commit/d618d9cb3eff308ef8e31f29a704ee32ce2d5a65))

- **plugin/relay**: Use new aya read and aya drop commands
  ([#195](https://github.com/shawnoster/aya/pull/195),
  [`032ed54`](https://github.com/shawnoster/aya/commit/032ed5413477964460e85a9bfc743133568bb811))

### Features

- **cli**: Add aya read and aya drop commands ([#195](https://github.com/shawnoster/aya/pull/195),
  [`032ed54`](https://github.com/shawnoster/aya/commit/032ed5413477964460e85a9bfc743133568bb811))


## v1.24.0 (2026-04-12)

### Bug Fixes

- **plugin/relay**: Correct failure modes table to match real CLI behavior
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))

- **plugin/relay**: Correct verb 1 (check) to match aya CLI behavior
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))

- **plugin/relay**: Correct verb 2 (read) — JSON format and metadata extraction
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))

- **plugin/relay**: Correct verb 3 (reply) — resolve recipient from DID
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))

- **plugin/relay**: Correct verb 5 (status) — actually compute pending count and honor AYA_HOME
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))

- **tests**: Make test_receive_since_lookback fixture relative to now
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))

### Chores

- Sync uv.lock to reflect version 1.23.1
  ([`317fe66`](https://github.com/shawnoster/aya/commit/317fe66f8948c30544452c8c7d0ac98ed359bfe0))

### Continuous Integration

- Drop path filters from pull_request trigger so required check always reports
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))

### Features

- **plugin**: Add /relay skill for cross-instance packet management
  ([#193](https://github.com/shawnoster/aya/pull/193),
  [`c3ca33d`](https://github.com/shawnoster/aya/commit/c3ca33df0243cc1e17ebc01867a08b445c7ed0e3))


## v1.23.1 (2026-04-03)

### Bug Fixes

- **cli**: Use explicit default severity in schedule_pending
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **install**: Address review — merge Bash hooks, silence stdout, explicit statusMessage
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Address review — correct run_tick docstring
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Address review — fetch all severities for text summary
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Address review — safe write and clear_session_lock docstring
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Annotate severity constants with AlertSeverity type
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Reduce polling noise in active sessions
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Skip polling in run_tick when session is active
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

### Documentation

- Add webhook/push support design spec ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Expand clear_session_lock docstring with design rationale
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

### Features

- **install**: Add PostToolUse hooks for silent auto-logging
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Add alert severity filtering to reduce info noise
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

- **scheduler**: Add session-aware delivery to reduce polling noise
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))

### Testing

- **scheduler**: Add session lock, severity filter, and tick deferral tests
  ([#188](https://github.com/shawnoster/aya/pull/188),
  [`f6b81d3`](https://github.com/shawnoster/aya/commit/f6b81d3f6e293c1104bf053476f08bd01c75f1a0))


## v1.23.0 (2026-04-03)

### Bug Fixes

- **install**: Address review — merge Bash hooks, silence stdout, explicit statusMessage
  ([#183](https://github.com/shawnoster/aya/pull/183),
  [`4bbeef0`](https://github.com/shawnoster/aya/commit/4bbeef0a2543b1fd58da82dd53c7c79f83cfb90d))

### Features

- **install**: Add PostToolUse hooks for silent auto-logging
  ([#183](https://github.com/shawnoster/aya/pull/183),
  [`4bbeef0`](https://github.com/shawnoster/aya/commit/4bbeef0a2543b1fd58da82dd53c7c79f83cfb90d))


## v1.22.0 (2026-04-03)

### Bug Fixes

- **config**: Address review — update help text, add env var tests
  ([#182](https://github.com/shawnoster/aya/pull/182),
  [`1f98397`](https://github.com/shawnoster/aya/commit/1f98397c5334c925ddbea787ba1fa4ce2c361697))

### Features

- **config**: Add AYA_NOTEBOOK_PATH env var fallback
  ([#182](https://github.com/shawnoster/aya/pull/182),
  [`1f98397`](https://github.com/shawnoster/aya/commit/1f98397c5334c925ddbea787ba1fa4ce2c361697))

- **config**: Add AYA_NOTEBOOK_PATH env var fallback for get_notebook_path
  ([#182](https://github.com/shawnoster/aya/pull/182),
  [`1f98397`](https://github.com/shawnoster/aya/commit/1f98397c5334c925ddbea787ba1fa4ce2c361697))


## v1.21.1 (2026-04-03)

### Bug Fixes

- **log**: Derive lock path dynamically for monkeypatch safety
  ([#181](https://github.com/shawnoster/aya/pull/181),
  [`1f62b46`](https://github.com/shawnoster/aya/commit/1f62b464122fba3ddae93b4c1642cc66211a9eef))

- **log**: Use atomic writes + file locking for log_state.json
  ([#181](https://github.com/shawnoster/aya/pull/181),
  [`1f62b46`](https://github.com/shawnoster/aya/commit/1f62b464122fba3ddae93b4c1642cc66211a9eef))


## v1.21.0 (2026-04-03)

### Bug Fixes

- **log**: Address review — naive tz, missing exists check, silent auto, enum style
  ([#178](https://github.com/shawnoster/aya/pull/178),
  [`6219f0d`](https://github.com/shawnoster/aya/commit/6219f0deeeb18e114b64990f74e9db2fcf9aa84c))

### Features

- **log**: Add aya log command for daily progress logging
  ([#178](https://github.com/shawnoster/aya/pull/178),
  [`6219f0d`](https://github.com/shawnoster/aya/commit/6219f0deeeb18e114b64990f74e9db2fcf9aa84c))

- **log**: Add log module with append, auto, and show
  ([#178](https://github.com/shawnoster/aya/pull/178),
  [`6219f0d`](https://github.com/shawnoster/aya/commit/6219f0deeeb18e114b64990f74e9db2fcf9aa84c))

### Testing

- **log**: Add CLI and unit tests for log commands
  ([#178](https://github.com/shawnoster/aya/pull/178),
  [`6219f0d`](https://github.com/shawnoster/aya/commit/6219f0deeeb18e114b64990f74e9db2fcf9aa84c))


## v1.20.1 (2026-04-03)

### Bug Fixes

- Print ingestion summary after receive --auto-ingest
  ([#175](https://github.com/shawnoster/aya/pull/175),
  [`aaa8efc`](https://github.com/shawnoster/aya/commit/aaa8efc4e3c0ab8196e735d6a869f566ff0c9df8))

- Summary to stdout (not stderr), only with --auto-ingest
  ([#175](https://github.com/shawnoster/aya/pull/175),
  [`aaa8efc`](https://github.com/shawnoster/aya/commit/aaa8efc4e3c0ab8196e735d6a869f566ff0c9df8))


## v1.20.0 (2026-04-03)

### Bug Fixes

- Validate --in-reply-to min length, add MCP test, remove unused param
  ([#174](https://github.com/shawnoster/aya/pull/174),
  [`0cd2b41`](https://github.com/shawnoster/aya/commit/0cd2b4167540838932eec43ce32b0ed28d0a526f))

### Features

- Add --in-reply-to to dispatch for threaded packet replies
  ([#174](https://github.com/shawnoster/aya/pull/174),
  [`0cd2b41`](https://github.com/shawnoster/aya/commit/0cd2b4167540838932eec43ce32b0ed28d0a526f))


## v1.19.1 (2026-04-03)

### Bug Fixes

- Add --skip-untrusted to receive for clean auto-ingest
  ([#173](https://github.com/shawnoster/aya/pull/173),
  [`e891af6`](https://github.com/shawnoster/aya/commit/e891af6ed1caac27362b436f202af68bad986fa2))

- Clarify --skip-untrusted help text (use with --auto-ingest)
  ([#173](https://github.com/shawnoster/aya/pull/173),
  [`e891af6`](https://github.com/shawnoster/aya/commit/e891af6ed1caac27362b436f202af68bad986fa2))

- Validate --skip-untrusted requires --auto-ingest or --yes
  ([#173](https://github.com/shawnoster/aya/pull/173),
  [`e891af6`](https://github.com/shawnoster/aya/commit/e891af6ed1caac27362b436f202af68bad986fa2))

### Refactoring

- Standardize logging across all modules with --verbose flag
  ([#167](https://github.com/shawnoster/aya/pull/167),
  [`1052e36`](https://github.com/shawnoster/aya/commit/1052e36f4ba6afb4be6c7a4c38397ca0c977bd23))


## v1.19.0 (2026-04-03)

### Bug Fixes

- Atomic cache writes with file locking and restricted permissions
  ([#164](https://github.com/shawnoster/aya/pull/164),
  [`98b0b4d`](https://github.com/shawnoster/aya/commit/98b0b4d597b445ec8f491b194437202094961225))

- Hash idempotency keys, reorder dry-run/dedup, consistent ack response
  ([#164](https://github.com/shawnoster/aya/pull/164),
  [`98b0b4d`](https://github.com/shawnoster/aya/commit/98b0b4d597b445ec8f491b194437202094961225))

### Features

- Add --idempotency-key for dedup on send, dispatch, and ack
  ([#164](https://github.com/shawnoster/aya/pull/164),
  [`98b0b4d`](https://github.com/shawnoster/aya/commit/98b0b4d597b445ec8f491b194437202094961225))


## v1.18.0 (2026-04-03)

### Bug Fixes

- Best-effort persistence, limit validation, safe stat, clean test patch
  ([#163](https://github.com/shawnoster/aya/pull/163),
  [`12882a0`](https://github.com/shawnoster/aya/commit/12882a0c9b1c6b0848a04ef774d530dd8c355cfc))

- Set 0o600 on packet files, 0o700 on packets dir, handle prune race
  ([#163](https://github.com/shawnoster/aya/pull/163),
  [`12882a0`](https://github.com/shawnoster/aya/commit/12882a0c9b1c6b0848a04ef774d530dd8c355cfc))

### Features

- Persist ingested packet content for later retrieval
  ([#163](https://github.com/shawnoster/aya/pull/163),
  [`12882a0`](https://github.com/shawnoster/aya/commit/12882a0c9b1c6b0848a04ef774d530dd8c355cfc))


## v1.17.2 (2026-04-03)

### Bug Fixes

- Label keypair roles in CLI output ([#162](https://github.com/shawnoster/aya/pull/162),
  [`19c0f24`](https://github.com/shawnoster/aya/commit/19c0f2449e719b91ae4c83eac7bc02489e4c6d89))

- Label keypair roles in CLI output (ed25519 vs secp256k1)
  ([#162](https://github.com/shawnoster/aya/pull/162),
  [`19c0f24`](https://github.com/shawnoster/aya/commit/19c0f2449e719b91ae4c83eac7bc02489e4c6d89))

- Make keypair annotations consistent across init, trust, and pair
  ([#162](https://github.com/shawnoster/aya/pull/162),
  [`19c0f24`](https://github.com/shawnoster/aya/commit/19c0f2449e719b91ae4c83eac7bc02489e4c6d89))


## v1.17.1 (2026-04-02)

### Bug Fixes

- Add receive contract test and fix remind docstring
  ([#160](https://github.com/shawnoster/aya/pull/160),
  [`556fbfa`](https://github.com/shawnoster/aya/commit/556fbfa6c33e92e108309c80d8eb9bc48a8a59c9))

- Standardize JSON output shapes (#159) ([#160](https://github.com/shawnoster/aya/pull/160),
  [`556fbfa`](https://github.com/shawnoster/aya/commit/556fbfa6c33e92e108309c80d8eb9bc48a8a59c9))

- Standardize JSON output shapes with consistent top-level wrappers
  ([#160](https://github.com/shawnoster/aya/pull/160),
  [`556fbfa`](https://github.com/shawnoster/aya/commit/556fbfa6c33e92e108309c80d8eb9bc48a8a59c9))


## v1.17.0 (2026-04-02)

### Features

- Add /aya-status skill for Ship Mind readiness check
  ([`48eef63`](https://github.com/shawnoster/aya/commit/48eef63433bbd4f335156c5be873a0a1526f8d14))


## v1.16.0 (2026-04-02)

### Bug Fixes

- Accept raw DIDs in send, handle Z timestamps, set encrypted on ack
  ([#154](https://github.com/shawnoster/aya/pull/154),
  [`8ffcf02`](https://github.com/shawnoster/aya/commit/8ffcf0269239a87a02c9bf4f49ed94427a99dc70))

- Add trust check to _resolve_did, instance param to ack, inbox/ack tests
  ([#154](https://github.com/shawnoster/aya/pull/154),
  [`8ffcf02`](https://github.com/shawnoster/aya/commit/8ffcf0269239a87a02c9bf4f49ed94427a99dc70))

- Correct type: ignore comment in _dt_now (union-attr → no-any-return)
  ([#153](https://github.com/shawnoster/aya/pull/153),
  [`83d58c3`](https://github.com/shawnoster/aya/commit/83d58c3f9da92f8290bf6225af0002ac4d266546))

- Resolve mypy errors, add None guard for ack pubkey, fix syntax
  ([#154](https://github.com/shawnoster/aya/pull/154),
  [`8ffcf02`](https://github.com/shawnoster/aya/commit/8ffcf0269239a87a02c9bf4f49ed94427a99dc70))

- Update docstrings to aya schedule, use _ALERT_MAX_AGE_DAYS constant, remove stale config
  ([#153](https://github.com/shawnoster/aya/pull/153),
  [`83d58c3`](https://github.com/shawnoster/aya/commit/83d58c3f9da92f8290bf6225af0002ac4d266546))

### Features

- Add MCP server exposing aya capabilities as Claude-native tools
  ([#154](https://github.com/shawnoster/aya/pull/154),
  [`8ffcf02`](https://github.com/shawnoster/aya/commit/8ffcf0269239a87a02c9bf4f49ed94427a99dc70))

### Refactoring

- Split scheduler.py into layered submodules ([#153](https://github.com/shawnoster/aya/pull/153),
  [`83d58c3`](https://github.com/shawnoster/aya/commit/83d58c3f9da92f8290bf6225af0002ac4d266546))


## v1.15.0 (2026-04-02)

### Bug Fixes

- Pair emits pairing_code in JSON, suppress _ingest stdout, use ErrorCode constant
  ([#152](https://github.com/shawnoster/aya/pull/152),
  [`db3a199`](https://github.com/shawnoster/aya/commit/db3a19924bbe77178f540850bb9bbde64a9f1304))

- Prevent mixed Rich/JSON output in pair and handle edge cases
  ([#152](https://github.com/shawnoster/aya/pull/152),
  [`db3a199`](https://github.com/shawnoster/aya/commit/db3a19924bbe77178f540850bb9bbde64a9f1304))

### Features

- Add --format json to all mutating CLI commands
  ([#152](https://github.com/shawnoster/aya/pull/152),
  [`db3a199`](https://github.com/shawnoster/aya/commit/db3a19924bbe77178f540850bb9bbde64a9f1304))


## v1.14.0 (2026-04-02)

### Bug Fixes

- Remove dead code in pair, add NoReturn type, fix pack seed error
  ([#151](https://github.com/shawnoster/aya/pull/151),
  [`ab7fa7f`](https://github.com/shawnoster/aya/commit/ab7fa7faf457c63fc08d09583fdc81fab79334b2))

- Use AYA_FORMAT for error mode detection and add default=str safety
  ([#151](https://github.com/shawnoster/aya/pull/151),
  [`ab7fa7f`](https://github.com/shawnoster/aya/commit/ab7fa7faf457c63fc08d09583fdc81fab79334b2))

### Features

- Add structured JSON error model on stderr ([#151](https://github.com/shawnoster/aya/pull/151),
  [`ab7fa7f`](https://github.com/shawnoster/aya/commit/ab7fa7faf457c63fc08d09583fdc81fab79334b2))


## v1.13.0 (2026-04-02)

### Bug Fixes

- Add validation before dry-run and complete test coverage
  ([#150](https://github.com/shawnoster/aya/pull/150),
  [`38b7838`](https://github.com/shawnoster/aya/commit/38b7838350670ed5938bfbf33762107dd2645c9a))

- Use _output_json for dry-run output and strengthen test assertions
  ([#150](https://github.com/shawnoster/aya/pull/150),
  [`38b7838`](https://github.com/shawnoster/aya/commit/38b7838350670ed5938bfbf33762107dd2645c9a))

### Features

- Add --dry-run to relay-publishing and state-mutating commands
  ([#150](https://github.com/shawnoster/aya/pull/150),
  [`38b7838`](https://github.com/shawnoster/aya/commit/38b7838350670ed5938bfbf33762107dd2645c9a))

- Add --dry-run to send, dispatch, ack, pair, and schedule commands
  ([#150](https://github.com/shawnoster/aya/pull/150),
  [`38b7838`](https://github.com/shawnoster/aya/commit/38b7838350670ed5938bfbf33762107dd2645c9a))


## v1.12.0 (2026-04-02)

### Bug Fixes

- Address review feedback on packet schema spec ([#148](https://github.com/shawnoster/aya/pull/148),
  [`4f0fbb7`](https://github.com/shawnoster/aya/commit/4f0fbb79e96375e18735944abc61f0c0b3c8ca3a))

- Correct version compat claim — unknown major warns, does not reject
  ([#148](https://github.com/shawnoster/aya/pull/148),
  [`4f0fbb7`](https://github.com/shawnoster/aya/commit/4f0fbb79e96375e18735944abc61f0c0b3c8ca3a))

- Resolve mypy errors in schema_version helpers ([#149](https://github.com/shawnoster/aya/pull/149),
  [`e6c79b5`](https://github.com/shawnoster/aya/commit/e6c79b5bcf7bcc77acb5aabaeaac80494cf2617f))

- Validate schema_version type, extract helper, fix test docstrings
  ([#149](https://github.com/shawnoster/aya/pull/149),
  [`e6c79b5`](https://github.com/shawnoster/aya/commit/e6c79b5bcf7bcc77acb5aabaeaac80494cf2617f))

### Documentation

- Publish packet envelope schema specification ([#148](https://github.com/shawnoster/aya/pull/148),
  [`4f0fbb7`](https://github.com/shawnoster/aya/commit/4f0fbb79e96375e18735944abc61f0c0b3c8ca3a))

### Features

- Add schema_version to persistent JSON files ([#149](https://github.com/shawnoster/aya/pull/149),
  [`e6c79b5`](https://github.com/shawnoster/aya/commit/e6c79b5bcf7bcc77acb5aabaeaac80494cf2617f))


## v1.11.2 (2026-04-02)

### Bug Fixes

- Add debug logging to scheduler tick, poll, and cron paths
  ([#147](https://github.com/shawnoster/aya/pull/147),
  [`0944b7c`](https://github.com/shawnoster/aya/commit/0944b7c8ef36a4e06220c59cfe81cdcc0df92040))


## v1.11.1 (2026-04-02)

### Bug Fixes

- Guard missing due_at in check_due and clarify AlertDetails cast
  ([#144](https://github.com/shawnoster/aya/pull/144),
  [`bbcbef8`](https://github.com/shawnoster/aya/commit/bbcbef895bde7ee5291e9dfe40ad4de0810223ed))

- Store sender DID in ingested_ids for reliable ACK routing
  ([#146](https://github.com/shawnoster/aya/pull/146),
  [`242d04d`](https://github.com/shawnoster/aya/commit/242d04d587fc372c1765b2d9d453816e142e5973))

- Use if-False-yield pattern for empty async generator stubs
  ([#145](https://github.com/shawnoster/aya/pull/145),
  [`8036395`](https://github.com/shawnoster/aya/commit/8036395af3541f71ef3d1c074e08acfe202bcdd4))

### Refactoring

- Add TypedDict schemas for Scheduler state ([#130](https://github.com/shawnoster/aya/pull/130),
  [`0b34a7d`](https://github.com/shawnoster/aya/commit/0b34a7d5dff31e730413886304f29900c508d723))

- Add TypedDict schemas for Scheduler state (#109)
  ([#130](https://github.com/shawnoster/aya/pull/130),
  [`0b34a7d`](https://github.com/shawnoster/aya/commit/0b34a7d5dff31e730413886304f29900c508d723))

- Narrow WatchState union access and remove scheduler mypy override
  ([#144](https://github.com/shawnoster/aya/pull/144),
  [`bbcbef8`](https://github.com/shawnoster/aya/commit/bbcbef895bde7ee5291e9dfe40ad4de0810223ed))

- Tighten TypedDict types and remove type: ignore in scheduler
  ([#130](https://github.com/shawnoster/aya/pull/130),
  [`0b34a7d`](https://github.com/shawnoster/aya/commit/0b34a7d5dff31e730413886304f29900c508d723))

### Testing

- Add --instance deprecation coverage for relay commands
  ([#145](https://github.com/shawnoster/aya/pull/145),
  [`8036395`](https://github.com/shawnoster/aya/commit/8036395af3541f71ef3d1c074e08acfe202bcdd4))

- Add --instance deprecation warning coverage for send/dispatch/receive/inbox
  ([#145](https://github.com/shawnoster/aya/pull/145),
  [`8036395`](https://github.com/shawnoster/aya/commit/8036395af3541f71ef3d1c074e08acfe202bcdd4))


## v1.11.0 (2026-04-01)

### Bug Fixes

- Wire-compat, type annotation, and prefix length for ack command
  ([#129](https://github.com/shawnoster/aya/pull/129),
  [`3c3d69e`](https://github.com/shawnoster/aya/commit/3c3d69e87fc6a6d6a74b2a15074bc78e5d7bf489))

### Features

- Add aya ack command for cross-instance packet acknowledgment
  ([#129](https://github.com/shawnoster/aya/pull/129),
  [`3c3d69e`](https://github.com/shawnoster/aya/commit/3c3d69e87fc6a6d6a74b2a15074bc78e5d7bf489))

- Add aya ack command for cross-instance packet acknowledgment (#103)
  ([#129](https://github.com/shawnoster/aya/pull/129),
  [`3c3d69e`](https://github.com/shawnoster/aya/commit/3c3d69e87fc6a6d6a74b2a15074bc78e5d7bf489))


## v1.10.4 (2026-04-01)

### Bug Fixes

- Add deprecation warnings for --label and --instance flags
  ([#128](https://github.com/shawnoster/aya/pull/128),
  [`9314861`](https://github.com/shawnoster/aya/commit/931486174f44f3b9dd85daab7be6d73070c43462))

- Error on conflicting legacy and current flags, add conflict test
  ([#128](https://github.com/shawnoster/aya/pull/128),
  [`9314861`](https://github.com/shawnoster/aya/commit/931486174f44f3b9dd85daab7be6d73070c43462))


## v1.10.3 (2026-04-01)

### Bug Fixes

- Improve pairing error message and add retry backoff (#115)
  ([#127](https://github.com/shawnoster/aya/pull/127),
  [`c032e71`](https://github.com/shawnoster/aya/commit/c032e71e8692d071d17ceace1304966fe23a5771))


## v1.10.2 (2026-04-01)

### Bug Fixes

- Add logging to silent exception handlers ([#126](https://github.com/shawnoster/aya/pull/126),
  [`72bc9c9`](https://github.com/shawnoster/aya/commit/72bc9c9751fbf34a96f6bf814a2a888575f5a9f4))

- Add logging to silent exception handlers (#112)
  ([#126](https://github.com/shawnoster/aya/pull/126),
  [`72bc9c9`](https://github.com/shawnoster/aya/commit/72bc9c9751fbf34a96f6bf814a2a888575f5a9f4))

- Include exc_info in verification warnings and clarify dispatch error message
  ([#126](https://github.com/shawnoster/aya/pull/126),
  [`72bc9c9`](https://github.com/shawnoster/aya/commit/72bc9c9751fbf34a96f6bf814a2a888575f5a9f4))


## v1.10.1 (2026-04-01)

### Bug Fixes

- Align docstring with behavior and guard non-string id in normalize
  ([#125](https://github.com/shawnoster/aya/pull/125),
  [`82536c4`](https://github.com/shawnoster/aya/commit/82536c40034c1497d1afb1c0f384519496640c1d))

- Only store full ULID in ingested_ids, strip truncated entries on load
  ([#125](https://github.com/shawnoster/aya/pull/125),
  [`82536c4`](https://github.com/shawnoster/aya/commit/82536c40034c1497d1afb1c0f384519496640c1d))

- Only store full ULID in ingested_ids, strip truncated entries on load (#123)
  ([#125](https://github.com/shawnoster/aya/pull/125),
  [`82536c4`](https://github.com/shawnoster/aya/commit/82536c40034c1497d1afb1c0f384519496640c1d))

### Refactoring

- Simplify ULID validation and tighten migration guard
  ([#125](https://github.com/shawnoster/aya/pull/125),
  [`82536c4`](https://github.com/shawnoster/aya/commit/82536c40034c1497d1afb1c0f384519496640c1d))


## v1.10.0 (2026-04-01)

### Bug Fixes

- Address Copilot review feedback on PR #124 ([#124](https://github.com/shawnoster/aya/pull/124),
  [`3f68142`](https://github.com/shawnoster/aya/commit/3f6814274f3c108803ec533a31db7de6334a4b1e))

### Features

- Add workspace config command and aya context output
  ([#124](https://github.com/shawnoster/aya/pull/124),
  [`3f68142`](https://github.com/shawnoster/aya/commit/3f6814274f3c108803ec533a31db7de6334a4b1e))

- Limit receive fetch window using last_checked lookback
  ([#124](https://github.com/shawnoster/aya/pull/124),
  [`3f68142`](https://github.com/shawnoster/aya/commit/3f6814274f3c108803ec533a31db7de6334a4b1e))

- Limit receive fetch window using last_checked lookback (#46)
  ([#124](https://github.com/shawnoster/aya/pull/124),
  [`3f68142`](https://github.com/shawnoster/aya/commit/3f6814274f3c108803ec533a31db7de6334a4b1e))

### Testing

- Add receive since_lookback and seed alert tests
  ([#124](https://github.com/shawnoster/aya/pull/124),
  [`3f68142`](https://github.com/shawnoster/aya/commit/3f6814274f3c108803ec533a31db7de6334a4b1e))


## v1.9.0 (2026-03-31)

### Features

- Add /aya-install skill for global reinstallation
  ([#121](https://github.com/shawnoster/aya/pull/121),
  [`94ad7e5`](https://github.com/shawnoster/aya/commit/94ad7e5b94fa5f1304bbe90d2701edb75b471e20))

### Refactoring

- Move aya-refresh command to .claude/commands (from .claude-plugin/skills)
  ([#121](https://github.com/shawnoster/aya/pull/121),
  [`94ad7e5`](https://github.com/shawnoster/aya/commit/94ad7e5b94fa5f1304bbe90d2701edb75b471e20))


## v1.8.0 (2026-03-31)

### Bug Fixes

- Address PR #120 review feedback ([#120](https://github.com/shawnoster/aya/pull/120),
  [`111bbef`](https://github.com/shawnoster/aya/commit/111bbef29055620ffe8380536feb3a55db0a912d))

### Documentation

- Mark async functions and add usage examples ([#120](https://github.com/shawnoster/aya/pull/120),
  [`111bbef`](https://github.com/shawnoster/aya/commit/111bbef29055620ffe8380536feb3a55db0a912d))

### Features

- Add /aya-install skill for global reinstallation
  ([`8cd8f64`](https://github.com/shawnoster/aya/commit/8cd8f6460c7b7f73ce1327c8065f44b74bf4fff6))


## v1.7.0 (2026-03-31)

### Bug Fixes

- Improve _validate_instance error message clarity
  ([#119](https://github.com/shawnoster/aya/pull/119),
  [`bb7f5cc`](https://github.com/shawnoster/aya/commit/bb7f5cce9749f924efc7fd3664917f2907278b19))

- Normalize AYA_TZ env var and add comprehensive timezone tests
  ([#119](https://github.com/shawnoster/aya/pull/119),
  [`bb7f5cc`](https://github.com/shawnoster/aya/commit/bb7f5cce9749f924efc7fd3664917f2907278b19))

### Features

- Add timezone configuration support via AYA_TZ env var
  ([#119](https://github.com/shawnoster/aya/pull/119),
  [`bb7f5cc`](https://github.com/shawnoster/aya/commit/bb7f5cce9749f924efc7fd3664917f2907278b19))


## v1.6.6 (2026-03-31)

### Bug Fixes

- Add missing type parameter to dict annotations in identity.py
  ([#118](https://github.com/shawnoster/aya/pull/118),
  [`0aa18e4`](https://github.com/shawnoster/aya/commit/0aa18e4cda4ffd3a04b27af56fc4e955e75d1e4d))

- Add validation on profile load — prevent silent corruption
  ([#118](https://github.com/shawnoster/aya/pull/118),
  [`0aa18e4`](https://github.com/shawnoster/aya/commit/0aa18e4cda4ffd3a04b27af56fc4e955e75d1e4d))

- Convert RelayClient.relay_url to property ([#118](https://github.com/shawnoster/aya/pull/118),
  [`0aa18e4`](https://github.com/shawnoster/aya/commit/0aa18e4cda4ffd3a04b27af56fc4e955e75d1e4d))

- Correct setup-uv action parameter name from python-version-file to version-file
  ([#118](https://github.com/shawnoster/aya/pull/118),
  [`0aa18e4`](https://github.com/shawnoster/aya/commit/0aa18e4cda4ffd3a04b27af56fc4e955e75d1e4d))

- Remove version-file parameter from setup-uv action
  ([#118](https://github.com/shawnoster/aya/pull/118),
  [`0aa18e4`](https://github.com/shawnoster/aya/commit/0aa18e4cda4ffd3a04b27af56fc4e955e75d1e4d))

### Refactoring

- Add defensive type checks in Profile.load() ([#118](https://github.com/shawnoster/aya/pull/118),
  [`0aa18e4`](https://github.com/shawnoster/aya/commit/0aa18e4cda4ffd3a04b27af56fc4e955e75d1e4d))


## v1.6.5 (2026-03-31)

### Bug Fixes

- Convert RelayClient.relay_url to property ([#117](https://github.com/shawnoster/aya/pull/117),
  [`815d6e4`](https://github.com/shawnoster/aya/commit/815d6e417dcf0c059a9fb44935db95fe0294c855))


## v1.6.4 (2026-03-31)

### Bug Fixes

- Implement _display_items() to print formatted scheduler output
  ([`6d39096`](https://github.com/shawnoster/aya/commit/6d3909619d1c22d89370fd73595618838101378e))

- Make scheduler getters robust to malformed timestamps and incorporate degraded state into checks.
  ([#116](https://github.com/shawnoster/aya/pull/116),
  [`8a26179`](https://github.com/shawnoster/aya/commit/8a261791d469650ddfd20f0b77f35424b2e7b272))

- Shorten line to pass E501 lint check
  ([`a8b5ad5`](https://github.com/shawnoster/aya/commit/a8b5ad50e3ae0d3f5459747d7f80c6dc34a6d62d))

### Chores

- Update uv.lock
  ([`cf0d750`](https://github.com/shawnoster/aya/commit/cf0d750807f8580e2ad9c8a07bb1fc49b7d166f5))

### Documentation

- Streamline scheduler flow documentation
  ([`edb3e2e`](https://github.com/shawnoster/aya/commit/edb3e2e6b2bb1cb49af5e1437d625be33091fef0))

### Performance Improvements

- Optimize hot path and add error logging
  ([`97b96b6`](https://github.com/shawnoster/aya/commit/97b96b63303d148e7792d997d38319c6fa774d0c))

### Refactoring

- Add scheduler constants and filter helpers
  ([`b20e8b1`](https://github.com/shawnoster/aya/commit/b20e8b156b8a9fe5733f022a3cac45937abb7f6f))

- Extract change detection logic into strategy dict
  ([`1e714a2`](https://github.com/shawnoster/aya/commit/1e714a2fac17ddf3ab74926d290ff6d479696102))

- Extract infrastructure helpers (_load_collection_unlocked, _create_alert, _get_jira_credentials)
  ([`462878b`](https://github.com/shawnoster/aya/commit/462878b4c97f0795ac1ab523a5a55e5503cd8723))

- Simplify CLI, status, and install modules ([#116](https://github.com/shawnoster/aya/pull/116),
  [`8a26179`](https://github.com/shawnoster/aya/commit/8a261791d469650ddfd20f0b77f35424b2e7b272))


## v1.6.3 (2026-03-31)

### Chores

- Update pre-commit hook from legacy ruff to ruff-check
  ([`fa40551`](https://github.com/shawnoster/aya/commit/fa405519e668e5f6465ae1779c22312f2a591fb8))

### Continuous Integration

- Use .python-version file in release workflow
  ([`4a8335f`](https://github.com/shawnoster/aya/commit/4a8335f8aa3520dd8e69c69cf6ba8558b8e22ecf))

- Use .python-version file instead of hardcoded version
  ([`6bbed71`](https://github.com/shawnoster/aya/commit/6bbed712bff9e2266e7c0289111cb72acc2bdc92))

### Performance Improvements

- Replace double JSON serialization with direct dict comparison
  ([`ff6145b`](https://github.com/shawnoster/aya/commit/ff6145ba6645ad793de76e5017abf8d1cde101e3))

### Refactoring

- Rename --tag to --tags for semantic clarity
  ([`bb85afc`](https://github.com/shawnoster/aya/commit/bb85afcea1e5a29542d641b745382a8393158a82))

- Simplify CLI JSON handling and eliminate duplication
  ([`4aae9d9`](https://github.com/shawnoster/aya/commit/4aae9d9b284a407bd241967de89753098c0880b7))


## v1.6.2 (2026-03-31)

### Bug Fixes

- Pair command stores peer DID under --peer label instead of local label
  ([#106](https://github.com/shawnoster/aya/pull/106),
  [`cd1e9b9`](https://github.com/shawnoster/aya/commit/cd1e9b93a2f5bb0afab6296ca1852ac0a637f1ea))

- Pair command stores peer DID under --peer label, not local label
  ([#106](https://github.com/shawnoster/aya/pull/106),
  [`cd1e9b9`](https://github.com/shawnoster/aya/commit/cd1e9b93a2f5bb0afab6296ca1852ac0a637f1ea))

- Remove unused label parameter from join_pairing
  ([#106](https://github.com/shawnoster/aya/pull/106),
  [`cd1e9b9`](https://github.com/shawnoster/aya/commit/cd1e9b93a2f5bb0afab6296ca1852ac0a637f1ea))

### Chores

- Relax requires-python to >=3.12 for prebuilt coincurve wheels
  ([#106](https://github.com/shawnoster/aya/pull/106),
  [`cd1e9b9`](https://github.com/shawnoster/aya/commit/cd1e9b93a2f5bb0afab6296ca1852ac0a637f1ea))

- **deps**: Document coincurve <21 pin rationale (see #101)
  ([`1428f20`](https://github.com/shawnoster/aya/commit/1428f20d2a95dd427331d9578c7e656220f0e37b))

### Documentation

- Document coincurve <21 pin in CHANGELOG ([#102](https://github.com/shawnoster/aya/pull/102),
  [`88620ca`](https://github.com/shawnoster/aya/commit/88620ca3444453043eb4b9af6b63a2361a66b6fc))

- Generalize pairing examples and update for NIP-44 encryption
  ([`bc91997`](https://github.com/shawnoster/aya/commit/bc91997e3667b6f7d4ccfa8babcc9561f19db1d0))

- **changelog**: Add entry for coincurve <21 pin (closes #101)"
  ([#102](https://github.com/shawnoster/aya/pull/102),
  [`88620ca`](https://github.com/shawnoster/aya/commit/88620ca3444453043eb4b9af6b63a2361a66b6fc))


## v1.6.1 (2026-03-30)

### Bug Fixes

- **deps**: Pin coincurve <21 — v21.0.0 fails to build (missing LICENSE in cffi)
  ([`11a1e30`](https://github.com/shawnoster/aya/commit/11a1e3045e0d20a9d586691830fc74a92327f890))


## v1.6.0 (2026-03-30)

### Bug Fixes

- Address Copilot review — mock relay in test, show resolved label in output
  ([`72e2ff8`](https://github.com/shawnoster/aya/commit/72e2ff899b729a31741e829494dcafd1b5d95edb))

- **encryption**: Address Copilot review feedback on PR #100
  ([#100](https://github.com/shawnoster/aya/pull/100),
  [`e01084e`](https://github.com/shawnoster/aya/commit/e01084e3c9b5326ebadefdcae7b2f6ce2ee8ac03))

### Features

- **encryption**: Implement NIP-44 v2 packet encryption for public relay privacy
  ([#100](https://github.com/shawnoster/aya/pull/100),
  [`e01084e`](https://github.com/shawnoster/aya/commit/e01084e3c9b5326ebadefdcae7b2f6ce2ee8ac03))

- **encryption**: NIP-44 v2 packet encryption for public relay privacy
  ([#100](https://github.com/shawnoster/aya/pull/100),
  [`e01084e`](https://github.com/shawnoster/aya/commit/e01084e3c9b5326ebadefdcae7b2f6ce2ee8ac03))


## v1.5.0 (2026-03-30)

### Bug Fixes

- Hermetic auto-format tests and full contract test isolation
  ([#98](https://github.com/shawnoster/aya/pull/98),
  [`46a4a2d`](https://github.com/shawnoster/aya/commit/46a4a2de9f15a0ecb2fa1fe76365d8dc82eb73cb))

### Features

- JSON default output for non-TTY contexts ([#98](https://github.com/shawnoster/aya/pull/98),
  [`46a4a2d`](https://github.com/shawnoster/aya/commit/46a4a2de9f15a0ecb2fa1fe76365d8dc82eb73cb))

- Make JSON the default output format for non-TTY contexts
  ([#98](https://github.com/shawnoster/aya/pull/98),
  [`46a4a2d`](https://github.com/shawnoster/aya/commit/46a4a2de9f15a0ecb2fa1fe76365d8dc82eb73cb))

### Testing

- Add JSON output contract tests for AI consumers ([#98](https://github.com/shawnoster/aya/pull/98),
  [`46a4a2d`](https://github.com/shawnoster/aya/commit/46a4a2de9f15a0ecb2fa1fe76365d8dc82eb73cb))


## v1.4.2 (2026-03-30)

### Bug Fixes

- Address review comments — inclusive cursor, no-progress guard, default since, linting
  ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

- Paginate relay fetch to avoid silently missing packets beyond limit
  ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

- Paginate relay fetch to eliminate silent packet loss beyond fetch window
  ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

- Sort imports in test_relay.py to satisfy ruff I001
  ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

- Update fetch_pending docstring to reflect 7-day default bound (PR #96)
  ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

- Use inclusive pagination cursor with dedup, cap unbounded scans
  ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

### Chores

- Regenerate uv.lock to fix idna source field error
  ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

- Update uv.lock package version to 1.4.0 ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))

### Code Style

- Format relay.py for ruff 0.15.8 ([#96](https://github.com/shawnoster/aya/pull/96),
  [`0c30c91`](https://github.com/shawnoster/aya/commit/0c30c916d1d0f0a095e69a142c8813d4bbef66f3))


## v1.4.1 (2026-03-30)

### Bug Fixes

- Prune ingested_ids by 7-day TTL instead of count cap of 100
  ([#95](https://github.com/shawnoster/aya/pull/95),
  [`cf78183`](https://github.com/shawnoster/aya/commit/cf781831f747a0c3c84c1dde8e337148104399ec))

- Use datetime parsing for TTL prune, dynamic timestamps in tests
  ([#95](https://github.com/shawnoster/aya/pull/95),
  [`cf78183`](https://github.com/shawnoster/aya/commit/cf781831f747a0c3c84c1dde8e337148104399ec))


## v1.4.0 (2026-03-30)

### Bug Fixes

- Document legacy aliases and include --as in pair output
  ([#91](https://github.com/shawnoster/aya/pull/91),
  [`9cfbaea`](https://github.com/shawnoster/aya/commit/9cfbaea95c119761f379a24debd7368e3cc787a4))

### Documentation

- Fix stale install steps and add plugin references
  ([#91](https://github.com/shawnoster/aya/pull/91),
  [`9cfbaea`](https://github.com/shawnoster/aya/commit/9cfbaea95c119761f379a24debd7368e3cc787a4))

- Self-hosted Nostr relay on Synology NAS ([#87](https://github.com/shawnoster/aya/pull/87),
  [`efb6cd9`](https://github.com/shawnoster/aya/commit/efb6cd9e9ec7d9512c8744d716e12a4d162e5b3e))

- Update slash commands and docs for --as/--peer rename
  ([#91](https://github.com/shawnoster/aya/pull/91),
  [`9cfbaea`](https://github.com/shawnoster/aya/commit/9cfbaea95c119761f379a24debd7368e3cc787a4))

- **relay**: Fix three inaccuracies flagged in review
  ([#87](https://github.com/shawnoster/aya/pull/87),
  [`efb6cd9`](https://github.com/shawnoster/aya/commit/efb6cd9e9ec7d9512c8744d716e12a4d162e5b3e))

### Features

- Add Claude Code plugin with 5 slash commands ([#91](https://github.com/shawnoster/aya/pull/91),
  [`9cfbaea`](https://github.com/shawnoster/aya/commit/9cfbaea95c119761f379a24debd7368e3cc787a4))

- Add Claude Code plugin with slash commands ([#91](https://github.com/shawnoster/aya/pull/91),
  [`9cfbaea`](https://github.com/shawnoster/aya/commit/9cfbaea95c119761f379a24debd7368e3cc787a4))

### Refactoring

- **cli**: Rename --instance to --as, --label to --peer for remote contexts
  ([#91](https://github.com/shawnoster/aya/pull/91),
  [`9cfbaea`](https://github.com/shawnoster/aya/commit/9cfbaea95c119761f379a24debd7368e3cc787a4))


## v1.3.1 (2026-03-29)

### Bug Fixes

- Address Copilot review feedback ([#85](https://github.com/shawnoster/aya/pull/85),
  [`50ff734`](https://github.com/shawnoster/aya/commit/50ff734fd630e599dcb9ebb3f782b679bcc8516d))

- **hooks**: Emit one hookSpecificOutput per session cron
  ([#85](https://github.com/shawnoster/aya/pull/85),
  [`50ff734`](https://github.com/shawnoster/aya/commit/50ff734fd630e599dcb9ebb3f782b679bcc8516d))


## v1.3.0 (2026-03-29)

### Bug Fixes

- **tests**: Update test_status_json_is_valid to use --format json
  ([#83](https://github.com/shawnoster/aya/pull/83),
  [`a8f2aa2`](https://github.com/shawnoster/aya/commit/a8f2aa26519e03b53c6b6da67c8afd22288ce1ad))

### Features

- **cli**: Standardize --format json across all output commands
  ([#83](https://github.com/shawnoster/aya/pull/83),
  [`a8f2aa2`](https://github.com/shawnoster/aya/commit/a8f2aa26519e03b53c6b6da67c8afd22288ce1ad))

- **inbox**: Add --format json option for token-efficient output
  ([#83](https://github.com/shawnoster/aya/pull/83),
  [`a8f2aa2`](https://github.com/shawnoster/aya/commit/a8f2aa26519e03b53c6b6da67c8afd22288ce1ad))

### Refactoring

- **cli**: Use OutputFormat enum for --format option; fix stale docs
  ([#83](https://github.com/shawnoster/aya/pull/83),
  [`a8f2aa2`](https://github.com/shawnoster/aya/commit/a8f2aa26519e03b53c6b6da67c8afd22288ce1ad))


## v1.2.0 (2026-03-29)

### Bug Fixes

- Address PR review — tighten hook detection, surface corrupt JSON
  ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))

- Resolve mypy errors in install module ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))

### Documentation

- Add idle tracking architecture review with use cases
  ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))

- Document schedule install and activity hooks ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))

### Features

- Add `aya schedule install` / `uninstall` for one-command setup
  ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))

- Add aya schedule install / uninstall ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))

- Wire install/uninstall commands into schedule CLI
  ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))

### Testing

- Add install/uninstall tests — hooks, crontab, CLI, roundtrip
  ([#81](https://github.com/shawnoster/aya/pull/81),
  [`cf45eba`](https://github.com/shawnoster/aya/commit/cf45eba83591b1c7a00a51acebfd3f1b15fe847d))


## v1.1.1 (2026-03-29)

### Bug Fixes

- Smart --instance default + improved error messages + docs
  ([`2618649`](https://github.com/shawnoster/aya/commit/261864988308e22c690edec367cd0c02d611edd1))

- **relay**: Skip pairing events in fetch_pending ([#80](https://github.com/shawnoster/aya/pull/80),
  [`3265a54`](https://github.com/shawnoster/aya/commit/3265a548e00b8c03d5b10205f0dde6951c63851d))

- **relay**: Skip pairing events in fetch_pending to prevent parse errors
  ([#80](https://github.com/shawnoster/aya/pull/80),
  [`3265a54`](https://github.com/shawnoster/aya/commit/3265a548e00b8c03d5b10205f0dde6951c63851d))

### Code Style

- Apply ruff format to test_cli.py
  ([`2618649`](https://github.com/shawnoster/aya/commit/261864988308e22c690edec367cd0c02d611edd1))

### Documentation

- Add one-prompt setup guide and relay polling ([#76](https://github.com/shawnoster/aya/pull/76),
  [`c275030`](https://github.com/shawnoster/aya/commit/c275030ddeae6cac24e9ee0afae5af711684c565))

- Add one-prompt setup guide and relay polling examples
  ([#76](https://github.com/shawnoster/aya/pull/76),
  [`c275030`](https://github.com/shawnoster/aya/commit/c275030ddeae6cac24e9ee0afae5af711684c565))

- Address Copilot review feedback on one-prompt setup
  ([#76](https://github.com/shawnoster/aya/pull/76),
  [`c275030`](https://github.com/shawnoster/aya/commit/c275030ddeae6cac24e9ee0afae5af711684c565))

### Refactoring

- **relay**: Promote pair tag strings to module-level constants
  ([#80](https://github.com/shawnoster/aya/pull/80),
  [`3265a54`](https://github.com/shawnoster/aya/commit/3265a548e00b8c03d5b10205f0dde6951c63851d))

### Testing

- Fix test_dispatch_missing_instance_fails for smart-default behavior
  ([`2618649`](https://github.com/shawnoster/aya/commit/261864988308e22c690edec367cd0c02d611edd1))

- Strengthen multiple-instance error assertion to require all names
  ([`2618649`](https://github.com/shawnoster/aya/commit/261864988308e22c690edec367cd0c02d611edd1))

- **cli**: Fix PT018 lint, add zero-instance test; docs: --yes in AGENTS.md
  ([`2618649`](https://github.com/shawnoster/aya/commit/261864988308e22c690edec367cd0c02d611edd1))


## v1.1.0 (2026-03-29)

### Bug Fixes

- **ci**: Add paths-ignore to prevent release loop; drop pull-requests permission
  ([#73](https://github.com/shawnoster/aya/pull/73),
  [`216523d`](https://github.com/shawnoster/aya/commit/216523da085f90fb4681daa086436051a2757ca3))

- **release**: Filter PSR bump commits via job condition, not paths-ignore
  ([#73](https://github.com/shawnoster/aya/pull/73),
  [`216523d`](https://github.com/shawnoster/aya/commit/216523da085f90fb4681daa086436051a2757ca3))

### Chores

- Automate PSR version bumping on push to main, relax requires-python
  ([#73](https://github.com/shawnoster/aya/pull/73),
  [`216523d`](https://github.com/shawnoster/aya/commit/216523da085f90fb4681daa086436051a2757ca3))

- Automate version bumping via Python Semantic Release on merge to main
  ([#73](https://github.com/shawnoster/aya/pull/73),
  [`216523d`](https://github.com/shawnoster/aya/commit/216523da085f90fb4681daa086436051a2757ca3))

### Features

- Add --yes/-y flag to receive command for non-interactive mode
  ([#74](https://github.com/shawnoster/aya/pull/74),
  [`f30e9b2`](https://github.com/shawnoster/aya/commit/f30e9b24ad85812b1f918218d00d07974a281fff))

- Add --yes/-y flag to receive for non-interactive mode
  ([#74](https://github.com/shawnoster/aya/pull/74),
  [`f30e9b2`](https://github.com/shawnoster/aya/commit/f30e9b24ad85812b1f918218d00d07974a281fff))

### Testing

- Use untrusted sender in -y short flag test ([#74](https://github.com/shawnoster/aya/pull/74),
  [`f30e9b2`](https://github.com/shawnoster/aya/commit/f30e9b24ad85812b1f918218d00d07974a281fff))


## v1.0.0 (2026-03-29)

- Initial Release
