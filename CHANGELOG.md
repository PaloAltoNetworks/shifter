# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2025-12-04

### Added
- SonarCloud integration
- Build and test workflow
- Quality gate badge to README

### Fixed
- npm version mismatch

### Changed
- Upgraded vitest from 1.x to 4.x (required code changes to test files due to breaking changes)
## [0.1.0] - 2024-12-04

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

