# Grail Content Editor

Standalone local development tooling for authoring the sibling `Grail` game
project. This folder is separate from the contest submission and is not loaded
by the game at runtime.

## Prerequisites

- Python 3.10 or newer
- The expected sibling layout:

  ```text
  GrailQuest/
    Grail/
    Tools/
      ContentEditor/
  ```

No npm package, cloud service, database, or third-party runtime dependency is
required. The machine used for Phase 1 does not have Node/npm installed, so
the editor uses a Python standard-library server and a browser UI.

## Start

From this directory:

```powershell
python server.py
```

Then open <http://127.0.0.1:5173/>. To select another local Grail checkout:

```powershell
python server.py --project "E:\path\to\Grail"
```

The default project is discovered as the sibling `../../Grail` relative to
`ContentEditor/server.py`.

## Supported Pass 3 content

- Encounters: metadata, path and direction filters, requirements, stages,
  choices, costs, outcomes/effects, pending actions, and advanced raw JSON.
  The list supports combinable text search, path/region/direction/distance,
  repeatable, tag, combat, and requirement-presence filters with in-memory
  unsaved edits reflected immediately.
  Common item, combat, injury, loot-table, path, and resource references have
  schema-aware controls. `startCombat` outcomes expose combat references,
  Victory/Fled result text, nested outcomes, loot-table rolls, direct item
  rewards, and the current weighted/random reward shapes without requiring
  Advanced JSON for ordinary edits.
- Shops: display name, item stock, buy prices, finite or unlimited stock, sell
  values, accepted categories, accepted tags, and raw JSON.
- Items: identity, category, rarity, tags, inventory flags, equipment slots,
  stack limits, weapon damage, armor defense, granted combat abilities,
  current combat-use and treatment fields, used-by references, and raw effect
  or item JSON. The list supports combinable text search, category, rarity,
  equipment, tri-state inventory flags, and all/any tag filters. A focused
  drop panel can add/remove this item in an existing loot table and edit its
  weight.
- Combat: combat metadata and reusable enemy roster composition, with Open
  Enemy navigation, repeated enemy occurrences, reordering, and multi-enemy
  combats.
- Enemies: the canonical COMBAT_ENEMY_DEFINITIONS editor for identity, HP,
  speed, defense, ordered action-pattern references, used-by navigation, and
  safe deletion.
- Enemy Actions: the canonical COMBAT_ENEMY_ACTION_DEFINITIONS editor for
  identity, damage range, target mode, optional injury/chance, used-by
  navigation, and safe deletion. Uncommon future fields remain available in
  Advanced JSON.
- Abilities: one schema-aware active/passive editor for shared identity,
  description, kind, tags, target mode, prompt, generic resource cost,
  cooldowns, charges, lifecycle trigger, conditions, structured effects,
  nested effect branches, used-by references, and raw JSON fallback. Filters
  cover kind, resource, tags, and tag matching mode.
- Loot Tables: rolls and ordered weighted gold, item, material, recipe, and
  nested loot-table entries, including fixed or min/max quantities.
- Paths: a derived, read-only path index built from encounter `pathIds` and
  expedition `pathId` relationships. It shows linked metadata, reverse
  encounter membership, filtering/sorting, and safe add/remove membership
  operations without creating a duplicate path database.
- Expeditions: the canonical `EXPEDITION_DEFINITIONS` editor, including ID,
  name, description, danger, region, path, kind, camp-event table IDs,
  prerequisites, used-by references, and advanced raw JSON.
- Recipes: canonical `RECIPE_DEFINITIONS` editing with typed item/material
  ingredient rows, quantities, selectors, duplicate/reorder/remove controls,
  item or provisions outputs, provider, rarity, starter flag, gold cost,
  references, and raw JSON. Legacy ingredient maps plus `ingredientType` are
  read for compatibility and normalize to typed rows on save.
- Crafting Providers: the separate current `CRAFTING_PROVIDER_DEFINITIONS`
  editor. Providers currently author only ID and name; recipe assignment is
  authored by each recipe's `craftingProvider` field and grouped here for
  browsing.
- Injuries: the canonical `INJURY_DEFINITIONS` editor, including identity,
  treatment item, recovery range, infection/travel-damage fields, known
  generic effect multipliers, and an advanced JSON escape hatch for future
  effect shapes. References are checked before deletion.
- Camp Events: the canonical `CAMP_EVENT_DEFINITIONS` editor, including
  identity, region/path applicability, optional occurrence and distance
  limits, staged choices, requirements, costs, and recursively editable
  outcomes. Camp-event table references remain linked to the editable event
  entries.
- Dialogue: reusable `DIALOGUE_DEFINITIONS` sequences with searchable CRUD,
  node and choice branching, speaker and node-link selectors, shared
  requirement/effect editing, reverse references, and safe deletion.
- NPCs: the canonical `NPC_DEFINITIONS` editor for identity, simple dialogue,
  rumors, dialogue-sequence hooks, and location membership with Open buttons.
- Destinations: the canonical `DESTINATION_DEFINITIONS` editor for scene
  metadata, shops, crafting providers, NPCs, actions, and intro gating.
