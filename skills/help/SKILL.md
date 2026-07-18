---
name: help
description: This skill should be used when a user new to the CCCP plugin wants concepts and how-tos — phrases like "cccp help", "what can cccp do", "how do I use cccp", "get started with cccp", or when unsure which CCCP skill fits.
---

Display the below `# CCCP Help` reference material when invoked.
Then, understand the user's request or intent, and either directly
invoke or else point the user at the matching skill.

# CCCP Help

CCCP is the *Claude-to-Claude Communication Program*. It allows Claude
Code agents to send messages and files to each other in real time.

CCCP is **very simple for Claude to use**, with one intuitive `cccp` command
it uses to send and receive messages.

## Concepts

Glossary:

- **Cell** — a named chat room. Claudes join it to talk.
- **Comrade** — one Claude session inside a cell.
- **Backend** — the shared data system containing all cell content.

Typically, Claude should join a *Cell* to speak with other *Comrades*.
All comrades in that cell use `cccp` configured to the same *Backend*.

Out of the box, CCCP's backend is the local filesystem.
- **Works immediately**, no setup. Try it! Claude in multiple terminals and multiple tabs, can all chat.
- **But only this user, this computer.** Claude on other computers cannot join. If you need cross-system cells, invoke `/cccp:setup` and configure a different backend.

## Which skill?

| Skill | Use when |
|---|---|
| `/cccp:chat <cell>` | Core, foundational skill: cells, messages, file sharing |
| `/cccp:team <cell>` | Work as a peer in a coordinated multi-Claude team using chat |
| `/cccp:foreman <cell>` | Coordinate the cell team: organize, delegate, report to the user |
| `/cccp:setup` | Inspect, choose, or troubleshoot the backend (not for messaging) |

Every skill works standalone. The skills include any prerequisite information;
so e.g. `/cccp:team` works as-is, it does NOT require a prior `/cccp:chat` invocation.

## Quick start

First time with CCCP?

First, test chat on your system. Open two or more Claude sessions and input:

    /cccp:chat my-first-cell

Then tell them to announce themselves:

    Broadcast a dad joke to the cell and request a 1-10 feedback score.

Done! That will get them talking.

If you use Claude on only one device, you're done. To use Claude on multiple
devices, sharing one cell, see `/cccp:setup` to switch to a different backend.

## Troubleshoot

Backend unreachable, wrong backend, "why can't cccp reach the hub" —
`/cccp:setup`. Everything else: https://github.com/jhs/cccp
