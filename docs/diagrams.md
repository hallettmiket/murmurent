---
date: 2026-05-06
tags: [murmurent, design, diagrams]
---

# Murmurent — Diagrams

> Mermaid diagrams for the group-level design. Companion to [[group_level]] and [[cli_manual]].
> Mermaid renders natively in Obsidian (with the official renderer) and on GitHub.
> Update alongside the design doc whenever structural concepts change.

## 1. Tier architecture

The Murmurent hierarchy: centre → group → project → squad → member.

```mermaid
graph TB
    subgraph CENTRE["Bioconvergence centre"]
        WC[Murmurent commons]
        OR[Centre oracle]
    end
    subgraph G1["Group g1 (Hallett)"]
        PI1[PI]
        LM1[lab_manager]
        BC1[bookworm_curator]
        M1[Member A]
        M2[Member B]
        M3[Member C]
        ORG1[Group oracle]
        INV1[Inventory]
    end
    subgraph PROJ["Project: dcis_imaging"]
        LEAD[Project lead]
        EN1[Experiment squad: 1_titration]
        EN2[Experiment squad: 2_qpcr]
        SEA1[SEA: segmentation]
    end
    CENTRE --> G1
    G1 --> PROJ
    LEAD -.lead.-> EN1
    LEAD -.lead.-> EN2
    EN1 --> SEA1
```

## 2. Repo and data layout

Three classes of repo plus the lab VM. Data never lives in the repos.

```mermaid
graph LR
    subgraph GH["GitHub"]
        WR["murmurent repo<br/>(agent registry,<br/>choreographies)"]
        LMR["lab-management repo<br/>(roles, inventory,<br/>members, audit, dashboards)"]
        PR1["project repo: dcis_imaging<br/>(CHARTER, MEMBERS,<br/>exp/, src/, findings/)"]
        PR2["project repo: bbb_perm<br/>(CHARTER, MEMBERS,<br/>exp/, src/, findings/)"]
    end
    subgraph LV["Lab VM (/data/lab_vm/)"]
        RAW["raw/<br/>(read-only,<br/>per-project)"]
        REF["refined/<br/>(analysis outputs,<br/>per-project)"]
    end
    subgraph LOCAL["Member machine"]
        CC["Claude Code +<br/>~/.claude/<br/>(agents, MCP servers)"]
        VAULT["Obsidian vault"]
    end
    WR -.symlinks.-> CC
    LMR --> CC
    PR1 -.clone.-> CC
    PR2 -.clone.-> CC
    PR1 -.references paths.-> RAW
    PR1 -.references paths.-> REF
    CC --> VAULT
```

## 3. Push mechanics

Member commits land on a personal branch; `--finalize` opens a PR; bots review per path; merge fires auto-publish hooks.

```mermaid
sequenceDiagram
    participant M as Member CC
    participant PB as Personal branch<br/>(member/<handle>/<topic>)
    participant Main as main
    participant Bots as Bots (Actions)
    participant Reviewer as Lead / PI
    participant Oracle as Group oracle
    M->>PB: murmurent push (direct)
    M->>PB: murmurent push --refined (checksums)
    M->>PB: murmurent push --finalize
    PB->>Main: open PR
    Main->>Bots: trigger by path
    Bots-->>Main: adversary, conscience,<br/>security_guard, bookworm
    Main->>Reviewer: request review
    Reviewer-->>Main: approve
    Main->>Main: merge
    Main->>Oracle: auto-publish findings/**
    Main->>Main: re-verify checksums
    Main->>Main: re-sync ACL on MEMBERS change
```

## 4. Project lifecycle

State diagram of a project's life from charter to archive, with transitions and required artefacts.