- Locations: the canonical `LOCATION_DEFINITIONS` editor for chapter/region
  metadata, visual keys, destination/NPC/shop/expedition/quest lists, and
  shared requirements.

Encounter, camp-event, and combat-ability effects/requirements use the same recursive,
schema-aware editor at supported nesting depths. This includes conditional
requirements and effects, random chance branches, random-one options, and
combat Victory/Fled outcomes. Add/remove controls are available for nested
collections and random options; Advanced JSON remains available for uncommon
future shapes.

Selectors are populated from the current game definitions in `data.js`,
`dialogue-data.js`, `location-data.js`, `combat-data.js`, `injury-data.js`,
`loot-data.js`, and `expedition-data.js`.
Item references also include current recipes and camp events. Cross-content
Open buttons connect encounter combat/loot references, item ability grants,
combat enemy/action references, and nested loot-table references. The editor
also connects encounters, derived Paths, canonical Expeditions, Recipes,
Crafting Providers, Items, Dialogue, NPCs, Destinations, Locations, and Loot
Tables. It keeps
the live game definitions as the source of truth and does not change them
until Save is explicitly clicked. Loot Tables expose the existing direct
`type: "recipe"` unlock entries with recipe selectors and Open Recipe links;
the editor does not invent recipe-scroll items.

## Loading and saving

The server reads the current JavaScript constants directly from:

- `Grail/js/encounter-data.js`
- `Grail/js/location-data.js`
- `Grail/js/data.js`
- `Grail/js/combat-data.js`
- `Grail/js/loot-data.js`
- `Grail/js/expedition-data.js`
- `Grail/js/crafting-data.js`
- `Grail/js/injury-data.js`
- `Grail/js/camp-data.js`

The editor starts with an in-memory copy and shows an unsaved indicator. Save
is explicit. Before writing, it validates references and structure, checks the
source hashes captured at load time to detect another process changing the
file, and replaces only the changed top-level definition property. Existing
definition order, comments, delimiters, and all untouched source spans remain
in place; new definitions are appended predictably and deleted definitions are
removed with only necessary delimiter cleanup. Writes use a temporary file
plus `os.replace`; a timestamped recovery backup is kept in
`Tools/ContentEditor/.backups/`. Item, combat, ability, and loot-table changes
are written with the same surgical definition-property behavior. Combat
definitions, enemy definitions, enemy actions, and abilities share
`combat-data.js`; a single save groups those changes into one
source-preserving update and performs one stale-file check. Recovery backups
are retained for each changed source file.

Validation reports duplicate keys, missing required encounter structure,
unknown item/combat/ability/enemy-action/injury/path/region/loot references,
unknown recipe/provider/material/dialogue/NPC/destination/location references,
invalid recipe ingredient and output quantities, malformed recipe/provider
definitions, malformed dialogue node links and choice branches,
invalid chance values, malformed combat-resolution branches, invalid combat
ability trigger/condition/effect fields, invalid loot
rolls and direct reward quantities, invalid combat damage and stat ranges,
invalid loot weights/quantities, invalid distance ranges, invalid shop
prices/stock, and deletions that remain referenced by understood definitions.
The editor never silently repairs authored content.

## Known limitations

- The parser intentionally supports the data-only object-literal subset used
  by the current authored constants; it does not execute arbitrary JavaScript
  or promise a general JavaScript round-trip formatter.
- The editor writes encounters, injuries, and camp events in their existing
  files, items in
  `Grail/js/data.js`, combat/ability/loot definitions in their existing
  source files, dialogue in `Grail/js/dialogue-data.js`, and
  shops/NPCs/destinations/locations in `Grail/js/location-data.js`.
  Expeditions are written to `Grail/js/expedition-data.js`. Paths do not have
  a standalone authored constant in the current game, so their metadata
  remains derived and only encounter membership is editable from the Path
  view.
- Combat no longer owns copies of enemy stats or action definitions: those
  shared definitions are edited in the Enemies and Enemy Actions categories.
- Paths remain derived from encounter and expedition relationships; the editor
  does not invent standalone Path definitions for the current distributed
  path-ID architecture.
- Dialogue requirements and effects reuse the encounter evaluator vocabulary.
  Expedition-only requirements/effects remain context-dependent and are
  rejected or evaluate false when authored for a town-only invocation.
- Dialogue nodes expose the current speaker, portrait, text, links, choices,
  requirements, and effects. Uncommon future node metadata remains available
  through Advanced JSON.
- Crafting providers currently have only the authored ID/name fields. Recipe
  unlocks are direct loot-table `recipe` entries; no recipe item or separate
  unlock database exists in the current game.
- Uncommon fields retain an advanced per-object JSON editor. Current combat
  resolution branch fields and common nested effects are typed, while unusual
  authored shapes remain available through the raw encounter/object editors.
- There is no autosave, collaboration lock, or automatic merge. A stale-file
  save is rejected and the editor must be reloaded before trying again.

## Tests

From `ContentEditor`:

```powershell
python -m unittest discover -s tests -v
```

The tests load the real current definitions, round-trip parsed data, and use a
temporary copy for all write tests. They do not modify the live Grail
worktree.
