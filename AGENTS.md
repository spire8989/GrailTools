# Project Guidance for Codex Agents

This folder contains **development tools for the Grail game project**. It is intentionally separate from the game repository and from the game-jam submission.

Read this file before changing, generating, testing, or reorganizing anything under `Tools`.

## Workspace layout

The intended local layout is:

```text
E:\Unreal Games\Shadow\GrailQuest\
    Grail\
        .git\
        AGENTS.md
        index.html
        js\
        css\
        assets\
        tests\
        ...

    Tools\
        AGENTS.md
        ContentEditor\
        ...
```

`Grail\` and `Tools\` are separate projects with separate responsibilities.

### Grail

`..\Grail\` is the actual game repository and the source of the submitted prototype.

It has its own `AGENTS.md`. When making any change inside `..\Grail\`, read and obey that file.

### Tools

This folder contains local development utilities used to author, inspect, validate, test, or analyze game content.

Tools are **not part of the game submission** unless the user explicitly changes that decision.

Do not copy tool code, tool dependencies, generated development files, package metadata, build infrastructure, or editor UI into the Grail repository unless explicitly requested.

---

## Contest/submission separation

Preserving a clean game submission is a primary constraint.

The tooling may use technologies that the game itself does not use, including:

* Node.js
* npm
* TypeScript
* React or other UI libraries
* bundlers
* local development servers
* desktop wrappers
* third-party development libraries
* generated files

Those choices are allowed for the tools because the tools are not intended to ship with the prototype.

Do **not** assume that a library or architecture chosen for a tool is appropriate for the Grail game itself.

Never introduce tool dependencies into `..\Grail\` merely because they are convenient here.

The Grail game should continue following its own submission-oriented architecture and its own `AGENTS.md`.

---

## Repository boundaries

`Tools\` is currently intended to remain local and does not need to be part of the Grail Git repository.

Never:

* initialize or move the Grail `.git` directory into `Tools`
* make `Tools` a subdirectory of the Grail repository without explicit user instruction
* alter Grail Git history while working on tooling
* commit tool files into the Grail repository
* add tool dependencies to Grail package/configuration files
* move Grail source files into the tool project

When a tool needs to access game files, use the sibling path:

```text
..\Grail\
```

Treat the Grail repository as an external project being edited or inspected by the tool.

---

## Source of truth

The Grail repository remains the canonical source of game content.

Do not create a separate content database that silently becomes authoritative.

The content editor should read from and, when explicitly designed to do so, write back to the actual Grail content definitions.

Important current game content locations include:

```text
..\Grail\js\data.js
..\Grail\js\encounter-data.js
..\Grail\js\expedition-data.js
..\Grail\js\location-data.js
..\Grail\js\combat-data.js
..\Grail\js\crafting-data.js
..\Grail\js\loot-data.js
..\Grail\js\camp-data.js
..\Grail\js\dialogue-data.js
..\Grail\js\injury-data.js
```

Do not duplicate these into a tool-owned authoritative format unless the user explicitly approves a content-format migration.

Temporary parsed representations, caches, indexes, schemas, and previews are fine.

---

## Current game content architecture

The game already uses stable IDs and separates much authored content from runtime logic.

Relevant relationships include:

* items are referenced by stable item IDs
* encounters reference paths, regions, items, combat definitions, injuries, loot tables, flags, and other content by ID
* shops reference items by ID
* locations reference destinations, NPCs, shops, and expeditions by ID
* expeditions reference paths, regions, camp-event tables, and prerequisites
* recipes and loot tables reference items/materials by ID

The editor should preserve these relationships rather than replacing them with copied display strings.

Prefer dropdowns, search selectors, reference browsers, and validation over manual ID entry whenever practical.

---

## Content Editor goals

The first major tool is expected to be a content editor.

Its purpose is to make authored game content easier and safer to manage without manually editing large JavaScript data files.

Likely editor responsibilities include:

* browse content
* search/filter content
* add content
* edit content
* duplicate content
* delete content
* validate references
* show where content is referenced
* warn before destructive changes
* preview raw data when useful

Initial high-value content types are:

1. Encounters
2. Items
3. Shops

Other content types may be added later.

Do not expand scope unnecessarily when implementing a focused request.

---

## Editing philosophy

Prefer **schema-aware editing** over a generic JSON/object editor.

For example:

* an encounter `combatId` should select from known combats
* an `itemId` should select from known items
* an injury effect should select from known injuries
* paths and regions should use known IDs
* shop stock should reference real item definitions

The editor may provide a raw-data view as an escape hatch, but the primary workflow should understand the game content structure.

---

## Validation

Validation is a core feature, not optional polish.

Where relevant, detect problems such as:

* duplicate IDs
* references to nonexistent items
* references to nonexistent combats
* references to nonexistent injuries
* references to nonexistent paths or regions
* missing loot tables
* invalid expedition references
* invalid probability/chance ranges
* invalid minimum/maximum distance combinations
* malformed encounter stages or choices
* deleted content that remains referenced elsewhere

Do not silently repair authored content unless the user explicitly requests automatic fixing.

Report problems clearly and preserve the original data.

---

## Destructive operations

Deletion should be reference-aware.

Before deleting content, inspect known references where practical.

For example, deleting an item should detect references from:

* encounters
* shops
* crafting recipes
* loot tables
* combat/content effects
* expedition prerequisites
* other relevant definitions

Prefer blocking or warning on unsafe deletion rather than leaving broken references.

If a force-delete capability is added, make the consequences explicit.

---

## Writing to the Grail repository

Do not modify `..\Grail\` casually while developing the tool.

When implementing tool functionality that writes to the game source:

1. Read `..\Grail\AGENTS.md`.
2. Inspect the Grail Git worktree before writing:

   ```powershell
   git -C ..\Grail status --short
   ```
3. Preserve unrelated modified or untracked files.
4. Only modify files required by the current operation.
5. Do not commit or push unless explicitly requested.
6. Validate generated output before replacing existing source.
7. Prefer atomic writes or backup-safe replacement so a failed write does not corrupt a content file.

Tool development itself should remain isolated from the Grail repo.

---

## Shared workspaces

There may be multiple Codex sessions working on the Grail project at once.

Do not assume the sibling Grail worktree is clean.

Never reset, checkout over, discard, stage, or rewrite changes that were not created for the current task.

When reading Grail files for editor development, treat their current contents as authoritative even if they differ from older context.

---

## Paths

Avoid hardcoding the user's absolute machine path throughout the application.

The current workspace is expected to live near:

```text
E:\Unreal Games\Shadow\GrailQuest\
```

but tools should preferably resolve the Grail project using one of:

* a configurable project path
* a relative sibling path such as `..\..\Grail` depending on tool location
* a user-selected project directory
* a small local tool configuration file

If an absolute path is stored, keep it in local tool configuration rather than application logic.

---

## Tool dependencies

Unlike the Grail submission, this folder may use ordinary development dependencies.

Choose dependencies based on usefulness and maintainability rather than reproducing the game's dependency-free restrictions.

However:

* keep the dependency set reasonable
* do not add large libraries for trivial functionality
* keep generated dependency folders such as `node_modules` local/untracked where appropriate
* document setup commands
* prefer commonly supported tooling
* do not require cloud services for basic content editing

The tool should work locally.

---

## Generated output

Clearly distinguish:

* human-authored tool source
* temporary files
* caches
* generated files
* content exported for Grail

Do not leave temporary editor artifacts inside `..\Grail\`.

If the tool produces intermediate output, keep it under the tool's own directories unless the final operation intentionally writes valid game content back to Grail.

---

## Testing

Testing rules for the tools are independent from the Grail game tests.

Use whatever testing stack is appropriate for the selected tool technology.

When a change affects how the editor reads or writes Grail content, test against representative real Grail definitions.

For write operations, verify at minimum:

* unchanged content round-trips without semantic changes
* IDs remain stable
* formatting remains readable
* references are preserved
* invalid edits are rejected or clearly reported
* unrelated definitions are not modified

If the tool modifies actual Grail files during testing, inspect the Grail diff afterward and restore only changes created by the current test. Never wipe unrelated work.

---

## Game verification

When a tool intentionally changes game content, successful editor validation does not automatically prove the game still works.

If the requested task includes applying content changes to Grail, use the game repository's own testing instructions from:

```text
..\Grail\AGENTS.md
```

The Grail project's tests and runtime behavior remain authoritative for the game.

---

## Documentation

Keep tool-specific setup and architecture documentation inside `Tools`.

Do not add tool documentation to the game submission merely to describe local development utilities.

A Content Editor should eventually have a short README covering:

* installation
* startup
* selecting/finding the Grail project
* supported content types
* save/write behavior
* validation behavior
* known limitations

Do not update Grail's `BUILD_LOG.md` for ordinary internal tool work unless the user specifically wants that tooling milestone recorded as part of the game-development history.

---

## Guiding principle

The tools exist to make development of Grail easier.

They must not make the Grail submission harder to understand, less portable, more dependent on tooling, or contaminated with development-only infrastructure.

Keep the boundary simple:

```text
Tools = development environment

Grail = game source and contest submission
```

When uncertain which side something belongs on, keep it in `Tools` unless the game itself requires it at runtime.