```mermaid
stateDiagram-v2
    [*] --> Birth: PI approves<br/>charter
    Birth --> Active: scaffold repo,<br/>create raw+refined dirs,<br/>register
    Active --> Active: admit / release<br/>(MEMBERS, ACL,<br/>age re-encrypt)
    Active --> Paused: pause<br/>(audit entry)
    Paused --> Active: resume
    Active --> Ended: end<br/>(reason, SUMMARY.md,<br/>oracle publish)
    Paused --> Ended: end
    Ended --> Archived: archive<br/>(repo archive,<br/>ARCHIVE-DATE/ on VM,<br/>frozen MEMBERS)
    Archived --> [*]
```

## 5. Onboarding sequence

Four stages: identity, enrollment, issuance, confirmation. Membership is a
signed certificate (see [identity.md](identity.md)); the roster follows from
issuance, not from a PR.

```mermaid
sequenceDiagram
    participant New as New member
    participant NM as New member's machine
    participant PI
    participant PM as PI's machine
    New->>NM: murmurent init
    NM->>NM: set handle, email, Slack<br/>generate ed25519 keypair
    New->>NM: murmurent enroll --group <lab>
    NM-->>New: enroll.json<br/>(proof of key possession)
    New->>PI: send enroll.json (DM / email)
    PI->>PM: murmurent issue-member-card enroll.json --group <lab>
    PM->>PM: verify proof, sign member card,<br/>record on roster (members/<handle>.md)
    PM-->>New: bundle.json DM'd on Slack<br/>(member card + PI card)
    New->>NM: murmurent import-card bundle.json<br/>--trust-root <root>
    NM->>NM: pin trust root, verify chain,<br/>store card
    New->>NM: murmurent whoami
    NM-->>New: group + role confirmed
```

## 6. Permissions surface

The layers of access control. Static lists block the obvious; hooks block the contextual; audit records what happened either way.

```mermaid
graph TB
    subgraph User["Per-member CC"]
        AL["settings.json<br/>permissions.allow / deny<br/>(static, generated from agents)"]
        AT["Per-agent tools:<br/>(required - denied)"]
        H1["PreToolUse hooks<br/>raw guard, x-project guard,<br/>secrets-pre"]
        H2["PostToolUse hooks<br/>audit log,<br/>secrets-post"]
        H3["UserPromptSubmit hooks<br/>context inject,<br/>frozen-agent integrity"]
        H4["Stop hook<br/>session summary"]
    end
    subgraph Server["Server-side"]
        BP["Branch protection<br/>(per-path PR rules)"]
        MCP["MCP server permissions<br/>(role checks per tool)"]
        ACL["Filesystem ACL<br/>(synced from MEMBERS)"]
    end
    subgraph Crypto["At rest / in transit"]
        AGE["age encryption<br/>(MEMBERS recipients)"]
        SSH["SSH / SSO to lab VM"]
        SIG["Signed commits"]
    end
    subgraph Audit["Audit trail"]
        AU1["git history (immutable)"]
        AU2["role registry audit log"]
        AU3["oracle publish log"]
        AU4["per-member jsonl audit<br/>(encrypted, uploaded nightly)"]
    end
    User --> Server
    Server --> Crypto
    Server --> Audit
    Crypto --> Audit
    H2 --> AU4
```

## 7. Hook flow

How the seven hooks fire around a tool call within a CC session.

```mermaid
sequenceDiagram
    participant U as User
    participant CC as Claude Code
    participant H as Hooks
    participant T as Tool / MCP
    participant L as Audit log
    U->>CC: prompt
    CC->>H: UserPromptSubmit<br/>(context inject, frozen check)
    H-->>CC: allow + injected context
    CC->>H: PreToolUse<br/>(raw guard, x-project guard, secrets-pre)
    alt deny
        H-->>CC: deny + reason
        CC-->>U: refusal explained
    else allow
        H-->>CC: allow
        CC->>T: invoke
        T-->>CC: result
        CC->>H: PostToolUse<br/>(audit, secrets-post)
        H->>L: append jsonl line
        H-->>CC: redacted result
        CC-->>U: response
    end
    Note over CC,H: Stop hook fires<br/>at end of session<br/>(session summary)
```
