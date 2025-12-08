<p align="center">
  <img src="assets/logo-wide-short.png" alt="Shifter">
</p>

[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=coverage)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter) [![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter) [![Bugs](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=bugs)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter) [![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter) [![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# Shifter

**Watch an AI hack. In your browser. Under your control.**

A SaaS cyber range for autonomous AI hacking agents.

**Beta coming soon:** Cortex Catalyst - December 18, 2025

## What is Shifter?

Shifter gives you a turnkey environment to experiment with AI-driven attacks. No setup, no infrastructure headaches—just log in and go.

- **Demo** AI cyber capabilities for customers, executives, or colleagues
- **Experiment** with AI-driven attacks against victim infrastructure
- **Educate** yourself on what autonomous offensive AI looks like in practice
- **Research** AI cyber agent capabilities in an isolated environment

Everything runs in the cloud. Open your browser, launch a range, and start.

## Why Shifter?

- **No infra to manage** — spin up a range in minutes, not days
- **No tools to install** — everything's in the browser
- **No scripts to write** — tell the AI what you want in plain English
- **Your endpoint agent** — victim VMs run your XDR/XSIAM agent, detections in your tenant
- **No cleanup** — tear down when you're done

## How It Works

1. Log into the portal and launch a range (contact [Brad Edwards](mailto:bedwards@paloaltonetworks.com) for access)
2. Open the control box—a browser-based desktop with an AI agent
3. Tell the agent what to do: *"Set up a vulnerable web server"* or *"Attack the target and get root"*
4. Watch the AI autonomously configure, exploit, and pivot
5. See detections in your security tooling

You direct. The agent executes.

## Architecture

```mermaid
flowchart LR
    Browser --> Portal[Portal]
    Browser --> Kasm[Control Box<br/>Agent + MCPs]
    Kasm -->|MCP| Kali[Kali]
    Kasm -->|MCP| Victim[Victim VM]
```

- **Portal**: Authentication and range management
- **Control Box**: Browser-based desktop with AI agent
- **Kali**: Attack platform
- **Victim**: Target infrastructure

## Under the Hood

- **AI Integration**: [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) gives the agent real tools—SSH, kali command execution, file ops. Works with Claude, GPT, Gemini, or any MCP-compatible model
- **Infrastructure**: Terraform-managed AWS (VPCs, EC2, ALB, Cognito auth)
- **Control Box**: Kasm containerized desktops with Cursor IDE and Cline
- **Zero local install**: Everything browser-based, nothing on your laptop

Full technical docs: [docs/](docs/)

## Roadmap

See [GitHub Issues](https://github.com/Brad-Edwards/shifter/issues).

**Note:** Initial release limits ranges to a single victim VM per user.

## Ethics

AI-driven attack capabilities are already in adversary hands. Defenders need to catch up. [Read more](docs/ethics.md).

## Safety

- Ranges are isolated—no internet egress from victim VMs
- Human oversight required—you direct every scenario
- AI actions are logged and auditable
- Users authenticate via Cognito with MFA required
- Access restricted to authorized personnel

## Disclaimer

This software is provided "as is" without warranty of any kind. The authors disclaim all liability for any damages or legal consequences arising from its use or misuse. You are solely responsible for ensuring your use complies with applicable laws and regulations.

Do not f*** around and find out.

## License

MIT

---

10-23 AI hacker shenanigans 🚓
