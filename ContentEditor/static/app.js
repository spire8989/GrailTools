/* global fetch */

const COMMON_REQUIREMENT_TYPES = [
  "ownsItem", "notOwnsItem", "carriedItem", "equippedItem", "availableExpeditionItem",
  "knowledge", "companion", "unlockedCompanion", "notUnlockedCompanion", "runFlag", "notRunFlag",
  "campaignFlag", "currentPath", "minimumResource", "minimumHealth", "maximumHealth", "minimumDistance",
];
const COMMON_EFFECT_TYPES = [
  "modifyResource", "consumeExpeditionItem", "gainUnsecuredItem", "gainUniqueUnsecuredItem",
  "gainRandomUnsecuredItem", "gainWeightedRandomUnsecuredItem", "rollLootTable", "startCombat",
  "setRunFlag", "setCampaignFlag", "changePath", "unlockCompanion", "applyInjury", "conditional",
  "randomChance", "randomOne", "learnRecipe", "markEncounterSeen",
];

const CONTENT_CATEGORIES = [
  ["encounters", "Encounters"],
  ["injuries", "Injuries"],
  ["campEvents", "Camp Events"],
  ["paths", "Paths"],
  ["expeditions", "Expeditions"],
  ["recipes", "Recipes"],
  ["materials", "Materials"],
  ["craftingProviders", "Crafting"],
  ["shops", "Shops"],
  ["items", "Items"],
  ["combats", "Combat"],
  ["abilities", "Abilities"],
  ["lootTables", "Loot Tables"],
];

const EDITABLE_REFERENCE_SOURCES = new Set([
  "encounters", "injuries", "campEvents", "expeditions", "recipes", "materials", "craftingProviders", "shops", "items", "combats", "abilities", "enemyDefinitions", "enemyActions", "lootTables",
]);

const state = {
  catalog: null,
  category: "encounters",
  selectedId: null,
  originalSelectedId: null,
  draft: null,
  search: "",
  dirty: false,
  draftDirty: false,
  searchByCategory: {},
  filterOpen: false,
  filters: {
    items: {
      category: "",
      rarity: "",
      equippable: "any",
      equipmentSlot: "",
      carriable: "any",
      consumable: "any",
      questItem: "any",
      campaignItem: "any",
      unique: "any",
      sellable: "any",
      protected: "any",
      tags: [],
      tagMode: "all",
    },
    encounters: {
      pathIds: [],
      regionIds: [],
      direction: "all",
      minDistance: "",
      maxDistance: "",
      repeatable: "any",
      tags: [],
      tagMode: "all",
      combat: "any",
      hasRequirements: "any",
    },
  },
  validation: { errors: [], warnings: [] },
  validationTimer: null,
  validationPending: false,
  navigationHistory: [],
  pathFilters: { search: "", direction: "all", minDistance: "", maxDistance: "", tag: "", sort: "title" },
};

const $ = (selector) => document.querySelector(selector);

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function jsonText(value) {
  return escapeHtml(JSON.stringify(value, null, 2));
}

function selected(value, current) {
  return String(value) === String(current) ? " selected" : "";
}

function checked(value) {
  return value ? " checked" : "";
}

function itemLabel(itemId) {
  const item = state.catalog?.items?.[itemId];
  const label = item?.name || state.catalog?.itemLabels?.[itemId];
  return label ? `${label} (${itemId})` : itemId;
}

function abilityLabel(abilityId) {
  const ability = state.catalog?.abilities?.[abilityId];
  return ability?.name ? `${ability.name} (${abilityId})` : abilityId;
}

function enemyLabel(enemyId) {
  const enemy = state.catalog?.enemyDefinitions?.[enemyId];
  return enemy?.name ? `${enemy.name} (${enemyId})` : enemyId;
}

function pathLabel(pathId) {
  const path = state.catalog?.paths?.[pathId];
  return path?.name ? `${path.name} (${pathId})` : pathId;
}

function expeditionLabel(expeditionId) {
  const expedition = state.catalog?.expeditions?.[expeditionId];
  return expedition?.name ? `${expedition.name} (${expeditionId})` : expeditionId;
}

function recipeLabel(recipeId) {
  const recipe = state.catalog?.recipes?.[recipeId];
  return recipe?.name ? `${recipe.name} (${recipeId})` : recipeId;
}

function providerLabel(providerId) {
  const provider = state.catalog?.craftingProviders?.[providerId];
  return provider?.name ? `${provider.name} (${providerId})` : providerId;
}

function materialLabel(materialId) {
  const material = state.catalog?.materials?.[materialId];
  const name = material?.name || state.catalog?.materialLabels?.[materialId];
  return name
    ? `${name} (${materialId})`
    : materialId;
}

function injuryLabel(injuryId) {
  const injury = state.catalog?.injuries?.[injuryId];
  const label = injury?.name || state.catalog?.injuryLabels?.[injuryId];
  return label ? `${label} (${injuryId})` : injuryId;
}

function campEventLabel(eventId) {
  const event = state.catalog?.campEvents?.[eventId];
  const label = event?.title || state.catalog?.campEventLabels?.[eventId];
  return label ? `${label} (${eventId})` : eventId;
}

const ITEM_FILTER_FLAGS = ["carriable", "consumable", "questItem", "campaignItem", "unique", "sellable", "protected"];

function filterState(category) {
  return state.filters[category];
}

function currentSearch() {
  return state.searchByCategory[state.category] ?? state.search ?? "";
}

function setCurrentSearch(value) {
  state.search = value;
  state.searchByCategory[state.category] = value;
}

function uniqueSorted(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null && value !== ""))]
    .map(String)
    .sort((a, b) => a.localeCompare(b));
}

function selectedFilterValues(select) {
  return Array.from(select.selectedOptions || []).map((option) => option.value).filter(Boolean);
}

function filterOptionValues(values, selectedValues = []) {
  return uniqueSorted([...(values || []), ...(selectedValues || [])]);
}

function filterOptions(values, current, labels = {}) {
  return filterOptionValues(values, current).map((value) => `<option value="${escapeHtml(value)}"${selected(value, current)}>${escapeHtml(labels[value] || value)}</option>`).join("");
}

function multiFilterOptions(values, current, labels = {}) {
  const selectedValues = new Set(current || []);
  return filterOptionValues(values, current).map((value) => `<option value="${escapeHtml(value)}"${selectedValues.has(value) ? " selected" : ""}>${escapeHtml(labels[value] || value)}</option>`).join("");
}

function triStateOptions(current) {
  return `<option value="any"${selected("any", current)}>Any</option><option value="yes"${selected("yes", current)}>Yes</option><option value="no"${selected("no", current)}>No</option>`;
}

function matchesTriState(value, filter) {
  if (filter === "any") return true;
  return filter === "yes" ? value === true : value !== true;
}

function tagsMatch(tags, selectedTags, mode = "all") {
  if (!selectedTags.length) return true;
  const authoredTags = new Set(Array.isArray(tags) ? tags : []);
  return mode === "any"
    ? selectedTags.some((tag) => authoredTags.has(tag))
    : selectedTags.every((tag) => authoredTags.has(tag));
}

function finiteNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function overlapsDistanceRange(encounter, minimum, maximum) {
  const queryMinimum = finiteNumber(minimum) ?? Number.NEGATIVE_INFINITY;
  const queryMaximum = finiteNumber(maximum) ?? Number.POSITIVE_INFINITY;
  if (queryMinimum > queryMaximum) return false;
  const encounterMinimum = finiteNumber(encounter?.minimumDistance) ?? Number.NEGATIVE_INFINITY;
  const encounterMaximum = finiteNumber(encounter?.maximumDistance) ?? Number.POSITIVE_INFINITY;
  return encounterMinimum <= queryMaximum && encounterMaximum >= queryMinimum;
}

function encounterHasCombat(encounter) {
  const visit = (value) => {
    if (!value || typeof value !== "object") return false;
    if (Array.isArray(value)) return value.some(visit);
    if (value.type === "startCombat") return true;
    return Object.values(value).some(visit);
  };
  return visit(encounter);
}

function searchMatches(category, id, entry, query) {
  if (!query) return true;
  const recipeSearch = category === "recipes"
    ? ` ${(entry.ingredients ? Object.keys(entry.ingredients).map((ingredientId) => state.catalog.items?.[ingredientId] ? itemLabel(ingredientId) : materialLabel(ingredientId)).join(" ") : "")} ${entry.output?.itemId ? itemLabel(entry.output.itemId) : "provisions"}`
    : "";
  const tags = Array.isArray(entry.tags) ? entry.tags.join(" ") : "";
  return `${id} ${entry.title || entry.displayName || entry.name || ""} ${entry.category || ""} ${entry.rarity || ""} ${tags}${recipeSearch}`.toLowerCase().includes(query);
}

function filterEntries(category, entries) {
  const query = currentSearch().trim().toLowerCase();
  const filters = filterState(category);
  return Object.entries(entries).filter(([id, entry]) => {
    if (!searchMatches(category, id, entry, query)) return false;
    if (category === "items") {
      if (filters.category && entry.category !== filters.category) return false;
      if (filters.rarity === "__none__" && entry.rarity) return false;
      if (filters.rarity && filters.rarity !== "__none__" && entry.rarity !== filters.rarity) return false;
      if (filters.equipmentSlot === "__none__" && entry.equipmentSlot) return false;
      if (filters.equipmentSlot && filters.equipmentSlot !== "__none__" && entry.equipmentSlot !== filters.equipmentSlot) return false;
      if (!matchesTriState(entry.equippable === true, filters.equippable)) return false;
      if (!ITEM_FILTER_FLAGS.every((field) => matchesTriState(entry[field] === true, filters[field]))) return false;
      if (!tagsMatch(entry.tags, filters.tags, filters.tagMode)) return false;
    }
    if (category === "encounters") {
      if (filters.pathIds.length && !filters.pathIds.some((pathId) => (entry.pathIds || []).includes(pathId))) return false;
      if (filters.regionIds.length && !filters.regionIds.includes(entry.regionId)) return false;
      if (filters.direction === "both") {
        if (!((entry.directions || []).includes("outbound") && (entry.directions || []).includes("returning"))) return false;
      } else if (filters.direction !== "all" && !(entry.directions || []).includes(filters.direction)) return false;
      if (!overlapsDistanceRange(entry, filters.minDistance, filters.maxDistance)) return false;
      if (!matchesTriState(entry.repeatable === true, filters.repeatable)) return false;
      if (!tagsMatch(entry.tags, filters.tags, filters.tagMode)) return false;
      const combat = encounterHasCombat(entry);
      if (filters.combat === "yes" && !combat) return false;
      if (filters.combat === "no" && combat) return false;
      const hasRequirements = Array.isArray(entry.requirements) && entry.requirements.length > 0;
      if (!matchesTriState(hasRequirements, filters.hasRequirements)) return false;
    }
    return true;
  });
}

function activeFilterCount(category) {
  const filters = filterState(category);
  if (!filters) return 0;
  if (category === "items") {
    return [filters.category, filters.rarity, filters.equipmentSlot, ...ITEM_FILTER_FLAGS.map((field) => filters[field] !== "any" ? filters[field] : ""), filters.tags.length ? "tags" : ""].filter(Boolean).length;
  }
  if (category === "encounters") {
    return [filters.pathIds.length ? "path" : "", filters.regionIds.length ? "region" : "", filters.direction !== "all" ? filters.direction : "", filters.minDistance !== "" ? "min" : "", filters.maxDistance !== "" ? "max" : "", filters.repeatable !== "any" ? filters.repeatable : "", filters.tags.length ? "tags" : "", filters.combat !== "any" ? filters.combat : "", filters.hasRequirements !== "any" ? filters.hasRequirements : ""].filter(Boolean).length;
  }
  return 0;
}

function activeEntryId(id) {
  return id === state.selectedId || (state.draft?.id === id && state.originalSelectedId === state.selectedId);
}

function selectOptions(values, current, labels = {}) {
  return values.map((value) => `<option value="${escapeHtml(value)}"${selected(value, current)}>${escapeHtml(labels[value] || value)}</option>`).join("");
}

function itemOptions(current) {
  const items = Object.keys(state.catalog?.items || {}).sort();
  return `<option value="">Select an item…</option>${items.map((id) => `<option value="${escapeHtml(id)}"${selected(id, current)}>${escapeHtml(itemLabel(id))}</option>`).join("")}`;
}

function referenceInputLegacy(field, value) {
  const known = state.catalog?.known || {};
  if (field === "itemId") {
    return `<input list="item-options" data-object-field="${field}" value="${escapeHtml(value || "")}" placeholder="item ID">`;
  }
  const map = { combatId: "combats", injuryId: "injuries", tableId: "lootTables", pathId: "paths", regionId: "regions" };
  if (map[field]) {
    const values = known[map[field]] || [];
    return `<select data-object-field="${field}"><option value="">Select ${field.replace("Id", "")}…</option>${selectOptions(values, value)}</select>`;
  }
  return `<input data-object-field="${field}" value="${escapeHtml(value || "")}">`;
}

function referenceInput(field, value, rootField = false) {
  const known = state.catalog?.known || {};
  const fieldAttribute = rootField ? `data-field="${field}"` : `data-object-field="${field}"`;
  if (field === "itemId") {
    const openButton = value
      ? ` <button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="items" data-reference-id="${escapeHtml(value)}">Open</button>`
      : "";
    return `<span class="reference-inline"><input list="item-options" ${fieldAttribute} value="${escapeHtml(value || "")}" placeholder="item ID">${openButton}</span>`;
  }
  if (field === "tableId") {
    const openButton = value
      ? ` <button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="lootTables" data-reference-id="${escapeHtml(value)}">Open</button>`
      : "";
    return `<span class="reference-inline"><input list="loot-table-options" ${fieldAttribute} value="${escapeHtml(value || "")}" placeholder="loot table ID">${openButton}</span>`;
  }
  const map = { combatId: "combats", abilityId: "abilities", injuryId: "injuries", treatmentItemId: "items", tableId: "lootTables", pathId: "paths", expeditionId: "expeditions", recipeId: "recipes", materialId: "materials", craftingProvider: "craftingProviders", craftingProviderId: "craftingProviders", regionId: "regions", eventId: "campEvents", campEventId: "campEvents", knowledgeId: "knowledge", companionId: "companions" };
  if (!map[field]) return `<input ${fieldAttribute} value="${escapeHtml(value || "")}">`;
  const values = ["items", "combats", "abilities", "injuries", "campEvents", "lootTables", "paths", "expeditions", "recipes", "materials", "craftingProviders"].includes(map[field])
    ? Object.keys(state.catalog?.[map[field]] || {}).sort()
    : known[map[field]] || [];
  const labels = map[field] === "items"
    ? Object.fromEntries(values.map((id) => [id, itemLabel(id)]))
    : map[field] === "injuries"
    ? Object.fromEntries(values.map((id) => [id, injuryLabel(id)]))
    : map[field] === "campEvents"
      ? Object.fromEntries(values.map((id) => [id, campEventLabel(id)]))
      : map[field] === "abilities"
    ? Object.fromEntries(values.map((id) => [id, abilityLabel(id)]))
    : map[field] === "paths"
      ? Object.fromEntries(values.map((id) => [id, pathLabel(id)]))
      : map[field] === "expeditions"
        ? Object.fromEntries(values.map((id) => [id, expeditionLabel(id)]))
        : map[field] === "recipes"
          ? Object.fromEntries(values.map((id) => [id, recipeLabel(id)]))
          : map[field] === "materials"
            ? Object.fromEntries(values.map((id) => [id, materialLabel(id)]))
          : map[field] === "craftingProviders"
            ? Object.fromEntries(values.map((id) => [id, providerLabel(id)]))
    : {};
  const openCategory = map[field] === "items" ? "items" : map[field] === "combats" ? "combats" : map[field] === "abilities" ? "abilities" : map[field] === "injuries" ? "injuries" : map[field] === "campEvents" ? "campEvents" : map[field] === "lootTables" ? "lootTables" : map[field] === "paths" ? "paths" : map[field] === "expeditions" ? "expeditions" : map[field] === "recipes" ? "recipes" : map[field] === "materials" ? "materials" : map[field] === "craftingProviders" ? "craftingProviders" : null;
  const openButton = openCategory && value
    ? ` <button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="${openCategory}" data-reference-id="${escapeHtml(value)}">Open</button>`
    : "";
  return `<span class="reference-inline"><select ${fieldAttribute}><option value="">Select ${field.replace("Id", "")}...</option>${selectOptions(values, value, labels)}</select>${openButton}</span>`;
}

function quickObjectFields(object) {
  const type = object.type || "";
  const fields = [];
  const add = (field, label, kind = "text") => {
    if (fields.some((entry) => entry.field === field)) return;
    fields.push({ field, label, kind });
  };
  const directItemType = ["gainUnsecuredItem", "gainUniqueUnsecuredItem", "consumeExpeditionItem"].includes(type);
  if ("itemId" in object || directItemType || (/Item/i.test(type) && !["gainRandomUnsecuredItem", "gainWeightedRandomUnsecuredItem"].includes(type))) add("itemId", "Item reference", "reference");
  if ("combatId" in object || type === "startCombat") add("combatId", "Combat reference", "reference");
  if ("injuryId" in object || type === "applyInjury") add("injuryId", "Injury reference", "reference");
  if ("recipeId" in object || type === "learnRecipe") add("recipeId", "Recipe reference", "reference");
  if ("tableId" in object || type === "rollLootTable") add("tableId", "Loot table", "reference");
  if ("pathId" in object || ["changePath", "currentPath"].includes(type)) add("pathId", "Path", "reference");
  if ("chance" in object || type === "randomChance") add("chance", "Chance", "number");
  if ("amount" in object || ["modifyResource", "minimumResource", "minimumHealth", "maximumHealth", "minimumDistance"].includes(type)) add("amount", "Amount", "number");
  if ("quantity" in object || /Item/.test(type)) add("quantity", "Quantity", "number");
  if ("rolls" in object || type === "rollLootTable") add("rolls", "Rolls", "number");
  if ("weight" in object || type === "gainWeightedRandomUnsecuredItem") add("weight", "Weight", "number");
  if ("resource" in object || ["modifyResource", "minimumResource"].includes(type)) add("resource", "Resource");
  if ("target" in object || type === "applyInjury") add("target", "Target");
  if ("injuryChance" in object) add("injuryChance", "Injury chance", "number");
  if ("flag" in object || /Flag$/.test(type)) add("flag", "Flag");
  if ("knowledgeId" in object || type === "knowledge") add("knowledgeId", "Knowledge", "reference");
  if ("companionId" in object || ["companion", "unlockedCompanion", "notUnlockedCompanion", "unlockCompanion"].includes(type)) add("companionId", "Companion", "reference");
  if ("value" in object || ["runFlag", "notRunFlag", "setRunFlag", "setCampaignFlag", "campaignFlag"].includes(type)) add("value", "Value");
  if ("resultText" in object || ["randomChance", "conditional"].includes(type)) add("resultText", "Result text");
  if ("elseResultText" in object || type === "randomChance") add("elseResultText", "Else result text");
  if ("lockedLabel" in object) add("lockedLabel", "Locked label");
  if ("source" in object) add("source", "Source");
  return fields;
}

function pathValue(root, path) {
  if (!path) return root;
  const tokens = path.match(/[^.[\]]+|\[\d+\]/g) || [];
  return tokens.reduce((value, token) => {
    if (value === undefined || value === null) return undefined;
    const key = token.startsWith("[") ? Number(token.slice(1, -1)) : token;
    return value[key];
  }, root);
}

function collectionNameForOwner(owner) {
  if (owner === "stage-outcomes") return "outcomes";
  if (owner.endsWith("-requirements")) return "requirements";
  if (owner.startsWith("resolution-")) return owner.slice("resolution-".length);
  if (owner.startsWith("nested-")) return owner.slice("nested-".length);
  return owner;
}

function isRequirementCollectionOwner(owner) {
  return owner === "requirements"
    || owner === "encounter-requirements"
    || owner.endsWith("-requirements");
}

function collectionPath(parentPath, collectionName) {
  return parentPath ? `${parentPath}.${collectionName}` : collectionName;
}

function resolutionItemOptions(current) {
  const ids = Object.keys(state.catalog?.items || {}).sort();
  return `<option value="">Select an item...</option>${selectOptions(ids, current, Object.fromEntries(ids.map((id) => [id, itemLabel(id)])))}`;
}

function renderResolutionItemList(object, objectPath) {
  if (object.type === "gainRandomUnsecuredItem") {
    const itemIds = Array.isArray(object.itemIds) ? object.itemIds : [];
    return `<div class="resolution-items"><div class="nested-heading"><span>Random item choices <span class="panel-count">${itemIds.length}</span></span><button type="button" class="small-button" data-action="add-resolution-item-id" data-resolution-path="${escapeHtml(objectPath)}">Add item</button></div>${itemIds.map((itemId, index) => `<div class="resolution-item-row"><select data-resolution-item-field="itemIds" data-resolution-item-path="${escapeHtml(objectPath)}" data-resolution-item-index="${index}">${resolutionItemOptions(itemId)}</select><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="items" data-reference-id="${escapeHtml(itemId)}">Open</button><button type="button" class="small-button danger-outline" data-action="remove-resolution-item-id" data-resolution-path="${escapeHtml(objectPath)}" data-resolution-item-index="${index}">Remove</button></div>`).join("") || `<p class="hint">No item choices. Add an item to author the random reward.</p>`}</div>`;
  }
  if (object.type !== "gainWeightedRandomUnsecuredItem") return "";
  const items = Array.isArray(object.items) ? object.items : [];
  return `<div class="resolution-items"><div class="nested-heading"><span>Weighted item choices <span class="panel-count">${items.length}</span></span><button type="button" class="small-button" data-action="add-resolution-weighted-item" data-resolution-path="${escapeHtml(objectPath)}">Add item</button></div>${items.map((item, index) => {
    const itemPath = `${objectPath}.items[${index}]`;
    return `<div class="resolution-item-row"><select data-resolution-item-field="itemId" data-resolution-item-path="${escapeHtml(itemPath)}">${resolutionItemOptions(item?.itemId)}</select><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="items" data-reference-id="${escapeHtml(item?.itemId || "")}">Open</button><label>Weight<input type="number" min="0" step="any" data-resolution-item-field="weight" data-resolution-item-path="${escapeHtml(itemPath)}" value="${escapeHtml(item?.weight ?? "")}"></label><button type="button" class="small-button danger-outline" data-action="remove-resolution-weighted-item" data-resolution-path="${escapeHtml(objectPath)}" data-resolution-item-index="${index}">Remove</button></div>`;
  }).join("") || `<p class="hint">No weighted item choices. Add an item to author the random reward.</p>`}</div>`;
}

function renderResolutionOptions(object, objectPath) {
  if (!Array.isArray(object.options)) return "";
  return `<div class="resolution-options"><div class="nested-heading"><span>Random options <span class="panel-count">${object.options.length}</span></span><button type="button" class="small-button" data-action="add-resolution-option" data-resolution-path="${escapeHtml(objectPath)}">Add option</button></div>${object.options.map((option, index) => {
    const optionPath = `${objectPath}.options[${index}]`;
    return `<div class="resolution-option"><div class="object-top"><strong>Option ${index + 1}</strong><button type="button" class="small-button danger-outline" data-action="remove-resolution-option" data-resolution-path="${escapeHtml(objectPath)}" data-resolution-option-index="${index}">Remove</button></div><div class="form-grid"><label>Weight<input type="number" step="any" data-resolution-field="weight" data-resolution-path="${escapeHtml(optionPath)}" value="${escapeHtml(option?.weight ?? "")}"></label><label class="wide">Result text<textarea data-resolution-field="resultText" data-resolution-path="${escapeHtml(optionPath)}">${escapeHtml(option?.resultText || "")}</textarea></label><label class="wide">Else result text<textarea data-resolution-field="elseResultText" data-resolution-path="${escapeHtml(optionPath)}">${escapeHtml(option?.elseResultText || "")}</textarea></label></div>${renderObjectCollection("Option requirements", option?.requirements, "resolution-requirements", "", -1, optionPath, true)}${renderObjectCollection("Option effects", option?.effects, "resolution-effects", "", -1, optionPath, true)}${renderObjectCollection("Option else effects", option?.elseEffects, "resolution-elseEffects", "", -1, optionPath, true)}</div>`;
  }).join("") || `<p class="hint">No options. Add an option to author the random branch.</p>`}</div>`;
}

function renderResolutionNestedCollections(object, objectPath) {
  if (!objectPath) return "";
  const nested = [];
  if (Array.isArray(object.requirements)) nested.push(renderObjectCollection("Nested requirements", object.requirements, "resolution-requirements", "", -1, objectPath, true));
  if (Array.isArray(object.effects)) nested.push(renderObjectCollection("Nested effects", object.effects, "resolution-effects", "", -1, objectPath, true));
  if (Array.isArray(object.elseEffects)) nested.push(renderObjectCollection("Else effects", object.elseEffects, "resolution-elseEffects", "", -1, objectPath, true));
  if (object.secondaryOutcome && typeof object.secondaryOutcome === "object") {
    const secondaryPath = `${objectPath}.secondaryOutcome`;
    if (Array.isArray(object.secondaryOutcome.effects)) nested.push(renderObjectCollection("Secondary outcome effects", object.secondaryOutcome.effects, "resolution-effects", "", -1, secondaryPath, true));
    if (Array.isArray(object.secondaryOutcome.elseEffects)) nested.push(renderObjectCollection("Secondary outcome else effects", object.secondaryOutcome.elseEffects, "resolution-elseEffects", "", -1, secondaryPath, true));
  }
  nested.push(renderResolutionOptions(object, objectPath));
  return nested.filter(Boolean).join("");
}

function renderCombatResolutionBranch(label, branchName, branch, objectPath) {
  if (!branch || typeof branch !== "object") return "";
  const branchPath = `${objectPath}.${branchName}`;
  return `<section class="combat-resolution-branch"><div class="section-heading"><div><h4>${label}</h4><p>Authored result resolution after this combat branch.</p></div></div><label class="wide">Result text<textarea data-resolution-field="resultText" data-resolution-path="${escapeHtml(branchPath)}">${escapeHtml(branch.resultText || "")}</textarea></label>${renderObjectCollection(`${label} outcomes`, branch.outcomes, "resolution-outcomes", "", -1, branchPath, true)}</section>`;
}

function renderStartCombatResolution(object, objectPath) {
  const branches = [
    renderCombatResolutionBranch("Victory", "victory", object.victory, objectPath),
    renderCombatResolutionBranch("Fled", "fled", object.fled, objectPath),
  ].filter(Boolean).join("");
  return `<div class="combat-resolution"><div class="section-heading"><div><h4>Combat</h4><p>Combat resolution stays authored on this encounter outcome. Loot tables remain separate content.</p></div></div><div class="form-grid"><label class="wide">Combat reference${referenceInput("combatId", object.combatId)}</label></div>${branches || `<p class="hint">No victory or fled branch is authored for this startCombat outcome.</p>`}${renderResolutionNestedCollections(object, objectPath)}</div>`;
}

function renderObjectCollection(label, collection, owner, stageId, choiceIndex, parentPath = null, resolutionContext = false) {
  const values = Array.isArray(collection) ? collection : [];
  const requirements = isRequirementCollectionOwner(owner);
  const types = [...new Set([...(requirements ? COMMON_REQUIREMENT_TYPES : COMMON_EFFECT_TYPES), ...values.map((value) => value?.type).filter(Boolean)])];
  const collectionName = collectionNameForOwner(owner);
  const nestedPath = parentPath === null ? null : collectionPath(parentPath, collectionName);
  const contextAttributes = parentPath === null ? "" : ` data-parent-path="${escapeHtml(parentPath)}" data-collection-name="${escapeHtml(collectionName)}"`;
  const rows = values.map((object, index) => {
    const fields = quickObjectFields(object || {});
    const quick = fields.map((field) => {
      const value = object?.[field.field];
      let control;
      if (field.kind === "reference") control = referenceInput(field.field, value);
      else if (field.kind === "number") control = `<input type="number" step="any" data-object-field="${field.field}" value="${escapeHtml(value ?? "")}">`;
      else control = `<input data-object-field="${field.field}" value="${escapeHtml(value ?? "")}">`;
      return `<label>${escapeHtml(field.label)}${control}</label>`;
    }).join("");
    const objectPath = nestedPath === null ? "" : `${nestedPath}[${index}]`;
    const special = object?.type === "startCombat"
      ? renderStartCombatResolution(object, objectPath)
      : `${renderResolutionItemList(object || {}, objectPath)}${renderResolutionNestedCollections(object || {}, objectPath)}`;
    return `<div class="object-row" data-object-row data-owner="${owner}" data-stage="${escapeHtml(stageId)}" data-choice-index="${choiceIndex}" data-object-index="${index}"${contextAttributes}>
      <div class="object-top">
        <select data-object-field="type">${selectOptions(types, object?.type)} </select>
        <span class="hint">Quick reference fields are schema-aware; use JSON for uncommon nested fields.</span>
        <button type="button" class="small-button danger-outline" data-action="remove-object">Remove</button>
      </div>
      ${object?.type === "startCombat" ? special : `${quick ? `<div class="quick-fields">${quick}</div>` : ""}${special}`}
      <details><summary>Advanced object JSON</summary><textarea class="object-json" data-object-json>${jsonText(object || {})}</textarea></details>
    </div>`;
  }).join("");
  const addPath = parentPath === null ? "" : ` data-parent-path="${escapeHtml(parentPath)}" data-collection-name="${escapeHtml(collectionName)}"`;
  return `<div class="nested-heading"><span>${escapeHtml(label)} <span class="panel-count">${values.length}</span></span><button type="button" class="small-button" data-action="add-object" data-owner="${owner}" data-stage="${escapeHtml(stageId)}" data-choice-index="${choiceIndex}"${addPath}>Add</button></div>
    ${rows || `<p class="hint">None. Add a ${requirements ? "requirement" : "cost or outcome"} when this collection needs one.</p>`}`;
}

function renderChoice(stageId, choice, index) {
  const title = choice.id || `Choice ${index + 1}`;
  return `<details class="choice-card" open>
    <summary>${escapeHtml(title)}</summary>
    <div class="form-grid">
      <label>Choice ID<input data-choice-field="id" data-stage="${escapeHtml(stageId)}" data-choice-index="${index}" value="${escapeHtml(choice.id || "")}"></label>
      <label>Label<input data-choice-field="label" data-stage="${escapeHtml(stageId)}" data-choice-index="${index}" value="${escapeHtml(choice.label || "")}"></label>
      <label class="wide">Result text<textarea data-choice-field="resultText" data-stage="${escapeHtml(stageId)}" data-choice-index="${index}">${escapeHtml(choice.resultText || "")}</textarea></label>
      <label>Pending action text<input data-choice-field="pendingAction.text" data-stage="${escapeHtml(stageId)}" data-choice-index="${index}" value="${escapeHtml(choice.pendingAction?.text || "")}"></label>
      <label>Delay profile<input data-choice-field="pendingAction.delayProfile" data-stage="${escapeHtml(stageId)}" data-choice-index="${index}" value="${escapeHtml(choice.pendingAction?.delayProfile || "")}"></label>
      <label class="check-chip"><input type="checkbox" data-choice-field="endEncounter" data-stage="${escapeHtml(stageId)}" data-choice-index="${index}"${checked(choice.endEncounter)}> Ends encounter</label>
    </div>
    ${renderObjectCollection("Requirements", choice.requirements, "requirements", stageId, index, `stages.${stageId}.choices[${index}]`)}
    ${renderObjectCollection("Costs", choice.costs, "costs", stageId, index, `stages.${stageId}.choices[${index}]`)}
    ${renderObjectCollection("Outcomes / effects", choice.outcomes, "outcomes", stageId, index, `stages.${stageId}.choices[${index}]`)}
    <div class="button-row"><button type="button" class="small-button danger-outline" data-action="remove-choice" data-stage="${escapeHtml(stageId)}" data-choice-index="${index}">Remove choice</button></div>
  </details>`;
}

function renderEncounter() {
  const encounter = state.draft;
  if (!encounter) return `<div class="empty-state">Choose an encounter to edit.</div>`;
  const known = state.catalog.known || {};
  const stageEntries = Object.entries(encounter.stages || {});
  const stageMarkup = stageEntries.map(([stageId, stage]) => {
    const choices = Array.isArray(stage.choices) ? stage.choices : [];
    return `<details class="stage-card" open>
      <summary>${escapeHtml(stageId)}${stage.resultStage ? " · result stage" : ""}</summary>
      <label>Stage text<textarea data-stage-field="text" data-stage="${escapeHtml(stageId)}">${escapeHtml(stage.text || "")}</textarea></label>
      ${renderObjectCollection("Stage outcomes / effects", stage.outcomes, "stage-outcomes", stageId, -1, `stages.${stageId}`)}
      <div class="nested-heading"><span>Choices <span class="panel-count">${choices.length}</span></span><button type="button" class="small-button" data-action="add-choice" data-stage="${escapeHtml(stageId)}">Add choice</button></div>
      ${choices.map((choice, index) => renderChoice(stageId, choice, index)).join("") || `<p class="hint">This result stage resolves automatically and has no choices.</p>`}
      <div class="button-row"><button type="button" class="small-button danger-outline" data-action="remove-stage" data-stage="${escapeHtml(stageId)}">Remove stage</button></div>
    </details>`;
  }).join("");
  return `<div class="editor-title"><div><h2>${escapeHtml(encounter.title || encounter.id || "New encounter")}</h2><p>${escapeHtml(encounter.id || "Unsaved ID")}</p></div><span class="schema-badge">Encounter schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Metadata</h3><p>Stable IDs and travel filters are written back to encounter-data.js.</p></div></div>
      <div class="form-grid">
        <label>ID<input data-field="id" value="${escapeHtml(encounter.id || "")}"></label>
        <label>Title<input data-field="title" value="${escapeHtml(encounter.title || "")}"></label>
        <label class="wide">Description<textarea data-field="description">${escapeHtml(encounter.description || "")}</textarea></label>
        <label>Region<select data-field="regionId"><option value="">Select region…</option>${selectOptions(known.regions || [], encounter.regionId)}</select></label>
        <label>Weight<input type="number" step="any" data-field="weight" value="${escapeHtml(encounter.weight ?? "")}"></label>
        <label>Minimum distance<input type="number" step="any" data-field="minimumDistance" value="${escapeHtml(encounter.minimumDistance ?? "")}"></label>
        <label>Maximum distance<input type="number" step="any" data-field="maximumDistance" value="${escapeHtml(encounter.maximumDistance ?? "")}"></label>
        <label>Max occurrences per run<input type="number" step="1" data-field="maxOccurrencesPerRun" value="${escapeHtml(encounter.maxOccurrencesPerRun ?? "")}" placeholder="optional"></label>
        <label class="wide">Tags<input data-array-field="tags" value="${escapeHtml((encounter.tags || []).join(", "))}" placeholder="forest, discovery"></label>
        <label class="check-chip"><input type="checkbox" data-field="repeatable"${checked(encounter.repeatable)}> Repeatable</label>
      </div>
      <div class="section-heading" style="margin-top:14px"><div><h3>Paths</h3><p>Choose the path IDs where this encounter can appear.</p></div></div>
      <div class="path-membership-grid">${(known.paths || []).map((pathId) => `<div class="path-membership-row"><label class="check-chip"><input type="checkbox" data-array-toggle="pathIds" data-array-value="${escapeHtml(pathId)}"${checked((encounter.pathIds || []).includes(pathId))}>${escapeHtml(pathLabel(pathId))}</label><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="paths" data-reference-id="${escapeHtml(pathId)}">Open Path</button></div>`).join("")}</div>
      <div class="section-heading" style="margin-top:14px"><div><h3>Directions</h3><p>Direction filters are kept as authored IDs.</p></div></div>
      <div class="check-grid">${["outbound", "returning"].map((direction) => `<label class="check-chip"><input type="checkbox" data-array-toggle="directions" data-array-value="${direction}"${checked((encounter.directions || []).includes(direction))}>${direction}</label>`).join("")}</div>
      ${renderObjectCollection("Encounter requirements", encounter.requirements, "encounter-requirements", "", -1, "")}
    </section>
    <section class="section"><div class="section-heading"><div><h3>Stages and choices</h3><p>Common nested fields are editable above; advanced JSON remains available for every authored object.</p></div><button type="button" class="small-button" data-action="add-stage">Add stage</button></div>
      ${stageMarkup || `<div class="empty-state">Add a stage to begin authoring this encounter.</div>`}
    </section>
    <section class="section"><details><summary>Raw encounter JSON (advanced)</summary><p class="hint">Use this escape hatch for fields not exposed in the details editor. Apply JSON to update the in-memory draft; it is still validated before save.</p><textarea id="raw-json" class="raw-editor">${jsonText(encounter)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderInjury() {
  const injury = state.draft;
  if (!injury) return `<div class="empty-state">Choose an injury to edit.</div>`;
  const known = state.catalog.known || {};
  const effects = injury.effects || {};
  const references = (liveReferences().injuries || []).filter((reference) => reference.id === injury.id);
  const effectFields = [...new Set(["travelSpeedMultiplier", "hardPushRiskMultiplier", "maxHealthMultiplier", "defenseMultiplier", "combatGaugeRateMultiplier", "incomingDamageMultiplier", ...Object.keys(effects)])];
  return `<div class="editor-title"><div><h2>${escapeHtml(injury.name || injury.id || "New injury")}</h2><p>${escapeHtml(injury.id || "Unsaved ID")}</p></div><span class="schema-badge">Injury schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Injury identity</h3><p>Injuries are authored in <code>js/injury-data.js</code>; treatment and travel behavior remain data-driven.</p></div></div>
      <div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(injury.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(injury.name || "")}"></label><label>Short name<input data-field="shortName" value="${escapeHtml(injury.shortName || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(injury.description || "")}</textarea></label><label>Treatment item${referenceInput("treatmentItemId", injury.treatmentItemId, true)}</label></div>
    </section>
    <section class="section"><div class="section-heading"><div><h3>Recovery and travel damage</h3><p>Optional fields remain absent when left blank, preserving legacy definitions.</p></div></div><div class="form-grid"><label>Recovery minimum<input type="number" min="0" step="any" data-injury-field="recoveryDistanceRange.minimum" value="${escapeHtml(injury.recoveryDistanceRange?.minimum ?? "")}"></label><label>Recovery maximum<input type="number" min="0" step="any" data-injury-field="recoveryDistanceRange.maximum" value="${escapeHtml(injury.recoveryDistanceRange?.maximum ?? "")}"></label><label>Infection check distance<input type="number" min="0" step="any" data-field="infectionCheckDistance" value="${escapeHtml(injury.infectionCheckDistance ?? "")}"></label><label>Infection chance<input type="number" min="0" max="1" step="any" data-field="infectionChance" value="${escapeHtml(injury.infectionChance ?? "")}"></label><label>Travel damage amount<input type="number" min="0" step="any" data-field="travelDamageAmount" value="${escapeHtml(injury.travelDamageAmount ?? "")}"></label><label>Travel damage interval<input type="number" min="0" step="any" data-field="travelDamageInterval" value="${escapeHtml(injury.travelDamageInterval ?? "")}"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Generic effects</h3><p>Known effect fields are quick-editable and additional authored keys remain available.</p></div></div><div class="form-grid">${effectFields.map((field) => `<label>${escapeHtml(field)}<input type="number" step="any" data-injury-effect-field="${escapeHtml(field)}" value="${escapeHtml(effects[field] ?? "")}"></label>`).join("")}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known encounter, item, and combat references are shown before deletion.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No known current references to this injury.")}</div></section>
    <section class="section"><details><summary>Raw injury JSON (advanced)</summary><p class="hint">Use this escape hatch for future injury shapes that are not yet represented by a dedicated control.</p><textarea id="raw-json" class="raw-editor">${jsonText(injury)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderCampEvent() {
  const event = state.draft;
  if (!event) return `<div class="empty-state">Choose a camp event to edit.</div>`;
  const known = state.catalog.known || {};
  const references = (liveReferences().campEvents || []).filter((reference) => reference.id === event.id);
  const stageMarkup = Object.entries(event.stages || {}).map(([stageId, stage]) => {
    const choices = Array.isArray(stage.choices) ? stage.choices : [];
    return `<details class="stage-card" open><summary>${escapeHtml(stageId)}${stage.resultStage ? " · result stage" : ""}</summary><label>Stage text<textarea data-stage-field="text" data-stage="${escapeHtml(stageId)}">${escapeHtml(stage.text || "")}</textarea></label>${renderObjectCollection("Stage outcomes / effects", stage.outcomes, "stage-outcomes", stageId, -1, `stages.${stageId}`)}<div class="nested-heading"><span>Choices <span class="panel-count">${choices.length}</span></span><button type="button" class="small-button" data-action="add-choice" data-stage="${escapeHtml(stageId)}">Add choice</button></div>${choices.map((choice, index) => renderChoice(stageId, choice, index)).join("") || `<p class="hint">This result stage resolves automatically and has no choices.</p>`}<div class="button-row"><button type="button" class="small-button danger-outline" data-action="remove-stage" data-stage="${escapeHtml(stageId)}">Remove stage</button></div></details>`;
  }).join("");
  return `<div class="editor-title"><div><h2>${escapeHtml(event.title || event.id || "New camp event")}</h2><p>${escapeHtml(event.id || "Unsaved ID")}</p></div><span class="schema-badge">Camp event schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Camp event identity</h3><p>Camp events are authored in <code>js/camp-data.js</code> and selected through expedition camp-event tables.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(event.id || "")}"></label><label>Title<input data-field="title" value="${escapeHtml(event.title || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(event.description || "")}</textarea></label><label>Region<select data-field="regionId"><option value="">Select region...</option>${selectOptions(known.regions || [], event.regionId)}</select></label><label>Weight<input type="number" step="any" data-field="weight" value="${escapeHtml(event.weight ?? "")}" placeholder="optional"></label><label>Minimum distance<input type="number" step="any" data-field="minimumDistance" value="${escapeHtml(event.minimumDistance ?? "")}" placeholder="optional"></label><label>Maximum distance<input type="number" step="any" data-field="maximumDistance" value="${escapeHtml(event.maximumDistance ?? "")}" placeholder="optional"></label><label>Max occurrences per run<input type="number" step="1" data-field="maxOccurrencesPerRun" value="${escapeHtml(event.maxOccurrencesPerRun ?? "")}" placeholder="optional"></label><label class="wide">Tags<input data-array-field="tags" value="${escapeHtml((event.tags || []).join(", "))}" placeholder="camp, discovery"></label></div><div class="section-heading" style="margin-top:14px"><div><h3>Paths</h3><p>Optional path applicability is stored as authored path IDs.</p></div></div>${renderReferenceChecks("pathIds", event.pathIds || [], known.paths || [], Object.fromEntries((known.paths || []).map((id) => [id, pathLabel(id)])))}${Object.prototype.hasOwnProperty.call(event, "expeditionIds") ? `<div class="section-heading" style="margin-top:14px"><div><h3>Expeditions</h3></div></div>${renderReferenceChecks("expeditionIds", event.expeditionIds || [], Object.keys(state.catalog.expeditions || {}).sort(), Object.fromEntries(Object.keys(state.catalog.expeditions || {}).map((id) => [id, expeditionLabel(id)])))}` : ""}${renderObjectCollection("Camp event requirements", event.requirements, "camp-event-requirements", "", -1, "")}</section>
    <section class="section"><div class="section-heading"><div><h3>Stages and choices</h3><p>Camp events reuse the encounter stage, requirement, cost, and recursive outcome editor.</p></div><button type="button" class="small-button" data-action="add-stage">Add stage</button></div>${stageMarkup || `<div class="empty-state">Add a stage to begin authoring this camp event.</div>`}</section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Camp-event tables and other known definitions are shown before deletion.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No known current references to this camp event.")}</div></section><section class="section"><details><summary>Raw camp event JSON (advanced)</summary><p class="hint">Use this escape hatch for future camp-event fields while the visible editor covers common authored structures.</p><textarea id="raw-json" class="raw-editor">${jsonText(event)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function refreshDerivedPaths() {
  if (!state.catalog) return;
  const previous = state.catalog.paths || {};
  const next = {};
  Object.values(state.catalog.encounters || {}).forEach((encounter) => {
    (encounter?.pathIds || []).forEach((pathId) => {
      if (typeof pathId !== "string") return;
      next[pathId] ||= { ...(previous[pathId] || {}), id: pathId, name: previous[pathId]?.name || pathId, derived: true, encounterCount: 0, expeditionIds: [] };
      next[pathId].encounterCount = (next[pathId].encounterCount || 0) + 1;
    });
  });
  Object.entries(state.catalog.expeditions || {}).forEach(([expeditionId, expedition]) => {
    const pathId = expedition?.pathId;
    if (typeof pathId !== "string") return;
    next[pathId] ||= { ...(previous[pathId] || {}), id: pathId, name: pathId, derived: true, encounterCount: 0, expeditionIds: [] };
    next[pathId].expeditionIds = [...new Set([...(next[pathId].expeditionIds || []), expeditionId])].sort();
    next[pathId].name = expedition.name || next[pathId].name || pathId;
    ["description", "regionId", "kind", "danger"].forEach((field) => {
      if (expedition[field] !== undefined) next[pathId][field] = expedition[field];
    });
  });
  Object.values(next).forEach((path) => {
    if (path.expeditionIds?.length === 1) path.expeditionId = path.expeditionIds[0];
  });
  state.catalog.paths = Object.fromEntries(Object.entries(next).sort(([a], [b]) => a.localeCompare(b)));
}

function renderPath() {
  const path = state.catalog.paths?.[state.selectedId];
  if (!path) return `<div class="empty-state"><h2>No derived path selected</h2><p>Paths appear when live encounter memberships or expedition pathId fields reference them.</p></div>`;
  const pathId = path.id;
  const filters = state.pathFilters;
  const linkedExpeditions = (path.expeditionIds || []).map((id) => state.catalog.expeditions?.[id]).filter(Boolean);
  const allEncounters = Object.entries(state.catalog.encounters || {}).filter(([, encounter]) => (encounter.pathIds || []).includes(pathId));
  const tags = [...new Set(allEncounters.flatMap(([, encounter]) => encounter.tags || []))].sort();
  const filtered = allEncounters.filter(([id, encounter]) => {
    const haystack = `${id} ${encounter.title || ""} ${(encounter.tags || []).join(" ")}`.toLowerCase();
    if (filters.search && !haystack.includes(filters.search.toLowerCase())) return false;
    if (filters.tag && !(encounter.tags || []).includes(filters.tag)) return false;
    if (filters.direction === "both") {
      if (!((encounter.directions || []).includes("outbound") && (encounter.directions || []).includes("returning"))) return false;
    } else if (filters.direction !== "all" && !(encounter.directions || []).includes(filters.direction)) return false;
    if (!overlapsDistanceRange(encounter, filters.minDistance, filters.maxDistance)) return false;
    return true;
  }).sort(([, a], [, b]) => {
    if (filters.sort === "distance") return Number(a.minimumDistance || 0) - Number(b.minimumDistance || 0);
    if (filters.sort === "weight") return Number(b.weight || 0) - Number(a.weight || 0);
    return String(a.title || "").localeCompare(String(b.title || ""));
  });
  const distances = allEncounters.flatMap(([, encounter]) => [encounter.minimumDistance, encounter.maximumDistance]).filter((value) => typeof value === "number");
  const summary = {
    outbound: allEncounters.filter(([, encounter]) => (encounter.directions || []).includes("outbound")).length,
    returning: allEncounters.filter(([, encounter]) => (encounter.directions || []).includes("returning")).length,
    minimum: distances.length ? Math.min(...distances) : "—",
    maximum: distances.length ? Math.max(...distances) : "—",
  };
  const available = Object.entries(state.catalog.encounters || {}).filter(([, encounter]) => !(encounter.pathIds || []).includes(pathId)).sort(([, a], [, b]) => String(a.title || "").localeCompare(String(b.title || "")));
  const linkedMarkup = linkedExpeditions.length
    ? linkedExpeditions.map((expedition) => `<button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="expeditions" data-reference-id="${escapeHtml(expedition.id)}">Open ${escapeHtml(expedition.name || expedition.id)}</button>`).join(" ")
    : `<span class="hint">No expedition owns this pathId; this is a legacy/derived path membership.</span>`;
  const encounterRows = filtered.map(([id, encounter]) => `<div class="path-encounter-row"><div><strong>${escapeHtml(encounter.title || id)}</strong><code>${escapeHtml(id)}</code><span class="hint">${escapeHtml((encounter.directions || []).join(", ") || "no direction")} · distance ${escapeHtml(encounter.minimumDistance ?? "—")}${encounter.maximumDistance !== undefined ? `–${escapeHtml(encounter.maximumDistance)}` : ""} · weight ${escapeHtml(encounter.weight ?? "—")}</span></div><div class="button-row"><button type="button" class="small-button" data-action="open-reference" data-reference-category="encounters" data-reference-id="${escapeHtml(id)}">Open Encounter</button><button type="button" class="small-button danger-outline" data-action="remove-encounter-from-path" data-path-id="${escapeHtml(pathId)}" data-encounter-id="${escapeHtml(id)}">Remove</button></div></div>`).join("");
  return `<div class="editor-title"><div><h2>${escapeHtml(path.name || pathId)}</h2><p>${escapeHtml(pathId)}</p></div><span class="schema-badge">Derived Path view</span></div>
    <section class="section"><div class="notice"><strong>Derived view, not a standalone definition</strong><p>Grail currently authors path IDs through encounter <code>pathIds</code> memberships and expedition <code>pathId</code> fields. This page edits encounter membership only; expedition metadata is edited in Expeditions.</p></div>
      <div class="form-grid"><label>Path ID<input value="${escapeHtml(pathId)}" readonly></label><label>Display name<input value="${escapeHtml(path.name || pathId)}" readonly></label><label>Region<input value="${escapeHtml(path.regionId || "—")}" readonly></label><label>Source<input value="${escapeHtml(linkedExpeditions.length ? "Expedition + encounters" : "Encounter memberships only")}" readonly></label></div>
      <div class="section-heading" style="margin-top:14px"><div><h3>Linked expedition</h3><p>Open the canonical expedition to edit authored name, danger, camp tables, prerequisites, or pathId.</p></div></div><div class="button-row">${linkedMarkup}</div>
    </section>
    <section class="section"><div class="section-heading"><div><h3>Path summary</h3><p>${allEncounters.length} encounter membership${allEncounters.length === 1 ? "" : "s"} on this path.</p></div></div><div class="summary-grid"><div><strong>${allEncounters.length}</strong><span>Total encounters</span></div><div><strong>${summary.outbound}</strong><span>Outbound</span></div><div><strong>${summary.returning}</strong><span>Returning</span></div><div><strong>${summary.minimum}–${summary.maximum}</strong><span>Distance range</span></div></div></section>
    <section class="section"><div class="section-heading"><div><h3>Encounter filters</h3><p>Search and sort the reverse relationship without changing authored data.</p></div><span class="panel-count">${filtered.length} / ${allEncounters.length}</span></div><div class="form-grid"><label>Search<input type="search" data-path-filter="search" value="${escapeHtml(filters.search)}" placeholder="title, ID, tag"></label><label>Direction<select data-path-filter="direction"><option value="all"${selected("all", filters.direction)}>All directions</option><option value="outbound"${selected("outbound", filters.direction)}>Outbound</option><option value="returning"${selected("returning", filters.direction)}>Returning</option><option value="both"${selected("both", filters.direction)}>Both directions</option></select></label><label>Minimum distance<input type="number" data-path-filter="minDistance" value="${escapeHtml(filters.minDistance)}"></label><label>Maximum distance<input type="number" data-path-filter="maxDistance" value="${escapeHtml(filters.maxDistance)}"></label><label>Tag<select data-path-filter="tag"><option value="">All tags</option>${tags.map((tag) => `<option value="${escapeHtml(tag)}"${selected(tag, filters.tag)}>${escapeHtml(tag)}</option>`).join("")}</select></label><label>Sort<select data-path-filter="sort"><option value="title"${selected("title", filters.sort)}>Title</option><option value="distance"${selected("distance", filters.sort)}>Distance</option><option value="weight"${selected("weight", filters.sort)}>Weight</option></select></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Encounters on this Path</h3><p>Remove only this path membership; the encounter and its other path memberships remain intact.</p></div></div><div class="path-encounter-list">${encounterRows || `<p class="hint">No encounters match the current filters.</p>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Add existing encounter to this path</h3><p>Membership editing never creates a duplicate encounter definition.</p></div></div><div class="reference-inline"><select id="path-add-encounter"><option value="">Select an existing encounter...</option>${available.map(([id, encounter]) => `<option value="${escapeHtml(id)}">${escapeHtml(encounter.title || id)} (${escapeHtml(id)})</option>`).join("")}</select><button type="button" class="small-button" data-action="add-encounter-to-path" data-path-id="${escapeHtml(pathId)}">Add to Path</button></div></section>`;
}

function renderReferenceChecks(field, ids, values, labels = {}) {
  return `<div class="check-grid compact-check-grid">${values.map((id) => `<label class="check-chip"><input type="checkbox" data-array-toggle="${field}" data-array-value="${escapeHtml(id)}"${checked(ids.includes(id))}>${escapeHtml(labels[id] || id)}</label>`).join("") || `<span class="hint">No known references are available.</span>`}</div>`;
}

function renderExpedition() {
  const expedition = state.draft;
  if (!expedition) return `<div class="empty-state">Choose an expedition to edit.</div>`;
  const known = state.catalog.known || {};
  const kinds = [...new Set([...(Object.values(state.catalog.expeditions || {}).map((value) => value.kind).filter(Boolean)), expedition.kind].filter(Boolean))].sort();
  const references = (liveReferences().expeditions || []).filter((reference) => reference.id === expedition.id);
  const campEventLinks = [...new Set((expedition.campEventTableIds || []).flatMap((tableId) => (state.catalog.campEventTables?.[tableId]?.entries || []).map((entry) => entry.eventId)).filter((eventId) => state.catalog.campEvents?.[eventId]))].map((eventId) => `<button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="campEvents" data-reference-id="${escapeHtml(eventId)}">Open ${escapeHtml(campEventLabel(eventId))}</button>`).join(" ");
  return `<div class="editor-title"><div><h2>${escapeHtml(expedition.name || expedition.id || "New expedition")}</h2><p>${escapeHtml(expedition.id || "Unsaved ID")}</p></div><span class="schema-badge">Expedition schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Expedition metadata</h3><p>These fields are authored in <code>js/expedition-data.js</code> and remain the canonical expedition definition.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(expedition.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(expedition.name || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(expedition.description || "")}</textarea></label><label>Danger<input type="number" min="0" step="any" data-field="danger" value="${escapeHtml(expedition.danger ?? "")}"></label><label>Region<select data-field="regionId"><option value="">Select region...</option>${selectOptions(known.regions || [], expedition.regionId)}</select></label><label>Kind<select data-field="kind"><option value="">Select kind...</option>${selectOptions(kinds, expedition.kind)}</select></label><label class="wide">Path${referenceInput("pathId", expedition.pathId, true)}</label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Camp event tables</h3><p>Choose reusable table IDs from <code>CAMP_EVENT_TABLE_DEFINITIONS</code>.</p></div></div>${renderReferenceChecks("campEventTableIds", expedition.campEventTableIds || [], known.campEventTables || [])}<div class="button-row">${campEventLinks || `<span class="hint">Selected tables have no editable camp-event entries.</span>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Prerequisites</h3><p>These are item IDs required by the existing expedition runtime.</p></div></div>${renderReferenceChecks("prerequisites", expedition.prerequisites || [], known.items || [], Object.fromEntries((known.items || []).map((id) => [id, itemLabel(id)])))}</section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known encounter and location references are shown before an expedition is deleted.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No known current references to this expedition.")}</div></section>
    <section class="section"><details><summary>Raw expedition JSON (advanced)</summary><p class="hint">Use raw JSON for future schema fields while preserving validation and surgical source updates.</p><textarea id="raw-json" class="raw-editor">${jsonText(expedition)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function collectClientReferences(value, source, references) {
  const scalarTypes = {
    itemId: "items", treatmentItemId: "items", combatId: "combats", abilityId: "abilities", injuryId: "injuries",
    tableId: "lootTables", lootTableId: "lootTables", pathId: "paths", expeditionId: "expeditions",
    nextExpeditionId: "expeditions", materialId: "materials", recipeId: "recipes",
    craftingProvider: "craftingProviders", craftingProviderId: "craftingProviders", eventId: "campEvents", campEventId: "campEvents", knowledgeId: "knowledge", companionId: "companions",
  };
  const listTypes = {
    itemIds: "items", injuryIds: "injuries", prerequisites: "items", enemyIds: "enemies", abilityIds: "abilities",
    grantedAbilityIds: "abilities", combatAbilities: "abilities", actionPattern: "enemyActions",
    pathIds: "paths", expeditionIds: "expeditions", availableExpeditions: "expeditions", campEventTableIds: "campEventTables", recipeIds: "recipes",
  };
  function visit(node, path = "") {
    if (Array.isArray(node)) {
      node.forEach((child, index) => visit(child, `${path}[${index}]`));
      return;
    }
    if (!node || typeof node !== "object") return;
    Object.entries(node).forEach(([key, child]) => {
      const childPath = path ? `${path}.${key}` : key;
      const scalarType = scalarTypes[key];
      if (scalarType && typeof child === "string") {
        (references[scalarType] ||= []).push({ source, path: childPath, id: child });
      }
      const listType = listTypes[key];
      if (listType && Array.isArray(child)) {
        child.forEach((id, index) => {
          if (typeof id === "string") (references[listType] ||= []).push({ source, path: `${childPath}[${index}]`, id });
        });
      }
      if (["itemsForSale", "sellValues"].includes(key) && child && typeof child === "object" && !Array.isArray(child)) {
        Object.keys(child).forEach((id) => (references.items ||= []).push({ source, path: `${childPath}.${id}`, id }));
      }
      if (key === "ingredients" && child && typeof child === "object" && !Array.isArray(child)) {
        const refType = node.ingredientType === "item" ? "items" : "materials";
        Object.keys(child).forEach((id) => (references[refType] ||= []).push({ source, path: `${childPath}.${id}`, id }));
      }
      visit(child, childPath);
    });
  }
  visit(value);
}

function liveReferences() {
  if (!state.catalog) return {};
  const references = {};
  const snapshot = draftSnapshot();
  ["encounters", "injuries", "campEvents", "expeditions", "recipes", "materials", "craftingProviders", "shops", "items", "combats", "abilities", "enemyDefinitions", "enemyActions", "lootTables"].forEach((source) => {
    collectClientReferences(snapshot[source], source, references);
  });
  Object.entries(state.catalog.references || {}).forEach(([type, entries]) => {
    entries.filter((entry) => !EDITABLE_REFERENCE_SOURCES.has(entry.source)).forEach((entry) => {
      (references[type] ||= []).push(entry);
    });
  });
  return references;
}

function referenceCategory(source) {
  return { encounters: "encounters", injuries: "injuries", campEvents: "campEvents", campEventTables: "campEvents", expeditions: "expeditions", recipes: "recipes", materials: "materials", craftingProviders: "craftingProviders", shops: "shops", items: "items", combats: "combats", abilities: "abilities", lootTables: "lootTables" }[source] || null;
}

function referenceTitle(source, id) {
  if (source === "items") return itemLabel(id);
  if (source === "abilities") return abilityLabel(id);
  if (source === "enemies") return enemyLabel(id);
  if (source === "paths") return pathLabel(id);
  if (source === "expeditions") return expeditionLabel(id);
  if (source === "recipes") return recipeLabel(id);
  if (source === "materials") return materialLabel(id);
  if (source === "craftingProviders") return providerLabel(id);
  if (source === "injuries") return injuryLabel(id);
  if (source === "campEvents") return campEventLabel(id);
  if (source === "campEventTables") return campEventLabel(id);
  return id;
}

function referenceSourceId(reference) {
  if (reference.source === "campEventTables") return reference.id;
  return String(reference.path || "").split(/[.\[]/, 1)[0] || reference.id;
}

function renderReferenceRows(references, emptyText = "No known references.") {
  if (!references.length) return `<p class="hint">${escapeHtml(emptyText)}</p>`;
  return references.map((reference) => {
    const category = referenceCategory(reference.source);
    const open = category
      ? `<button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="${category}" data-reference-id="${escapeHtml(referenceSourceId(reference))}">Open</button>`
      : "";
    return `<div class="reference-row"><strong>${escapeHtml(reference.source)}</strong><span>${escapeHtml(referenceTitle(reference.source, reference.id))}</span><code>${escapeHtml(reference.path)}</code>${open}</div>`;
  }).join("");
}

function recipeIngredientOptions(recipe, currentId) {
  const ingredientType = recipe.ingredientType || "material";
  const values = ingredientType === "item"
    ? Object.keys(state.catalog.items || {}).sort()
    : Object.keys(state.catalog.materials || {}).sort();
  const labels = ingredientType === "item"
    ? Object.fromEntries(values.map((id) => [id, itemLabel(id)]))
    : Object.fromEntries(values.map((id) => [id, materialLabel(id)]));
  const currentOption = currentId && !values.includes(currentId)
    ? `<option value="${escapeHtml(currentId)}" selected>${escapeHtml(ingredientType === "item" ? itemLabel(currentId) : materialLabel(currentId))}</option>`
    : "";
  return `<option value="">Select ${ingredientType}...</option>${currentOption}${selectOptions(values, currentId, labels)}`;
}

function renderRecipeIngredientRows(recipe) {
  const ingredients = Object.entries(recipe.ingredients || {});
  return ingredients.map(([ingredientId, quantity], index) => `<div class="recipe-ingredient-row" data-recipe-ingredient-row data-ingredient-id="${escapeHtml(ingredientId)}">
    <select data-recipe-ingredient-field="id" data-ingredient-index="${index}">${recipeIngredientOptions(recipe, ingredientId)}</select>
    <input type="number" min="1" step="1" data-recipe-ingredient-field="quantity" data-ingredient-index="${index}" value="${escapeHtml(quantity ?? "")}" aria-label="Ingredient quantity">
    ${recipe.ingredientType === "item" ? `<button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="items" data-reference-id="${escapeHtml(ingredientId)}">Open Item</button>` : `<span class="recipe-ref-kind">Material</span>`}
    <button type="button" class="small-button" data-action="duplicate-recipe-ingredient" data-ingredient-index="${index}">Duplicate</button><button type="button" class="small-button danger-outline" data-action="remove-recipe-ingredient" data-ingredient-index="${index}">Remove</button>
  </div>`).join("");
}

function recipeOutputType(recipe) {
  return recipe.output?.itemId ? "item" : "provisions";
}

function renderRecipe() {
  const recipe = state.draft;
  if (!recipe) return `<div class="empty-state">Choose a recipe to edit.</div>`;
  const known = state.catalog.known || {};
  const outputType = recipeOutputType(recipe);
  const output = recipe.output || {};
  const references = (liveReferences().recipes || []).filter((reference) => reference.id === recipe.id);
  const providerIds = Object.keys(state.catalog.craftingProviders || {}).sort();
  const rarityIds = known.rarities || [];
  return `<div class="editor-title"><div><h2>${escapeHtml(recipe.name || recipe.id || "New recipe")}</h2><p>${escapeHtml(recipe.id || "Unsaved ID")} · Produces: ${escapeHtml(outputType === "item" ? itemLabel(output.itemId || "") : `${output.provisions ?? 0} provisions`)}</p></div><span class="schema-badge">Recipe schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Recipe identity</h3><p>Recipes are authored in <code>js/crafting-data.js</code>.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(recipe.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(recipe.name || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(recipe.description || "")}</textarea></label><label>Rarity<select data-field="rarity"><option value="">No rarity</option>${selectOptions(rarityIds, recipe.rarity)}</select></label><label class="check-chip"><input type="checkbox" data-field="starter"${checked(recipe.starter)}> Starter recipe</label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Crafting provider</h3><p>Provider IDs are selected from the live <code>CRAFTING_PROVIDER_DEFINITIONS</code> catalog.</p></div></div><div class="form-grid"><label>Provider${referenceInput("craftingProvider", recipe.craftingProvider, true)}</label><label>Gold cost<input type="number" min="0" step="1" data-field="goldCost" value="${escapeHtml(recipe.goldCost ?? "")}"></label><label>Crafting duration (ms)<input type="number" min="1" step="1" data-field="craftingDurationMs" value="${escapeHtml(recipe.craftingDurationMs ?? "")}" placeholder="provider default"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Ingredients</h3><p>Current runtime supports material ingredients by default and item ingredients when <code>ingredientType</code> is <code>item</code>.</p></div><button type="button" class="small-button" data-action="add-recipe-ingredient">Add ingredient</button></div><div class="recipe-ingredient-type"><label>Ingredient type<select data-field="ingredientType"><option value="material"${selected("material", recipe.ingredientType || "material")}>Materials</option><option value="item"${selected("item", recipe.ingredientType)}>Items</option></select></label></div><div class="recipe-ingredient-list">${renderRecipeIngredientRows(recipe) || `<p class="hint">No ingredients. Add one to make this recipe craftable.</p>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Output</h3><p>Expose the current item or provisions result shape without requiring raw JSON.</p></div></div><div class="form-grid"><label>Output type<select data-recipe-output-type><option value="item"${selected("item", outputType)}>Item</option><option value="provisions"${selected("provisions", outputType)}>Provisions</option></select></label>${outputType === "item" ? `<label>Quantity<input type="number" min="1" step="1" data-recipe-output-field="quantity" value="${escapeHtml(output.quantity ?? "")}"></label><label class="wide">Output item<span class="reference-inline"><input list="item-options" data-recipe-output-field="itemId" value="${escapeHtml(output.itemId || "")}" placeholder="Search item..."><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="items" data-reference-id="${escapeHtml(output.itemId || "")}">Open Item</button></span></label>` : `<label>Provisions<input type="number" min="1" step="1" data-recipe-output-field="provisions" value="${escapeHtml(output.provisions ?? "")}"></label>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by / references</h3><p>Known loot-table and other semantic recipe references.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No known current references. Loot tables can directly unlock this recipe.")}</div></section>
    <section class="section"><details><summary>Raw recipe JSON (advanced)</summary><p class="hint">Uncommon existing fields survive typed edits and can be edited here when needed.</p><textarea id="raw-json" class="raw-editor">${jsonText(recipe)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderMaterial() {
  const material = state.draft;
  if (!material) return `<div class="empty-state">Choose a material to edit.</div>`;
  const known = state.catalog.known || {};
  const references = (liveReferences().materials || []).filter((reference) => reference.id === material.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(material.name || material.id || "New material")}</h2><p>${escapeHtml(material.id || "Unsaved ID")}</p></div><span class="schema-badge">Material schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Material identity</h3><p>Materials are authored in <code>js/crafting-data.js</code> and remain the canonical recipe ingredient catalog.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(material.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(material.name || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(material.description || "")}</textarea></label><label>Rarity<select data-field="rarity"><option value="">Select rarity...</option>${selectOptions(known.rarities || [], material.rarity)}</select></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by / references</h3><p>Recipe ingredient references are checked before a material can be deleted.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No current recipe references.")}</div></section>
    <section class="section"><details><summary>Raw material JSON (advanced)</summary><textarea id="raw-json" class="raw-editor">${jsonText(material)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderCraftingProvider() {
  const provider = state.draft;
  if (!provider) return `<div class="empty-state">Choose a crafting provider to edit.</div>`;
  const recipes = Object.entries(state.catalog.recipes || {}).filter(([, recipe]) => recipe.craftingProvider === provider.id).sort(([, a], [, b]) => String(a.name || "").localeCompare(String(b.name || "")));
  const references = (liveReferences().craftingProviders || []).filter((reference) => reference.id === provider.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(provider.name || provider.id || "New provider")}</h2><p>${escapeHtml(provider.id || "Unsaved ID")}</p></div><span class="schema-badge">Crafting Provider schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Provider fields</h3><p>These are the actual fields in <code>CRAFTING_PROVIDER_DEFINITIONS</code>; recipe assignment lives on each Recipe.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(provider.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(provider.name || "")}"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Recipes at this Provider</h3><p>${recipes.length} recipe${recipes.length === 1 ? "" : "s"} use this provider.</p></div></div><div class="reference-list">${recipes.map(([id, recipe]) => `<div class="reference-row"><strong>Recipe</strong><span>${escapeHtml(recipe.name || id)}</span><code>${escapeHtml(id)}</code><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="recipes" data-reference-id="${escapeHtml(id)}">Open Recipe</button></div>`).join("") || `<p class="hint">No recipes currently use this provider.</p>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Locations and recipe definitions that reference this provider.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No other known references.")}</div></section>
    <section class="section"><details><summary>Raw provider JSON (advanced)</summary><textarea id="raw-json" class="raw-editor">${jsonText(provider)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderItemLegacy() {
  const item = state.draft;
  if (!item) return `<div class="empty-state">Choose an item to edit.</div>`;
  const known = state.catalog.known || {};
  const effects = item.effects && typeof item.effects === "object" ? item.effects : {};
  const damage = effects.combatDamage && typeof effects.combatDamage === "object" ? effects.combatDamage : {};
  const treatment = effects.treatment && typeof effects.treatment === "object" ? effects.treatment : {};
  const combat = effects.combat && typeof effects.combat === "object" ? effects.combat : {};
  const showDamage = item.category === "weapon" || Object.prototype.hasOwnProperty.call(effects, "combatDamage");
  const showDefense = item.category === "armor" || Object.prototype.hasOwnProperty.call(effects, "combatDefense");
  const showCombat = Object.prototype.hasOwnProperty.call(effects, "combat");
  const showTreatment = Object.prototype.hasOwnProperty.call(effects, "treatment");
  const references = (state.catalog.references?.items || []).filter((reference) => reference.id === item.id);
  const sourceLabels = { encounters: "Encounter", shops: "Shop", lootTables: "Loot table", recipes: "Recipe", expeditions: "Expedition", campEvents: "Camp event", locations: "Location" };
  const referenceMarkup = references.length ? references.map((reference) => `<div class="reference-row"><strong>${escapeHtml(sourceLabels[reference.source] || reference.source)}</strong><span>${escapeHtml(reference.path)}</span></div>`).join("") : `<p class="hint">No known current references. New items can be saved before they are added to an encounter, shop, recipe, or loot table.</p>`;
  const abilityMarkup = (known.abilities || []).map((abilityId) => `<label class="check-chip"><input type="checkbox" data-item-ability-toggle="${escapeHtml(abilityId)}"${checked((effects.grantedAbilityIds || []).includes(abilityId))}>${escapeHtml(state.catalog.abilityLabels?.[abilityId] || abilityId)}</label>`).join("");
  const injuryMarkup = (known.injuries || []).map((injuryId) => `<label class="check-chip"><input type="checkbox" data-item-treatment-toggle="${escapeHtml(injuryId)}"${checked((treatment.injuryIds || []).includes(injuryId))}>${escapeHtml(injuryId)}</label>`).join("");
  return `<div class="editor-title"><div><h2>${escapeHtml(item.name || item.id || "New item")}</h2><p>${escapeHtml(item.id || "Unsaved ID")}</p></div><span class="schema-badge">Item schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Identity</h3><p>Stable item IDs are referenced throughout encounters, shops, loot, recipes, and expedition content.</p></div></div>
      <div class="form-grid">
        <label>ID<input data-field="id" value="${escapeHtml(item.id || "")}"></label>
        <label>Name<input data-field="name" value="${escapeHtml(item.name || "")}"></label>
        <label class="wide">Description<textarea data-field="description">${escapeHtml(item.description || "")}</textarea></label>
        <label>Category<select data-field="category">${selectOptions(known.itemCategories || [], item.category)}</select></label>
        <label>Rarity<select data-field="rarity"><option value="">No rarity</option>${selectOptions(known.rarities || [], item.rarity)}</select></label>
        <label class="wide">Tags<input data-array-field="tags" value="${escapeHtml((item.tags || []).join(", "))}" placeholder="martial, steel"></label>
      </div>
    </section>
    <section class="section"><div class="section-heading"><div><h3>Inventory and flags</h3><p>These flags retain the current runtime item behavior without requiring raw JSON for common edits.</p></div></div>
      <div class="form-grid">
        <label class="check-chip"><input type="checkbox" data-field="equippable"${checked(item.equippable)}> Equippable</label>
        <label>Equipment slot<select data-field="equipmentSlot"><option value="">Not equipped</option>${selectOptions(known.equipmentSlots || [], item.equipmentSlot)}</select></label>
        <label class="check-chip"><input type="checkbox" data-field="carriable"${checked(item.carriable)}> Carriable</label>
        <label class="check-chip"><input type="checkbox" data-field="consumable"${checked(item.consumable)}> Consumable</label>
        <label>Maximum stack<input type="number" min="1" step="1" data-field="maxStack" value="${escapeHtml(item.maxStack ?? "")}" placeholder="optional"></label>
        <label class="check-chip"><input type="checkbox" data-field="questItem"${checked(item.questItem)}> Quest item</label>
        <label class="check-chip"><input type="checkbox" data-field="campaignItem"${checked(item.campaignItem)}> Campaign item</label>
        <label class="check-chip"><input type="checkbox" data-field="unique"${checked(item.unique)}> Unique</label>
        <label class="check-chip"><input type="checkbox" data-field="sellable"${checked(item.sellable)}> Sellable</label>
        <label class="check-chip"><input type="checkbox" data-field="protected"${checked(item.protected)}> Protected from unsafe deletion</label>
      </div>
    </section>
    <section class="section"><div class="section-heading"><div><h3>Combat effects</h3><p>Weapon damage, armor defense, and granted combat abilities are edited as typed fields.</p></div></div>
      ${showDamage ? `<div class="form-grid"><label>Damage minimum<input type="number" min="0" step="any" data-item-effect-field="combatDamage.minimum" value="${escapeHtml(damage.minimum ?? "")}"></label><label>Damage maximum<input type="number" min="0" step="any" data-item-effect-field="combatDamage.maximum" value="${escapeHtml(damage.maximum ?? "")}"></label></div>` : `<p class="hint">No weapon damage effect is present. Choose category Weapon or use the advanced effects editor below.</p>`}
      ${showDefense ? `<div class="form-grid" style="margin-top:11px"><label>Combat defense<input type="number" min="0" step="any" data-item-effect-field="combatDefense" value="${escapeHtml(effects.combatDefense ?? "")}"></label></div>` : ""}
      <div class="section-heading" style="margin-top:14px"><div><h4>Granted abilities</h4><p>Choose from COMBAT_ABILITY_DEFINITIONS; IDs are validated before save.</p></div></div>
      <div class="check-grid ability-grid">${abilityMarkup || `<span class="hint">No combat abilities are available.</span>`}</div>
    </section>
    ${showCombat ? `<section class="section"><div class="section-heading"><div><h3>Combat use effect</h3><p>Current combat-usable item fields, including healing and target text.</p></div></div><div class="form-grid"><label>Effect type<input data-item-combat-field="effectType" value="${escapeHtml(combat.effectType || "")}></label><label>Amount<input type="number" min="0" step="any" data-item-combat-field="amount" value="${escapeHtml(combat.amount ?? "")}"></label><label>Target<input data-item-combat-field="target" value="${escapeHtml(combat.target || "")}></label><label>Selection prompt<input data-item-combat-field="selectionPrompt" value="${escapeHtml(combat.selectionPrompt || "")}></label><label class="wide">Description<textarea data-item-combat-field="description">${escapeHtml(combat.description || "")}</textarea></label><label class="check-chip"><input type="checkbox" data-item-combat-field="usable"${checked(combat.usable)}> Usable in combat</label></div></section>` : ""}
    ${showTreatment ? `<section class="section"><div class="section-heading"><div><h3>Treatment effect</h3><p>Select the injuries this item can treat. Injury IDs are checked against the live injury definitions.</p></div></div><div class="check-grid">${injuryMarkup || `<span class="hint">No injuries are available.</span>`}</div></section>` : ""}
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known live references are shown here before an item is deleted.</p></div></div><div class="reference-list">${referenceMarkup}</div></section>
    <section class="section"><details><summary>Advanced effects JSON</summary><p class="hint">Use this escape hatch for uncommon effect shapes. The editor preserves authored fields and validates known nested structures.</p><textarea id="effects-json" class="raw-editor">${jsonText(effects)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-effects">Apply effects JSON</button></div></details></section>
    <section class="section"><details><summary>Raw item JSON (advanced)</summary><p class="hint">Apply raw JSON to update the in-memory draft. Validation still blocks unsafe writes.</p><textarea id="raw-json" class="raw-editor">${jsonText(item)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderShop() {
  const shop = state.draft;
  if (!shop) return `<div class="empty-state">Choose a shop to edit.</div>`;
  const stockRows = Object.entries(shop.itemsForSale || {}).map(([itemId, listing]) => `<div class="shop-row" data-shop-row data-item-id="${escapeHtml(itemId)}">
    <label>Item<input list="item-options" data-shop-item-field="itemId" value="${escapeHtml(itemId)}"></label>
    <label>Buy price<input type="number" min="0" step="1" data-shop-item-field="price" value="${escapeHtml(listing?.price ?? "")}"></label>
    <label class="unlimited"><input type="checkbox" data-shop-item-field="unlimited"${checked(listing && !Object.prototype.hasOwnProperty.call(listing, "stock"))}> Unlimited stock</label>
    <label class="stock-input">Stock<input type="number" min="0" step="1" data-shop-item-field="stock" value="${escapeHtml(listing?.stock ?? "")}"${listing && !Object.prototype.hasOwnProperty.call(listing, "stock") ? " disabled" : ""}></label>
    <button type="button" class="small-button danger-outline" data-action="remove-shop-item">Remove</button>
  </div>`).join("");
  const sellRows = Object.entries(shop.sellValues || {}).map(([itemId, value]) => `<div class="shop-row" data-sell-row data-item-id="${escapeHtml(itemId)}">
    <label>Item<input list="item-options" data-sell-item-field="itemId" value="${escapeHtml(itemId)}"></label>
    <label>Sell value<input type="number" min="0" step="1" data-sell-item-field="value" value="${escapeHtml(value ?? "")}"></label>
    <span></span><span></span><button type="button" class="small-button danger-outline" data-action="remove-sell-item">Remove</button>
  </div>`).join("");
  return `<div class="editor-title"><div><h2>${escapeHtml(shop.displayName || shop.id || "New shop")}</h2><p>${escapeHtml(shop.id || "Unsaved ID")}</p></div><span class="schema-badge">Shop schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Shop metadata</h3><p>Shop IDs are stable references from location-data.js.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(shop.id || "")}"></label><label>Display name<input data-field="displayName" value="${escapeHtml(shop.displayName || "")}"></label><label class="wide">Accepted categories<input data-array-field="acceptedCategories" value="${escapeHtml((shop.acceptedCategories || []).join(", "))}" placeholder="supply, consumable"></label><label class="wide">Accepted tags<input data-array-field="acceptedTags" value="${escapeHtml((shop.acceptedTags || []).join(", "))}" placeholder="medical, tool"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Items for sale</h3><p>Selectors are populated from the live ITEM_DEFINITIONS catalog. Omit stock for unlimited inventory.</p></div></div>
      ${stockRows || `<div class="empty-state">This shop has no item stock.</div>`}
      <div class="button-row"><input id="new-stock-item" list="item-options" placeholder="Search existing item…"><button type="button" class="small-button" data-action="add-shop-item">Add stock item</button></div>
    </section>
    <section class="section"><div class="section-heading"><div><h3>Sell values</h3><p>Items the shop accepts when the player sells goods.</p></div></div>
      ${sellRows || `<div class="empty-state">No sell values.</div>`}
      <div class="button-row"><input id="new-sell-item" list="item-options" placeholder="Search existing item…"><button type="button" class="small-button" data-action="add-sell-item">Add sell value</button></div>
    </section>
    <section class="section"><details><summary>Raw shop JSON (advanced)</summary><p class="hint">Apply raw JSON to update the in-memory draft. Validation still blocks unsafe writes.</p><textarea id="raw-json" class="raw-editor">${jsonText(shop)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderItem() {
  const item = state.draft;
  if (!item) return `<div class="empty-state">Choose an item to edit.</div>`;
  const known = state.catalog.known || {};
  const effects = item.effects && typeof item.effects === "object" ? item.effects : {};
  const damage = effects.combatDamage && typeof effects.combatDamage === "object" ? effects.combatDamage : {};
  const treatment = effects.treatment && typeof effects.treatment === "object" ? effects.treatment : {};
  const combat = effects.combat && typeof effects.combat === "object" ? effects.combat : {};
  const damageMarkup = item.category === "weapon" || Object.prototype.hasOwnProperty.call(effects, "combatDamage")
    ? `<div class="form-grid"><label>Damage minimum<input type="number" min="0" step="any" data-item-effect-field="combatDamage.minimum" value="${escapeHtml(damage.minimum ?? "")}"></label><label>Damage maximum<input type="number" min="0" step="any" data-item-effect-field="combatDamage.maximum" value="${escapeHtml(damage.maximum ?? "")}"></label></div>`
    : `<p class="hint">No weapon damage effect is present. Choose category Weapon or use the advanced effects editor.</p>`;
  const defenseMarkup = item.category === "armor" || Object.prototype.hasOwnProperty.call(effects, "combatDefense")
    ? `<div class="form-grid" style="margin-top:11px"><label>Combat defense<input type="number" min="0" step="any" data-item-effect-field="combatDefense" value="${escapeHtml(effects.combatDefense ?? "")}"></label></div>`
    : "";
  const abilityMarkup = (known.abilities || []).map((abilityId) => `<label class="check-chip"><input type="checkbox" data-item-ability-toggle="${escapeHtml(abilityId)}"${checked((effects.grantedAbilityIds || []).includes(abilityId))}>${escapeHtml(state.catalog.abilityLabels?.[abilityId] || abilityId)}</label>`).join("");
  const treatmentMarkup = Object.prototype.hasOwnProperty.call(effects, "treatment") ? `<section class="section"><div class="section-heading"><div><h3>Treatment effect</h3><p>Select injuries this item can treat.</p></div></div><div class="check-grid">${(known.injuries || []).map((injuryId) => `<label class="check-chip"><input type="checkbox" data-item-treatment-toggle="${escapeHtml(injuryId)}"${checked((treatment.injuryIds || []).includes(injuryId))}>${escapeHtml(injuryId)}</label>`).join("")}</div></section>` : "";
  const combatMarkup = Object.prototype.hasOwnProperty.call(effects, "combat") ? `<section class="section"><div class="section-heading"><div><h3>Combat use effect</h3><p>Common healing and consumable fields.</p></div></div><div class="form-grid"><label>Effect type<input data-item-combat-field="effectType" value="${escapeHtml(combat.effectType || "")}"></label><label>Amount<input type="number" min="0" step="any" data-item-combat-field="amount" value="${escapeHtml(combat.amount ?? "")}"></label><label>Target<input data-item-combat-field="target" value="${escapeHtml(combat.target || "")}"></label><label>Selection prompt<input data-item-combat-field="selectionPrompt" value="${escapeHtml(combat.selectionPrompt || "")}"></label><label class="wide">Description<textarea data-item-combat-field="description">${escapeHtml(combat.description || "")}</textarea></label><label class="check-chip"><input type="checkbox" data-item-combat-field="usable"${checked(combat.usable)}> Usable in combat</label></div></section>` : "";
  const sourceLabels = { encounters: "Encounter", shops: "Shop", lootTables: "Loot table", recipes: "Recipe", expeditions: "Expedition", campEvents: "Camp event", locations: "Location" };
  const references = (liveReferences().items || []).filter((reference) => reference.id === item.id);
  const referenceMarkup = renderReferenceRows(references);
  const lootTables = Object.entries(state.catalog.lootTables || {});
  const lootMarkup = lootTables.map(([tableId, table]) => {
    const entries = Array.isArray(table?.entries) ? table.entries : [];
    const itemEntries = entries.map((entry, index) => ({ entry, index })).filter(({ entry }) => entry?.type === "item" && entry.itemId === item.id);
    const rows = itemEntries.map(({ entry, index }) => `<div class="loot-row"><span>${escapeHtml(table?.id || tableId)}</span><label>Weight<input type="number" min="0" step="any" data-loot-field="weight" data-table-id="${escapeHtml(tableId)}" data-entry-index="${index}" value="${escapeHtml(entry.weight ?? "")}"></label><button type="button" class="small-button danger-outline" data-action="remove-loot-item" data-table-id="${escapeHtml(tableId)}" data-entry-index="${index}">Remove</button></div>`).join("");
    return rows || `<div class="loot-row loot-row-empty"><span>${escapeHtml(table?.id || tableId)}</span><button type="button" class="small-button" data-action="add-loot-item" data-table-id="${escapeHtml(tableId)}">Add this item</button></div>`;
  }).join("");
  const recipeEntries = Object.entries(state.catalog.recipes || {});
  const producedBy = recipeEntries.filter(([, recipe]) => recipe.output?.itemId === item.id);
  const usedAsIngredient = recipeEntries.filter(([, recipe]) => recipe.ingredientType === "item" && Object.prototype.hasOwnProperty.call(recipe.ingredients || {}, item.id));
  const recipeRelationshipRows = (entries, emptyText) => entries.length
    ? entries.map(([recipeId, recipe]) => `<div class="reference-row"><strong>Recipe</strong><span>${escapeHtml(recipe.name || recipeId)}</span><code>${escapeHtml(recipeId)}</code><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="recipes" data-reference-id="${escapeHtml(recipeId)}">Open Recipe</button></div>`).join("")
    : `<p class="hint">${escapeHtml(emptyText)}</p>`;
  return `<div class="editor-title"><div><h2>${escapeHtml(item.name || item.id || "New item")}</h2><p>${escapeHtml(item.id || "Unsaved ID")}</p></div><span class="schema-badge">Item schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Identity</h3><p>Stable IDs are referenced throughout the game content.</p></div></div><div class="form-grid">
      <label>ID<input data-field="id" value="${escapeHtml(item.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(item.name || "")}"></label>
      <label class="wide">Description<textarea data-field="description">${escapeHtml(item.description || "")}</textarea></label>
      <label>Category<select data-field="category">${selectOptions(known.itemCategories || [], item.category)}</select></label>
      <label>Rarity<select data-field="rarity"><option value="">No rarity</option>${selectOptions(known.rarities || [], item.rarity)}</select></label>
      <label class="wide">Tags<input data-array-field="tags" value="${escapeHtml((item.tags || []).join(", "))}" placeholder="martial, steel"></label>
    </div></section>
    <section class="section"><div class="section-heading"><div><h3>Inventory and flags</h3><p>Common runtime flags stay schema-aware.</p></div></div><div class="form-grid">
      <label class="check-chip"><input type="checkbox" data-field="equippable"${checked(item.equippable)}> Equippable</label><label>Equipment slot<select data-field="equipmentSlot"><option value="">Not equipped</option>${selectOptions(known.equipmentSlots || [], item.equipmentSlot)}</select></label>
      <label class="check-chip"><input type="checkbox" data-field="carriable"${checked(item.carriable)}> Carriable</label><label class="check-chip"><input type="checkbox" data-field="consumable"${checked(item.consumable)}> Consumable</label>
      <label>Maximum stack<input type="number" min="1" step="1" data-field="maxStack" value="${escapeHtml(item.maxStack ?? "")}" placeholder="optional"></label>
      <label class="check-chip"><input type="checkbox" data-field="questItem"${checked(item.questItem)}> Quest item</label><label class="check-chip"><input type="checkbox" data-field="campaignItem"${checked(item.campaignItem)}> Campaign item</label>
      <label class="check-chip"><input type="checkbox" data-field="unique"${checked(item.unique)}> Unique</label><label class="check-chip"><input type="checkbox" data-field="sellable"${checked(item.sellable)}> Sellable</label><label class="check-chip"><input type="checkbox" data-field="protected"${checked(item.protected)}> Protected</label>
    </div></section>
    <section class="section"><div class="section-heading"><div><h3>Combat effects</h3><p>Weapon damage, armor defense, and granted abilities are typed fields.</p></div></div>${damageMarkup}${defenseMarkup}<div class="section-heading" style="margin-top:14px"><div><h4>Granted abilities</h4><p>Validated against COMBAT_ABILITY_DEFINITIONS.</p></div></div><div class="check-grid ability-grid">${abilityMarkup || `<span class="hint">No combat abilities are available.</span>`}</div></section>
    ${combatMarkup}${treatmentMarkup}
    <section class="section"><div class="section-heading"><div><h3>Crafting</h3><p>Recipe relationships update from the current in-memory catalog.</p></div></div><h4>Produced By</h4><div class="reference-list">${recipeRelationshipRows(producedBy, "No recipe currently produces this item.")}</div><h4 style="margin-top:13px">Used As Ingredient In</h4><div class="reference-list">${recipeRelationshipRows(usedAsIngredient, "This item is not currently used as a recipe ingredient.")}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Loot table drops</h3><p>Focused support for adding this item to an existing table, including Bandit Leader. Other loot entry types remain read-only.</p></div></div><div class="loot-list">${lootMarkup || `<p class="hint">No loot tables are available.</p>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known live references are shown before deletion.</p></div></div><div class="reference-list">${referenceMarkup}</div></section>
    <section class="section"><details><summary>Advanced effects JSON</summary><p class="hint">Use this for uncommon effect shapes; known nested fields remain validated.</p><textarea id="effects-json" class="raw-editor">${jsonText(effects)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-effects">Apply effects JSON</button></div></details></section>
    <section class="section"><details><summary>Raw item JSON (advanced)</summary><p class="hint">Apply raw JSON to update the in-memory draft. Validation still blocks unsafe writes.</p><textarea id="raw-json" class="raw-editor">${jsonText(item)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderEnemyAction(enemyId, actionId, actionIndex) {
  const action = state.catalog.enemyActions?.[actionId] || {};
  const damage = action.damage || {};
  const injuries = state.catalog.known?.injuries || [];
  return `<div class="enemy-action-row">
    <div class="enemy-action-heading"><select data-combat-action-select="${escapeHtml(enemyId)}" data-action-index="${actionIndex}">${selectOptions(state.catalog.known?.enemyActions || [], actionId, Object.fromEntries((state.catalog.known?.enemyActions || []).map((id) => [id, state.catalog.enemyActions?.[id]?.name || id])))}</select><button type="button" class="small-button danger-outline" data-action="remove-enemy-action" data-enemy-id="${escapeHtml(enemyId)}" data-action-index="${actionIndex}">Remove</button></div>
    <div class="form-grid three">
      <label>Name<input data-enemy-action-field="name" data-action-id="${escapeHtml(actionId)}" value="${escapeHtml(action.name || "")}"></label>
      <label>Damage min<input type="number" min="0" step="any" data-enemy-action-field="damage.minimum" data-action-id="${escapeHtml(actionId)}" value="${escapeHtml(damage.minimum ?? "")}"></label>
      <label>Damage max<input type="number" min="0" step="any" data-enemy-action-field="damage.maximum" data-action-id="${escapeHtml(actionId)}" value="${escapeHtml(damage.maximum ?? "")}"></label>
      <label>Target<input data-enemy-action-field="target" data-action-id="${escapeHtml(actionId)}" value="${escapeHtml(action.target || "")}"></label>
      <label>Injury<select data-enemy-action-field="injuryId" data-action-id="${escapeHtml(actionId)}"><option value="">No injury</option>${selectOptions(injuries, action.injuryId)}</select></label>
      <label>Injury chance<input type="number" min="0" max="1" step="any" data-enemy-action-field="injuryChance" data-action-id="${escapeHtml(actionId)}" value="${escapeHtml(action.injuryChance ?? "")}"></label>
    </div>
  </div>`;
}

function renderCombat() {
  const combat = state.draft;
  if (!combat) return `<div class="empty-state">Choose a combat to edit.</div>`;
  const enemyIds = Array.isArray(combat.enemyIds) ? combat.enemyIds : [];
  const enemyMarkup = enemyIds.map((enemyId, index) => {
    const enemy = state.catalog.enemyDefinitions?.[enemyId] || {};
    const actions = Array.isArray(enemy.actionPattern) ? enemy.actionPattern : [];
    return `<details class="enemy-card" open><summary>${escapeHtml(enemy.name || enemyId || `Enemy ${index + 1}`)} <span class="panel-count">${escapeHtml(enemyId)}</span></summary>
      <div class="form-grid three">
        <label>Enemy ID<select data-combat-enemy-field="id" data-enemy-index="${index}">${selectOptions(state.catalog.known?.enemies || [], enemyId, Object.fromEntries((state.catalog.known?.enemies || []).map((id) => [id, enemyLabel(id)])))}</select></label>
        <label>Name<input data-combat-enemy-field="name" data-enemy-id="${escapeHtml(enemyId)}" value="${escapeHtml(enemy.name || "")}"></label>
        <label>Max HP<input type="number" min="1" step="1" data-combat-enemy-field="maxHp" data-enemy-id="${escapeHtml(enemyId)}" value="${escapeHtml(enemy.maxHp ?? "")}"></label>
        <label>Speed<input type="number" min="1" step="any" data-combat-enemy-field="speed" data-enemy-id="${escapeHtml(enemyId)}" value="${escapeHtml(enemy.speed ?? "")}"></label>
        <label>Defense<input type="number" min="0" step="any" data-combat-enemy-field="defense" data-enemy-id="${escapeHtml(enemyId)}" value="${escapeHtml(enemy.defense ?? "")}"></label>
      </div>
      <div class="nested-heading"><span>Special action pattern <span class="panel-count">${actions.length}</span></span><button type="button" class="small-button" data-action="add-enemy-action" data-enemy-id="${escapeHtml(enemyId)}">Add action</button></div>
      ${actions.map((actionId, actionIndex) => renderEnemyAction(enemyId, actionId, actionIndex)).join("") || `<p class="hint">No enemy actions. Add one to create an action pattern.</p>`}
      <div class="button-row"><button type="button" class="small-button" data-action="duplicate-enemy" data-enemy-index="${index}">Duplicate enemy</button><button type="button" class="small-button danger-outline" data-action="remove-enemy" data-enemy-index="${index}">Remove enemy</button></div>
    </details>`;
  }).join("");
  const references = (liveReferences().combats || []).filter((reference) => reference.id === combat.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(combat.id || "New combat")}</h2><p>${enemyIds.length} enemy occurrence${enemyIds.length === 1 ? "" : "s"}</p></div><span class="schema-badge">Combat schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Combat metadata</h3><p>Combat rosters reference reusable enemy definitions; repeated IDs remain independent occurrences in the lineup.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(combat.id || "")}"></label><label>Title / display name<input data-field="name" value="${escapeHtml(combat.name || combat.title || "")}" placeholder="optional authored field"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Enemies</h3><p>Edit HP, speed, defense, and the authored enemy action pattern. Enemy definitions are shared wherever the same enemy ID is used.</p></div><button type="button" class="small-button" data-action="add-enemy">Add enemy</button></div>${enemyMarkup || `<div class="empty-state">Add an enemy to begin authoring this combat.</div>`}</section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known encounter references to this combat.</p></div></div><div class="reference-list">${renderReferenceRows(references)}</div></section>
    <section class="section"><details><summary>Raw combat JSON (advanced)</summary><p class="hint">Use raw JSON for uncommon combat-level fields. Enemy stats and action patterns are edited in the cards above.</p><textarea id="raw-json" class="raw-editor">${jsonText(combat)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderAbility() {
  const ability = state.draft;
  if (!ability) return `<div class="empty-state">Choose an ability to edit.</div>`;
  const references = (liveReferences().abilities || []).filter((reference) => reference.id === ability.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(ability.name || ability.id || "New ability")}</h2><p>${escapeHtml(ability.id || "Unsaved ID")}</p></div><span class="schema-badge">Ability schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Ability fields</h3><p>These controls cover the current shared combat ability shapes; uncommon fields remain available in raw JSON.</p></div></div><div class="form-grid">
      <label>ID<input data-field="id" value="${escapeHtml(ability.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(ability.name || "")}"></label>
      <label class="wide">Description<textarea data-field="description">${escapeHtml(ability.description || "")}</textarea></label>
      <label>Target<select data-field="target">${selectOptions(["enemy", "ally", "self", "menu", "none"], ability.target)}</select></label>
      <label>Category<input data-field="category" value="${escapeHtml(ability.category || "")}"></label>
      <label>Selection prompt<input data-field="selectionPrompt" value="${escapeHtml(ability.selectionPrompt || "")}"></label>
      <label>Effect type<input data-field="effectType" value="${escapeHtml(ability.effectType || "")}"></label>
      <label>Damage multiplier<input type="number" min="0" step="any" data-field="damageMultiplier" value="${escapeHtml(ability.damageMultiplier ?? "")}"></label>
      <label>Gauge reduction<input type="number" min="0" step="any" data-field="gaugeReduction" value="${escapeHtml(ability.gaugeReduction ?? "")}"></label>
    </div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Items and other current definitions that grant or reference this ability.</p></div></div><div class="reference-list">${renderReferenceRows(references)}</div></section>
    <section class="section"><details><summary>Raw ability JSON (advanced)</summary><p class="hint">Apply raw JSON for schema-specific fields not exposed above.</p><textarea id="raw-json" class="raw-editor">${jsonText(ability)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function lootReferenceOptions(type, current) {
  const known = state.catalog.known || {};
  if (type === "item") {
    const ids = Object.keys(state.catalog.items || {}).sort();
    return selectOptions(ids, current, Object.fromEntries(ids.map((id) => [id, itemLabel(id)])));
  }
  if (type === "material") {
    const ids = Object.keys(state.catalog.materials || {}).sort();
    return selectOptions(ids, current, Object.fromEntries(ids.map((id) => [id, materialLabel(id)])));
  }
  if (type === "recipe") return selectOptions(known.recipes || [], current, Object.fromEntries((known.recipes || []).map((id) => [id, recipeLabel(id)])));
  if (type === "table") return selectOptions(Object.keys(state.catalog.lootTables || {}).sort(), current);
  return "";
}

function renderLootEntry(entry, index) {
  const type = entry?.type || "item";
   const quantity = ["item", "material"].includes(type) ? `<label>Quantity<input type="number" min="1" step="1" data-loot-entry-field="quantity" data-entry-index="${index}" value="${escapeHtml(entry.quantity ?? "")}" placeholder="fixed"></label><label>Minimum<input type="number" min="1" step="1" data-loot-entry-field="minimum" data-entry-index="${index}" value="${escapeHtml(entry.minimum ?? "")}"></label><label>Maximum<input type="number" min="1" step="1" data-loot-entry-field="maximum" data-entry-index="${index}" value="${escapeHtml(entry.maximum ?? "")}"></label>` : "";
  const referenceKey = type === "table" ? "tableId" : type === "material" ? "materialId" : type === "recipe" ? "recipeId" : "itemId";
  const referenceCategory = type === "recipe" ? "recipes" : type === "item" ? "items" : type === "table" ? "lootTables" : null;
  const referenceValue = entry?.[referenceKey];
  const openReference = referenceCategory && referenceValue
    ? `<button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="${referenceCategory}" data-reference-id="${escapeHtml(referenceValue)}">Open ${type === "recipe" ? "Recipe" : type === "item" ? "Item" : "Table"}</button>`
    : "";
  const referenceField = type === "gold"
    ? ""
    : `<label class="wide">${type === "table" ? "Loot table" : type === "material" ? "Material" : type === "recipe" ? "Recipe" : "Item"}<span class="reference-inline"><select data-loot-entry-field="${referenceKey}" data-entry-index="${index}"><option value="">Select ${type}...</option>${lootReferenceOptions(type, referenceValue)}</select>${openReference}</span></label>`;
  const goldFields = type === "gold" ? `<label>Minimum gold<input type="number" min="0" step="1" data-loot-entry-field="minimum" data-entry-index="${index}" value="${escapeHtml(entry.minimum ?? "")}"></label><label>Maximum gold<input type="number" min="0" step="1" data-loot-entry-field="maximum" data-entry-index="${index}" value="${escapeHtml(entry.maximum ?? "")}"></label>` : "";
  return `<div class="loot-entry-card" data-loot-entry-index="${index}"><div class="loot-entry-heading"><strong>Entry ${index + 1}</strong><select data-loot-entry-type data-entry-index="${index}">${selectOptions(["item", "material", "gold", "recipe", "table"], type)}</select><button type="button" class="small-button" data-action="duplicate-loot-entry" data-entry-index="${index}">Duplicate</button><button type="button" class="small-button danger-outline" data-action="remove-loot-entry" data-entry-index="${index}">Remove</button></div><div class="form-grid three"><label>Weight<input type="number" min="0" step="any" data-loot-entry-field="weight" data-entry-index="${index}" value="${escapeHtml(entry?.weight ?? "")}"></label>${referenceField}${goldFields}${quantity}</div></div>`;
}

function renderLootTable() {
  const table = state.draft;
  if (!table) return `<div class="empty-state">Choose a loot table to edit.</div>`;
  const entries = Array.isArray(table.entries) ? table.entries : [];
  const references = (liveReferences().lootTables || []).filter((reference) => reference.id === table.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(table.id || "New loot table")}</h2><p>${entries.length} entr${entries.length === 1 ? "y" : "ies"}</p></div><span class="schema-badge">Loot table schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Table metadata</h3><p>Weighted entries are kept in authored order. Nested table entries are reference-aware.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(table.id || "")}"></label><label>Rolls<input type="number" min="1" step="1" data-field="rolls" value="${escapeHtml(table.rolls ?? "")}" placeholder="optional"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Entries</h3><p>Edit item, material, gold, recipe, and nested loot-table entries.</p></div><button type="button" class="small-button" data-action="add-loot-entry">Add entry</button></div>${entries.map((entry, index) => renderLootEntry(entry, index)).join("") || `<div class="empty-state">This table has no entries.</div>`}</section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Encounters and other loot tables that reference this table.</p></div></div><div class="reference-list">${renderReferenceRows(references)}</div></section>
    <section class="section"><details><summary>Raw loot table JSON (advanced)</summary><p class="hint">Use raw JSON for uncommon entry shapes while keeping validation enabled.</p><textarea id="raw-json" class="raw-editor">${jsonText(table)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function currentEntries() {
  if (!state.catalog) return {};
  const entries = { ...state.catalog[state.category] };
  if (state.draft && state.category !== "paths") {
    delete entries[state.originalSelectedId];
    const draftId = state.draft.id || state.originalSelectedId;
    if (!entries[draftId] || draftId === state.originalSelectedId) entries[draftId] = state.draft;
    else entries[state.originalSelectedId] = state.draft;
  }
  return entries;
}

function renderItemFilters(entries) {
  const filters = filterState("items");
  const values = Object.values(entries);
  const categories = values.map((item) => item.category);
  const rarities = values.map((item) => item.rarity);
  const slots = values.map((item) => item.equipmentSlot);
  const tags = values.flatMap((item) => Array.isArray(item.tags) ? item.tags : []);
  return `<div class="filter-drawer">
    <div class="form-grid filter-grid">
      <label>Category<select data-filter-category="items" data-filter-field="category"><option value="">Any category</option>${filterOptions(categories, filters.category)}</select></label>
      <label>Rarity<select data-filter-category="items" data-filter-field="rarity"><option value="">Any rarity</option>${values.some((item) => !item.rarity) ? `<option value="__none__"${selected("__none__", filters.rarity)}>No rarity</option>` : ""}${filterOptions(rarities, filters.rarity === "__none__" ? "" : filters.rarity)}</select></label>
      <label>Equipment<select data-filter-category="items" data-filter-field="equippable">${triStateOptions(filters.equippable)}</select></label>
      <label>Equipment slot<select data-filter-category="items" data-filter-field="equipmentSlot"><option value="">Any slot</option>${values.some((item) => !item.equipmentSlot) ? `<option value="__none__"${selected("__none__", filters.equipmentSlot)}>No slot</option>` : ""}${filterOptions(slots, filters.equipmentSlot === "__none__" ? "" : filters.equipmentSlot)}</select></label>
      ${ITEM_FILTER_FLAGS.map((field) => `<label>${field === "questItem" ? "Quest item" : field === "campaignItem" ? "Campaign item" : field[0].toUpperCase() + field.slice(1)}<select data-filter-category="items" data-filter-field="${field}">${triStateOptions(filters[field])}</select></label>`).join("")}
      <label class="wide">Tags<select multiple size="4" data-filter-category="items" data-filter-field="tags">${multiFilterOptions(tags, filters.tags)}</select><span class="hint">Selected tags must all be present unless Match ANY is chosen.</span></label>
      <label>Tag matching<select data-filter-category="items" data-filter-field="tagMode"><option value="all"${selected("all", filters.tagMode)}>Match ALL</option><option value="any"${selected("any", filters.tagMode)}>Match ANY</option></select></label>
    </div>
  </div>`;
}

function renderEncounterFilters(entries) {
  const filters = filterState("encounters");
  const values = Object.values(entries);
  const pathIds = values.flatMap((encounter) => Array.isArray(encounter.pathIds) ? encounter.pathIds : []);
  const regionIds = values.map((encounter) => encounter.regionId);
  const tags = values.flatMap((encounter) => Array.isArray(encounter.tags) ? encounter.tags : []);
  const paths = uniqueSorted([...Object.keys(state.catalog.paths || {}), ...pathIds]);
  const pathLabels = Object.fromEntries(paths.map((pathId) => [pathId, pathLabel(pathId)]));
  return `<div class="filter-drawer">
    <div class="form-grid filter-grid">
      <label class="wide">Path<select multiple size="4" data-filter-category="encounters" data-filter-field="pathIds">${multiFilterOptions(paths, filters.pathIds, pathLabels)}</select><span class="hint">Choose one or more paths; an encounter matches any selected path.</span></label>
      <label>Region<select multiple size="3" data-filter-category="encounters" data-filter-field="regionIds">${multiFilterOptions(regionIds, filters.regionIds)}</select></label>
      <label>Direction<select data-filter-category="encounters" data-filter-field="direction"><option value="all"${selected("all", filters.direction)}>Any direction</option><option value="outbound"${selected("outbound", filters.direction)}>Outbound</option><option value="returning"${selected("returning", filters.direction)}>Returning</option><option value="both"${selected("both", filters.direction)}>Both directions</option></select></label>
      <label>Repeatable<select data-filter-category="encounters" data-filter-field="repeatable">${triStateOptions(filters.repeatable)}</select></label>
      <label>Combat<select data-filter-category="encounters" data-filter-field="combat"><option value="any"${selected("any", filters.combat)}>Any</option><option value="yes"${selected("yes", filters.combat)}>Combat</option><option value="no"${selected("no", filters.combat)}>Non-combat</option></select></label>
      <label>Has requirements<select data-filter-category="encounters" data-filter-field="hasRequirements">${triStateOptions(filters.hasRequirements)}</select></label>
      <label>Distance min<input type="number" data-filter-category="encounters" data-filter-field="minDistance" value="${escapeHtml(filters.minDistance)}" placeholder="Any"></label>
      <label>Distance max<input type="number" data-filter-category="encounters" data-filter-field="maxDistance" value="${escapeHtml(filters.maxDistance)}" placeholder="Any"></label>
      <label class="wide">Tags<select multiple size="4" data-filter-category="encounters" data-filter-field="tags">${multiFilterOptions(tags, filters.tags)}</select><span class="hint">Selected tags match all by default; switch to Match ANY if needed.</span></label>
      <label>Tag matching<select data-filter-category="encounters" data-filter-field="tagMode"><option value="all"${selected("all", filters.tagMode)}>Match ALL</option><option value="any"${selected("any", filters.tagMode)}>Match ANY</option></select></label>
    </div>
  </div>`;
}

function renderFilterControls(entries, filtered) {
  const category = state.category;
  if (!filterState(category)) return "";
  const active = activeFilterCount(category);
  const drawer = state.filterOpen ? (category === "items" ? renderItemFilters(entries) : renderEncounterFilters(entries)) : "";
  const selectionHidden = state.selectedId && !filtered.some(([id]) => activeEntryId(id));
  return `<div class="filter-toolbar"><button type="button" class="filter-toggle" data-action="toggle-filters" aria-expanded="${state.filterOpen}">Filters</button><span class="filter-status">${active} active</span><button type="button" class="filter-clear" data-action="clear-filters"${active ? "" : " disabled"}>Clear filters</button></div>${drawer}${selectionHidden ? `<div class="filter-selection-note">The selected entry is hidden by the current filters.</div>` : ""}`;
}

function renderNavigationControls() {
  if (!state.navigationHistory.length) return "";
  return `<div class="navigation-history"><button type="button" class="small-button" data-action="back-reference">Back to previous content</button></div>`;
}

function renderEntryPaneOnly() {
  if (!state.catalog || !$("#entry-list")) return;
  const entries = currentEntries();
  const filtered = filterEntries(state.category, entries).sort((a, b) => String(a[1].title || a[1].displayName || a[1].name || a[0]).localeCompare(String(b[1].title || b[1].displayName || b[1].name || b[0])));
  $("#entry-heading").textContent = CONTENT_CATEGORIES.find(([id]) => id === state.category)?.[1] || "Content";
  $("#entry-count").textContent = `${filtered.length} / ${Object.keys(entries).length}`;
  $("#entry-search").value = currentSearch();
  const filterRoot = $("#filter-controls");
  if (filterRoot) filterRoot.innerHTML = renderFilterControls(entries, filtered);
  $("#entry-list").innerHTML = filtered.length ? filtered.map(([id, entry]) => `<button type="button" role="option" aria-selected="${activeEntryId(id)}" class="entry-row ${activeEntryId(id) ? "active" : ""}" data-action="select" data-id="${escapeHtml(id)}"><span class="entry-title">${escapeHtml(entry.title || entry.displayName || entry.name || id)}</span><span class="entry-id">${escapeHtml(id)}${state.category === "paths" ? ` &middot; ${escapeHtml(entry.encounterCount || 0)} encounters` : ""}</span></button>`).join("") : `<div class="empty-state">No matching entries.</div>`;
}

function render() {
  if (!state.catalog) return;
  refreshDerivedPaths();
  $("#project-path").textContent = `Project: ${state.catalog.projectRoot}`;
  $("#category-nav").innerHTML = CONTENT_CATEGORIES.map(([id, label]) => `<button type="button" class="${state.category === id ? "active" : ""}" data-action="category" data-category="${id}">${label}<span class="category-count">${Object.keys(state.catalog[id] || {}).length}</span></button>`).join("");
  const entries = currentEntries();
  const filterVisibleEntries = Object.fromEntries(filterEntries(state.category, entries));
  const query = currentSearch().trim().toLowerCase();
  const filtered = Object.entries(filterVisibleEntries).filter(([id, entry]) => {
    const recipeSearch = state.category === "recipes"
      ? ` ${(entry.ingredients ? Object.keys(entry.ingredients).map((ingredientId) => state.catalog.items?.[ingredientId] ? itemLabel(ingredientId) : materialLabel(ingredientId)).join(" ") : "")} ${entry.output?.itemId ? itemLabel(entry.output.itemId) : "provisions"}`
      : "";
    return !query || `${id} ${entry.title || entry.displayName || entry.name || ""} ${entry.category || ""} ${entry.rarity || ""}${recipeSearch}`.toLowerCase().includes(query);
  }).sort((a, b) => String(a[1].title || a[1].displayName || a[1].name || a[0]).localeCompare(String(b[1].title || b[1].displayName || b[1].name || b[0])));
  $("#entry-heading").textContent = CONTENT_CATEGORIES.find(([id]) => id === state.category)?.[1] || "Content";
  $("#entry-count").textContent = `${filtered.length} / ${Object.keys(entries).length}`;
  $("#entry-search").value = currentSearch();
  const filterRoot = $("#filter-controls");
  if (filterRoot) filterRoot.innerHTML = renderFilterControls(entries, filtered);
  $("#entry-list").innerHTML = filtered.length ? filtered.map(([id, entry]) => {
    const recipeOutput = state.category === "recipes" ? ` · Produces: ${entry.output?.itemId ? itemLabel(entry.output.itemId) : `${entry.output?.provisions ?? 0} provisions`}` : "";
    return `<button type="button" role="option" aria-selected="${id === state.selectedId || (state.draft?.id === id && state.originalSelectedId === state.selectedId)}" class="entry-row ${(id === state.selectedId || (state.draft?.id === id && state.originalSelectedId === state.selectedId)) ? "active" : ""}" data-action="select" data-id="${escapeHtml(id)}"><span class="entry-title">${escapeHtml(entry.title || entry.displayName || entry.name || id)}</span><span class="entry-id">${escapeHtml(id)}${state.category === "paths" ? ` · ${escapeHtml(entry.encounterCount || 0)} encounters` : recipeOutput}</span></button>`;
  }).join("") : `<div class="empty-state">No matching entries.</div>`;
  const readonlyPaths = state.category === "paths";
  $("[data-action='add']").disabled = readonlyPaths;
  $("[data-action='duplicate']").disabled = readonlyPaths;
  $("[data-action='delete']").disabled = readonlyPaths;
  $("#editor-root").innerHTML = state.category === "encounters"
    ? renderEncounter()
    : state.category === "injuries"
      ? renderInjury()
      : state.category === "campEvents"
        ? renderCampEvent()
    : state.category === "paths"
      ? renderPath()
      : state.category === "expeditions"
      ? renderExpedition()
      : state.category === "recipes"
        ? renderRecipe()
        : state.category === "materials"
          ? renderMaterial()
        : state.category === "craftingProviders"
          ? renderCraftingProvider()
        : state.category === "shops"
      ? renderShop()
      : state.category === "items"
        ? renderItem()
        : state.category === "combats"
          ? renderCombat()
          : state.category === "abilities"
             ? renderAbility()
             : renderLootTable();
   if (state.navigationHistory.length) $("#editor-root").insertAdjacentHTML("afterbegin", renderNavigationControls());
   updateSaveState();
  renderValidation();
  populateItemDatalist();
}

function populateItemDatalist() {
  const datalist = $("#item-options");
  const lootTableDatalist = $("#loot-table-options");
  if (!state.catalog) return;
  if (datalist) datalist.innerHTML = Object.keys(state.catalog.items || {}).sort().map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(itemLabel(id))}</option>`).join("");
  if (lootTableDatalist) lootTableDatalist.innerHTML = Object.keys(state.catalog.lootTables || {}).sort().map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join("");
}

function updateSaveState() {
  const indicator = $("#dirty-indicator");
  if (!indicator) return;
  indicator.className = `save-state ${state.dirty ? "dirty" : "saved"}`;
  indicator.textContent = state.dirty ? "Unsaved changes" : "All changes saved";
}

function renderValidationLegacy() {
  const panel = $("#validation-panel");
  if (!panel) return;
  if (state.validationPending) {
    panel.innerHTML = `<div class="validation-header"><h2>Validation</h2><span>Checking current draft…</span></div>`;
    return;
  }
  const errors = state.validation?.errors || [];
  const warnings = state.validation?.warnings || [];
  const issues = [...errors, ...warnings];
  panel.innerHTML = `<div class="validation-header"><h2>Validation</h2><span>${errors.length} error${errors.length === 1 ? "" : "s"}, ${warnings.length} warning${warnings.length === 1 ? "" : "s"}</span></div>${issues.length ? `<ul class="issue-list">${issues.slice(0, 120).map((issue) => `<li class="${issue.severity === "warning" ? "warning" : ""}"><strong>${escapeHtml(issue.source || "content")}</strong>${issue.path ? ` · ${escapeHtml(issue.path)}` : ""}: ${escapeHtml(issue.message)}</li>`).join("")}</ul>` : `<p class="validation-ok">No validation errors found in the loaded Phase 1 content.</p>`}`;
}

function renderValidation() {
  const panel = $("#validation-panel");
  if (!panel) return;
  if (state.validationPending) {
    panel.innerHTML = `<div class="validation-header"><h2>Validation</h2><span>Checking current draft...</span></div>`;
    return;
  }
  const errors = state.validation?.errors || [];
  const warnings = state.validation?.warnings || [];
  const issues = [...errors, ...warnings];
   panel.innerHTML = `<div class="validation-header"><h2>Validation</h2><span>${errors.length} error${errors.length === 1 ? "" : "s"}, ${warnings.length} warning${warnings.length === 1 ? "" : "s"}</span></div>${issues.length ? `<ul class="issue-list">${issues.slice(0, 120).map((issue) => `<li class="${issue.severity === "warning" ? "warning" : ""}"><strong>${escapeHtml(issue.source || "content")}</strong>${issue.path ? ` - ${escapeHtml(issue.path)}` : ""}: ${escapeHtml(issue.message)}</li>`).join("")}</ul>` : `<p class="validation-ok">No validation errors found in the loaded Phase 3 content.</p>`}`;
}

function draftSnapshot() {
  const snapshot = {
    encounters: clone(state.catalog.encounters),
    injuries: clone(state.catalog.injuries),
    campEvents: clone(state.catalog.campEvents),
    expeditions: clone(state.catalog.expeditions),
    recipes: clone(state.catalog.recipes),
    materials: clone(state.catalog.materials),
    craftingProviders: clone(state.catalog.craftingProviders),
    shops: clone(state.catalog.shops),
    items: clone(state.catalog.items),
    combats: clone(state.catalog.combats),
    abilities: clone(state.catalog.abilities),
    enemyDefinitions: clone(state.catalog.enemyDefinitions),
    enemyActions: clone(state.catalog.enemyActions),
    lootTables: clone(state.catalog.lootTables),
  };
  if (state.draft && state.category !== "paths") {
    const map = snapshot[state.category];
    const draftId = state.draft.id || state.originalSelectedId;
    if (draftId === state.originalSelectedId || !Object.prototype.hasOwnProperty.call(map, draftId)) {
      delete map[state.originalSelectedId];
      map[draftId] = clone(state.draft);
    } else {
      // Preserve the collision so the server reports the key/id mismatch
      // instead of silently overwriting an existing authored definition.
      map[state.originalSelectedId] = clone(state.draft);
    }
  }
  return snapshot;
}

function markDirty() {
  state.dirty = true;
  state.draftDirty = true;
  updateSaveState();
  renderEntryPaneOnly();
  scheduleValidation();
}

function scheduleValidation() {
  state.validationPending = true;
  renderValidation();
  clearTimeout(state.validationTimer);
  state.validationTimer = setTimeout(requestValidation, 350);
}

async function requestValidation() {
  if (!state.catalog) return;
  try {
    const response = await fetch("/api/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draftSnapshot()) });
    state.validation = await response.json();
  } catch (error) {
    state.validation = { errors: [{ severity: "error", source: "editor", message: `Validation request failed: ${error.message}` }], warnings: [] };
  }
  state.validationPending = false;
  renderValidation();
}

function commitDraftToCatalog() {
  if (!state.draft || !state.catalog || state.category === "paths") return;
  const map = state.catalog[state.category];
  const draftId = state.draft.id || state.originalSelectedId;
  delete map[state.originalSelectedId];
  map[draftId] = clone(state.draft);
  state.selectedId = draftId;
  state.originalSelectedId = draftId;
  state.draft = clone(map[draftId]);
}

function selectEntry(id, discard = false) {
  if (!state.catalog) return;
  if (state.draftDirty && state.category !== "paths" && !discard && !window.confirm("Discard unsaved changes?")) return;
  const entry = state.catalog[state.category]?.[id];
  if (!entry) return;
  state.selectedId = id;
  state.originalSelectedId = id;
  state.draft = clone(entry);
  state.draftDirty = false;
  state.validation = state.catalog.validation;
  render();
}

function defaultEntry(category) {
  if (category === "injuries") return {
    id: "new_injury",
    name: "New Injury",
    shortName: "New Injury",
    description: "",
    effects: {},
    recoveryDistanceRange: { minimum: 0, maximum: 0 },
    treatmentItemId: null,
  };
  if (category === "campEvents") return {
    id: "new_camp_event",
    title: "New Camp Event",
    description: "",
    regionId: state.catalog.known.regions?.[0] || "",
    pathIds: [],
    tags: [],
    requirements: [],
    stages: { start: { text: "", choices: [] } },
  };
  if (category === "shops") return { id: "new_shop", displayName: "New Shop", itemsForSale: {}, acceptedCategories: [], acceptedTags: [], sellValues: {} };
  if (category === "items") return {
    id: "new_weapon",
    name: "New Weapon",
    description: "",
    category: "weapon",
    rarity: "common",
    tags: [],
    equippable: true,
    equipmentSlot: "weapon",
    carriable: false,
    consumable: false,
    effects: { combatDamage: { minimum: 1, maximum: 2 }, grantedAbilityIds: [] },
    questItem: false,
    unique: false,
  };
  if (category === "combats") return { id: "new_combat", enemyIds: [] };
  if (category === "abilities") return { id: "new_ability", name: "New Ability", description: "", target: "enemy" };
  if (category === "lootTables") return { id: "new_loot_table", entries: [] };
  if (category === "materials") return {
    id: "new_material",
    name: "New Material",
    description: "",
    rarity: "common",
  };
  if (category === "expeditions") return {
    id: "new_expedition",
    name: "New Expedition",
    description: "",
    danger: 1,
    regionId: state.catalog.known.regions?.[0] || "",
    pathId: state.catalog.known.paths?.[0] || "",
    kind: "normal",
    campEventTableIds: [],
    prerequisites: [],
  };
  if (category === "craftingProviders") return { id: "new_provider", name: "New Crafting Provider" };
  if (category === "recipes") return {
    id: "new_recipe",
    name: "New Recipe",
    description: "",
    craftingProvider: Object.keys(state.catalog.craftingProviders || {})[0] || "",
    ingredients: { [Object.keys(state.catalog.materials || {}).sort()[0] || ""]: 1 },
    output: { itemId: Object.keys(state.catalog.items || {})[0] || "", quantity: 1 },
    goldCost: 0,
    rarity: "common",
  };
  return {
    id: "new_encounter",
    title: "New Encounter",
    description: "",
    regionId: state.catalog.known.regions?.[0] || "",
    pathIds: state.catalog.known.paths?.slice(0, 1) || [],
    directions: ["outbound"],
    weight: 1,
    minimumDistance: 0,
    tags: [],
    repeatable: false,
    requirements: [],
    stages: { start: { text: "", choices: [] } },
  };
}

function uniqueId(base, map) {
  let id = base;
  let suffix = 2;
  while (Object.prototype.hasOwnProperty.call(map, id)) id = `${base}_${suffix++}`;
  return id;
}

function addEntry() {
  if (state.category === "paths") return;
  commitDraftToCatalog();
  const map = state.catalog[state.category];
  const entry = defaultEntry(state.category);
  entry.id = uniqueId(entry.id, map);
  map[entry.id] = entry;
  state.selectedId = entry.id;
  state.originalSelectedId = entry.id;
  state.draft = clone(entry);
  markDirty();
  render();
}

function duplicateEntry() {
  if (!state.draft || state.category === "paths") return;
  commitDraftToCatalog();
  const map = state.catalog[state.category];
  const entry = clone(state.draft);
  entry.id = uniqueId(`${entry.id || "entry"}_copy`, map);
  if (["encounters", "campEvents"].includes(state.category)) entry.title = `${entry.title || "Event"} Copy`;
  else if (state.category === "injuries") entry.name = `${entry.name || "Injury"} Copy`;
  else if (state.category === "shops") entry.displayName = `${entry.displayName || "Shop"} Copy`;
  else if (["items", "abilities"].includes(state.category)) entry.name = `${entry.name || "Entry"} Copy`;
  else if (["expeditions", "recipes", "materials", "craftingProviders"].includes(state.category)) entry.name = `${entry.name || "Entry"} Copy`;
  map[entry.id] = entry;
  state.selectedId = entry.id;
  state.originalSelectedId = entry.id;
  state.draft = clone(entry);
  markDirty();
  render();
}

function deleteEntry() {
  if (!state.draft || !state.catalog || state.category === "paths") return;
  const id = state.draft.id || state.originalSelectedId;
  const refType = state.category === "shops" ? "shops" : state.category === "items" ? "items" : state.category === "combats" ? "combats" : state.category === "abilities" ? "abilities" : state.category === "injuries" ? "injuries" : state.category === "campEvents" ? "campEvents" : state.category === "lootTables" ? "lootTables" : state.category === "expeditions" ? "expeditions" : state.category === "recipes" ? "recipes" : state.category === "materials" ? "materials" : state.category === "craftingProviders" ? "craftingProviders" : "encounters";
  const refs = (liveReferences()[refType] || []).filter((reference) => reference.id === id);
  const warning = refs.length ? `\n\nReferences found:\n${refs.map((reference) => `- ${reference.source} (${reference.path})`).join("\n")}\n\nSaving this deletion will be blocked until those references are resolved.` : "";
  if (!window.confirm(`Delete ${id}? This is an in-memory deletion until you explicitly save.${warning}`)) return;
  commitDraftToCatalog();
  delete state.catalog[state.category][id];
  const nextId = Object.keys(state.catalog[state.category])[0] || null;
  state.selectedId = nextId;
  state.originalSelectedId = nextId;
  state.draft = nextId ? clone(state.catalog[state.category][nextId]) : null;
  markDirty();
  render();
}

function getChoice(stageId, index) {
  if (index === "-1" || index === -1) return state.draft?.stages?.[stageId];
  return state.draft?.stages?.[stageId]?.choices?.[Number(index)];
}

function getObjectRow(row) {
  if (row.dataset.parentPath !== undefined) {
    const parent = pathValue(state.draft, row.dataset.parentPath);
    const collectionName = row.dataset.collectionName;
    parent[collectionName] ||= [];
    return { collection: parent[collectionName], index: Number(row.dataset.objectIndex) };
  }
  const owner = row.dataset.owner;
  const stage = row.dataset.stage;
  const choice = row.dataset.choiceIndex;
  const parent = owner === "encounter-requirements" ? state.draft : getChoice(stage, choice);
  const collectionName = owner === "stage-outcomes" ? "outcomes" : owner === "encounter-requirements" ? "requirements" : owner;
  parent[collectionName] ||= [];
  return { collection: parent[collectionName], index: Number(row.dataset.objectIndex) };
}

function parseInputValue(input, field) {
  if (input.type === "checkbox") return input.checked;
  if (input.type === "number") return input.value === "" ? undefined : Number(input.value);
  return input.value;
}

function setNested(object, path, value) {
  const parts = path.split(".");
  let target = object;
  for (let index = 0; index < parts.length - 1; index += 1) {
    target[parts[index]] ||= {};
    target = target[parts[index]];
  }
  const key = parts.at(-1);
  if (value === undefined || value === "") delete target[key];
  else target[key] = value;
}

function toggleArray(array, value, on) {
  const result = Array.isArray(array) ? [...array] : [];
  const index = result.indexOf(value);
  if (on && index < 0) result.push(value);
  if (!on && index >= 0) result.splice(index, 1);
  return result;
}

function splitList(value) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function handleInput(input) {
  if (input.dataset.pathFilter) {
    state.pathFilters[input.dataset.pathFilter] = input.value;
    render();
    return;
  }
  if (input.dataset.filterCategory) {
    const filters = filterState(input.dataset.filterCategory);
    if (!filters) return;
    const filterCategory = input.dataset.filterCategory;
    const filterField = input.dataset.filterField;
    const selectionStart = input.selectionStart;
    const selectionEnd = input.selectionEnd;
    filters[input.dataset.filterField] = input.multiple ? selectedFilterValues(input) : input.value;
    renderEntryPaneOnly();
    const nextInput = document.querySelector(`[data-filter-category="${filterCategory}"][data-filter-field="${filterField}"]`);
    if (nextInput) {
      nextInput.focus();
      if (selectionStart !== null && selectionStart !== undefined && !nextInput.multiple) nextInput.setSelectionRange(selectionStart, selectionEnd);
    }
    return;
  }
  if (!state.draft) return;
  if (input.dataset.resolutionField) {
    const target = pathValue(state.draft, input.dataset.resolutionPath);
    if (!target) return;
    const value = parseInputValue(input, input.dataset.resolutionField);
    if (value === undefined || value === "") delete target[input.dataset.resolutionField];
    else target[input.dataset.resolutionField] = value;
    markDirty();
    return;
  }
  if (input.dataset.resolutionItemField) {
    const target = pathValue(state.draft, input.dataset.resolutionItemPath);
    if (input.dataset.resolutionItemField === "itemIds") {
      if (!target?.itemIds) return;
      target.itemIds[Number(input.dataset.resolutionItemIndex)] = input.value;
    } else if (target) {
      const value = parseInputValue(input, input.dataset.resolutionItemField);
      if (value === undefined || value === "") delete target[input.dataset.resolutionItemField];
      else target[input.dataset.resolutionItemField] = value;
    }
    markDirty();
    return;
  }
  if (input.hasAttribute("data-loot-entry-type")) {
    const index = Number(input.dataset.entryIndex);
    const type = input.value;
    const first = {
      item: { type, itemId: state.catalog.known?.items?.[0] || "", weight: 1 },
      material: { type, materialId: Object.keys(state.catalog.materials || {}).sort()[0] || "", weight: 1, quantity: 1 },
      gold: { type, minimum: 1, maximum: 1, weight: 1 },
      recipe: { type, recipeId: state.catalog.known?.recipes?.[0] || "", weight: 1 },
      table: { type, tableId: state.catalog.known?.lootTables?.[0] || "", weight: 1 },
    }[type];
    if (first) {
      state.draft.entries[index] = first;
      markDirty();
      render();
    }
    return;
  }
  if (input.dataset.recipeIngredientField) {
    const entries = Object.entries(state.draft.ingredients || {});
    const index = Number(input.dataset.ingredientIndex);
    const current = entries[index];
    if (!current) return;
    if (input.dataset.recipeIngredientField === "id") {
      const newId = input.value;
      if (!newId || (newId !== current[0] && Object.prototype.hasOwnProperty.call(state.draft.ingredients, newId))) {
        render();
        return;
      }
      const next = {};
      entries.forEach(([id, quantity], entryIndex) => { next[entryIndex === index ? newId : id] = quantity; });
      state.draft.ingredients = next;
    } else {
      const quantity = input.value === "" ? undefined : Number(input.value);
      if (quantity === undefined) delete state.draft.ingredients[current[0]];
      else state.draft.ingredients[current[0]] = quantity;
    }
    markDirty();
    render();
    return;
  }
  if (input.hasAttribute("data-recipe-output-type")) {
    state.draft.output = input.value === "item"
      ? { itemId: Object.keys(state.catalog.items || {})[0] || "", quantity: 1 }
      : { provisions: 1 };
    markDirty();
    render();
    return;
  }
  if (input.dataset.recipeOutputField) {
    state.draft.output ||= {};
    const value = input.value === "" ? undefined : input.dataset.recipeOutputField === "itemId" ? input.value : Number(input.value);
    if (value === undefined) delete state.draft.output[input.dataset.recipeOutputField];
    else state.draft.output[input.dataset.recipeOutputField] = value;
    markDirty();
    return;
  }
  if (input.dataset.lootEntryField) {
    const entry = state.draft.entries?.[Number(input.dataset.entryIndex)];
    if (!entry) return;
    const value = parseInputValue(input, input.dataset.lootEntryField);
    if (value === undefined || value === "") delete entry[input.dataset.lootEntryField];
    else entry[input.dataset.lootEntryField] = value;
    markDirty();
    return;
  }
  if (input.dataset.combatEnemyField) {
    const index = Number(input.dataset.enemyIndex);
    if (input.dataset.combatEnemyField === "id") {
      state.draft.enemyIds[index] = input.value;
      markDirty();
      render();
      return;
    }
    const enemy = state.catalog.enemyDefinitions?.[input.dataset.enemyId];
    if (!enemy) return;
    const value = parseInputValue(input, input.dataset.combatEnemyField);
    if (value === undefined || value === "") delete enemy[input.dataset.combatEnemyField];
    else enemy[input.dataset.combatEnemyField] = value;
    markDirty();
    return;
  }
  if (input.dataset.combatActionSelect) {
    const enemy = state.catalog.enemyDefinitions?.[input.dataset.combatActionSelect];
    if (!enemy) return;
    enemy.actionPattern ||= [];
    enemy.actionPattern[Number(input.dataset.actionIndex)] = input.value;
    markDirty();
    render();
    return;
  }
  if (input.dataset.enemyActionField) {
    const action = state.catalog.enemyActions?.[input.dataset.actionId];
    if (!action) return;
    const value = parseInputValue(input, input.dataset.enemyActionField);
    setNested(action, input.dataset.enemyActionField, value);
    markDirty();
    return;
  }
  if (input.dataset.lootField) {
    const table = state.catalog.lootTables?.[input.dataset.tableId];
    const entry = table?.entries?.[Number(input.dataset.entryIndex)];
    if (!entry) return;
    entry[input.dataset.lootField] = input.value === "" ? undefined : Number(input.value);
    if (entry[input.dataset.lootField] === undefined) delete entry[input.dataset.lootField];
    markDirty();
    return;
  }
  if (input.dataset.itemEffectField) {
    state.draft.effects ||= {};
    setNested(state.draft.effects, input.dataset.itemEffectField, parseInputValue(input, input.dataset.itemEffectField));
    markDirty();
    return;
  }
  if (input.dataset.itemAbilityToggle) {
    state.draft.effects ||= {};
    state.draft.effects.grantedAbilityIds = toggleArray(state.draft.effects.grantedAbilityIds, input.dataset.itemAbilityToggle, input.checked);
    markDirty();
    return;
  }
  if (input.dataset.itemTreatmentToggle) {
    state.draft.effects ||= {};
    state.draft.effects.treatment ||= {};
    state.draft.effects.treatment.injuryIds = toggleArray(state.draft.effects.treatment.injuryIds, input.dataset.itemTreatmentToggle, input.checked);
    markDirty();
    return;
  }
  if (input.dataset.itemCombatField) {
    state.draft.effects ||= {};
    state.draft.effects.combat ||= {};
    setNested(state.draft.effects.combat, input.dataset.itemCombatField, parseInputValue(input, input.dataset.itemCombatField));
    markDirty();
    return;
  }
  if (input.dataset.injuryEffectField) {
    state.draft.effects ||= {};
    setNested(state.draft.effects, input.dataset.injuryEffectField, parseInputValue(input, input.dataset.injuryEffectField));
    markDirty();
    return;
  }
  if (input.dataset.injuryField) {
    setNested(state.draft, input.dataset.injuryField, parseInputValue(input, input.dataset.injuryField));
    markDirty();
    return;
  }
  if (input.dataset.field) {
    const value = parseInputValue(input, input.dataset.field);
    setNested(state.draft, input.dataset.field, value);
    markDirty();
    if (["category", "ingredientType"].includes(input.dataset.field)) render();
    return;
  }
  if (input.dataset.arrayField) {
    state.draft[input.dataset.arrayField] = splitList(input.value);
    markDirty();
    return;
  }
  if (input.dataset.arrayToggle) {
    state.draft[input.dataset.arrayToggle] = toggleArray(state.draft[input.dataset.arrayToggle], input.dataset.arrayValue, input.checked);
    markDirty();
    return;
  }
  if (input.dataset.stageField) {
    const stage = state.draft.stages[input.dataset.stage];
    setNested(stage, input.dataset.stageField, input.value);
    markDirty();
    return;
  }
  if (input.dataset.choiceField) {
    const choice = getChoice(input.dataset.stage, input.dataset.choiceIndex);
    setNested(choice, input.dataset.choiceField, parseInputValue(input, input.dataset.choiceField));
    markDirty();
    return;
  }
  if (input.dataset.objectField && input.closest("[data-object-row]")) {
    const { collection, index } = getObjectRow(input.closest("[data-object-row]"));
    if (!collection[index]) return;
    const value = parseInputValue(input, input.dataset.objectField);
    if (value === undefined || value === "") delete collection[index][input.dataset.objectField];
    else collection[index][input.dataset.objectField] = value;
    markDirty();
    if (input.dataset.objectField === "type") render();
    return;
  }
  if (input.dataset.shopItemField && input.closest("[data-shop-row]")) {
    const row = input.closest("[data-shop-row]");
    const oldId = row.dataset.itemId;
    const listing = state.draft.itemsForSale[oldId] ||= {};
    if (input.dataset.shopItemField === "itemId") {
      const newId = input.value.trim();
      if (newId && newId !== oldId) {
        if (state.draft.itemsForSale[newId]) { input.value = oldId; return; }
        state.draft.itemsForSale[newId] = listing;
        delete state.draft.itemsForSale[oldId];
        markDirty();
        render();
      }
    } else if (input.dataset.shopItemField === "price") {
      listing.price = input.value === "" ? undefined : Number(input.value);
      if (listing.price === undefined) delete listing.price;
      markDirty();
    } else if (input.dataset.shopItemField === "unlimited") {
      if (input.checked) delete listing.stock;
      else listing.stock = 1;
      markDirty();
      render();
    } else if (input.dataset.shopItemField === "stock") {
      listing.stock = input.value === "" ? undefined : Number(input.value);
      if (listing.stock === undefined) delete listing.stock;
      markDirty();
    }
    return;
  }
  if (input.dataset.sellItemField && input.closest("[data-sell-row]")) {
    const row = input.closest("[data-sell-row]");
    const oldId = row.dataset.itemId;
    const value = state.draft.sellValues[oldId];
    if (input.dataset.sellItemField === "itemId") {
      const newId = input.value.trim();
      if (newId && newId !== oldId) {
        if (Object.prototype.hasOwnProperty.call(state.draft.sellValues, newId)) { input.value = oldId; return; }
        state.draft.sellValues[newId] = value;
        delete state.draft.sellValues[oldId];
        markDirty();
        render();
      }
    } else {
      state.draft.sellValues[oldId] = input.value === "" ? undefined : Number(input.value);
      if (state.draft.sellValues[oldId] === undefined) delete state.draft.sellValues[oldId];
      markDirty();
    }
  }
}

function handleObjectJson(textarea) {
  try {
    const row = textarea.closest("[data-object-row]");
    const { collection, index } = getObjectRow(row);
    const parsed = JSON.parse(textarea.value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Object JSON must be an object");
    collection[index] = parsed;
    markDirty();
    render();
  } catch (error) {
    window.alert(`Could not apply object JSON: ${error.message}`);
  }
}

function switchCategory(category, id = null) {
  if (!state.catalog?.[category]) return;
  if (state.dirty) commitDraftToCatalog();
  state.searchByCategory[state.category] = state.search;
  state.draftDirty = false;
  state.category = category;
  state.search = state.searchByCategory[category] || "";
  const nextId = id && state.catalog[category][id] ? id : Object.keys(state.catalog[category])[0] || null;
  state.selectedId = nextId;
  state.originalSelectedId = nextId;
  state.draft = nextId ? clone(state.catalog[category][nextId]) : null;
  state.validation = state.catalog.validation;
  render();
}

function handleAction(button) {
  const action = button.dataset.action;
  if (action === "toggle-filters") {
    state.filterOpen = !state.filterOpen;
    renderEntryPaneOnly();
  } else if (action === "clear-filters") {
    if (state.filters[state.category]) {
      state.filters[state.category] = state.category === "items"
        ? { category: "", rarity: "", equippable: "any", equipmentSlot: "", carriable: "any", consumable: "any", questItem: "any", campaignItem: "any", unique: "any", sellable: "any", protected: "any", tags: [], tagMode: "all" }
        : { pathIds: [], regionIds: [], direction: "all", minDistance: "", maxDistance: "", repeatable: "any", tags: [], tagMode: "all", combat: "any", hasRequirements: "any" };
      renderEntryPaneOnly();
    }
  } else if (action === "category") {
    switchCategory(button.dataset.category);
  } else if (action === "open-reference") {
    state.navigationHistory.push({ category: state.category, id: state.draft?.id || state.selectedId });
    switchCategory(button.dataset.referenceCategory, button.dataset.referenceId);
  } else if (action === "back-reference") {
    const previous = state.navigationHistory.pop();
    if (previous) switchCategory(previous.category, previous.id);
  } else if (action === "select") {
    selectEntry(button.dataset.id);
  } else if (action === "add-encounter-to-path") {
    const encounterId = $("#path-add-encounter")?.value;
    const encounter = state.catalog.encounters?.[encounterId];
    const pathId = button.dataset.pathId;
    if (!encounter || !pathId) return;
    encounter.pathIds = toggleArray(encounter.pathIds, pathId, true);
    markDirty();
    render();
  } else if (action === "add-recipe-ingredient") {
    const recipe = state.draft;
    const ingredientType = recipe.ingredientType || "material";
    const candidates = ingredientType === "item" ? Object.keys(state.catalog.items || {}).sort() : Object.keys(state.catalog.materials || {}).sort();
    const ingredientId = candidates.find((id) => !Object.prototype.hasOwnProperty.call(recipe.ingredients || {}, id));
    if (!ingredientId) return window.alert("No unused ingredient references are available.");
    recipe.ingredients ||= {};
    recipe.ingredients[ingredientId] = 1;
    markDirty();
    render();
  } else if (action === "duplicate-recipe-ingredient") {
    const recipe = state.draft;
    const entries = Object.entries(recipe.ingredients || {});
    const source = entries[Number(button.dataset.ingredientIndex)];
    if (!source) return;
    const candidates = (recipe.ingredientType || "material") === "item" ? Object.keys(state.catalog.items || {}).sort() : Object.keys(state.catalog.materials || {}).sort();
    const ingredientId = candidates.find((id) => !Object.prototype.hasOwnProperty.call(recipe.ingredients || {}, id));
    if (!ingredientId) return window.alert("No unused ingredient references are available.");
    recipe.ingredients[ingredientId] = source[1];
    markDirty();
    render();
  } else if (action === "remove-recipe-ingredient") {
    const entries = Object.entries(state.draft.ingredients || {});
    const source = entries[Number(button.dataset.ingredientIndex)];
    if (!source) return;
    delete state.draft.ingredients[source[0]];
    markDirty();
    render();
  } else if (action === "remove-encounter-from-path") {
    const encounter = state.catalog.encounters?.[button.dataset.encounterId];
    const pathId = button.dataset.pathId;
    if (!encounter || !pathId) return;
    encounter.pathIds = toggleArray(encounter.pathIds, pathId, false);
    markDirty();
    render();
  } else if (action === "add") addEntry();
  else if (action === "duplicate") duplicateEntry();
  else if (action === "delete") deleteEntry();
  else if (action === "reload") {
    if (!state.dirty || window.confirm("Discard unsaved changes and reload from disk?")) loadCatalog();
  } else if (action === "save") saveChanges();
  else if (action === "add-enemy") {
    const enemyId = state.catalog.known?.enemies?.[0];
    if (!enemyId) return window.alert("No enemy definitions are available.");
    state.draft.enemyIds ||= [];
    state.draft.enemyIds.push(enemyId);
    markDirty();
    render();
  } else if (action === "duplicate-enemy") {
    const index = Number(button.dataset.enemyIndex);
      if (!state.draft.enemyIds?.[index]) return;
    state.draft.enemyIds.splice(index + 1, 0, state.draft.enemyIds[index]);
    markDirty();
    render();
  } else if (action === "remove-enemy") {
    state.draft.enemyIds.splice(Number(button.dataset.enemyIndex), 1);
    markDirty();
    render();
  } else if (action === "add-enemy-action") {
    const enemy = state.catalog.enemyDefinitions?.[button.dataset.enemyId];
    const actionId = state.catalog.known?.enemyActions?.[0];
    if (!enemy || !actionId) return window.alert("No enemy actions are available.");
    enemy.actionPattern ||= [];
    enemy.actionPattern.push(actionId);
    markDirty();
    render();
  } else if (action === "remove-enemy-action") {
    const enemy = state.catalog.enemyDefinitions?.[button.dataset.enemyId];
    if (!enemy?.actionPattern) return;
    enemy.actionPattern.splice(Number(button.dataset.actionIndex), 1);
    markDirty();
    render();
  } else if (action === "add-loot-entry") {
    state.draft.entries ||= [];
    state.draft.entries.push({ type: "item", itemId: state.catalog.known?.items?.[0] || "", weight: 1 });
    markDirty();
    render();
  } else if (action === "duplicate-loot-entry") {
    const index = Number(button.dataset.entryIndex);
    const entry = state.draft.entries?.[index];
    if (!entry) return;
    state.draft.entries.splice(index + 1, 0, clone(entry));
    markDirty();
    render();
  } else if (action === "remove-loot-entry") {
    state.draft.entries.splice(Number(button.dataset.entryIndex), 1);
    markDirty();
    render();
  }
  else if (action === "add-stage") {
    const base = uniqueId("new_stage", state.draft.stages || {});
    state.draft.stages ||= {};
    state.draft.stages[base] = { text: "", choices: [] };
    markDirty();
    render();
  } else if (action === "remove-stage") {
    if (Object.keys(state.draft.stages || {}).length <= 1) return window.alert("An encounter needs at least one stage.");
    delete state.draft.stages[button.dataset.stage];
    markDirty();
    render();
  } else if (action === "add-choice") {
    const stage = state.draft.stages[button.dataset.stage];
    stage.choices ||= [];
    stage.choices.push({ id: uniqueId("new_choice", Object.fromEntries(stage.choices.map((choice) => [choice.id, true]))), label: "New choice", endEncounter: true });
    markDirty();
    render();
  } else if (action === "remove-choice") {
    const stage = state.draft.stages[button.dataset.stage];
    stage.choices.splice(Number(button.dataset.choiceIndex), 1);
    markDirty();
    render();
  } else if (action === "add-object") {
    const owner = button.dataset.owner;
    const parent = button.dataset.parentPath !== undefined
      ? pathValue(state.draft, button.dataset.parentPath)
      : owner === "encounter-requirements" ? state.draft : getChoice(button.dataset.stage, button.dataset.choiceIndex);
    const collectionName = button.dataset.collectionName || (owner === "stage-outcomes" ? "outcomes" : owner === "encounter-requirements" ? "requirements" : owner);
    parent[collectionName] ||= [];
    parent[collectionName].push({ type: isRequirementCollectionOwner(owner) ? "ownsItem" : "modifyResource" });
    markDirty();
    render();
  } else if (action === "remove-object") {
    const { collection, index } = getObjectRow(button.closest("[data-object-row]"));
    collection.splice(index, 1);
    markDirty();
    render();
  } else if (action === "add-resolution-item-id") {
    const target = pathValue(state.draft, button.dataset.resolutionPath);
    if (!target) return;
    target.itemIds ||= [];
    target.itemIds.push(state.catalog.known?.items?.[0] || Object.keys(state.catalog.items || {})[0] || "");
    markDirty();
    render();
  } else if (action === "remove-resolution-item-id") {
    const target = pathValue(state.draft, button.dataset.resolutionPath);
    if (!target?.itemIds) return;
    target.itemIds.splice(Number(button.dataset.resolutionItemIndex), 1);
    markDirty();
    render();
  } else if (action === "add-resolution-weighted-item") {
    const target = pathValue(state.draft, button.dataset.resolutionPath);
    if (!target) return;
    target.items ||= [];
    target.items.push({ itemId: Object.keys(state.catalog.items || {})[0] || "", weight: 1 });
    markDirty();
    render();
  } else if (action === "remove-resolution-weighted-item") {
    const target = pathValue(state.draft, button.dataset.resolutionPath);
    if (!target?.items) return;
    target.items.splice(Number(button.dataset.resolutionItemIndex), 1);
    markDirty();
    render();
  } else if (action === "add-resolution-option") {
    const target = pathValue(state.draft, button.dataset.resolutionPath);
    if (!target) return;
    target.options ||= [];
    target.options.push({ weight: 1, resultText: "", effects: [] });
    markDirty();
    render();
  } else if (action === "remove-resolution-option") {
    const target = pathValue(state.draft, button.dataset.resolutionPath);
    if (!target?.options) return;
    target.options.splice(Number(button.dataset.resolutionOptionIndex), 1);
    markDirty();
    render();
  } else if (action === "apply-effects") {
    try {
      const parsed = JSON.parse($("#effects-json").value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Effects JSON must be an object");
      state.draft.effects = parsed;
      markDirty();
      render();
    } catch (error) { window.alert(`Could not apply effects JSON: ${error.message}`); }
  } else if (action === "apply-raw") {
    try {
      const parsed = JSON.parse($("#raw-json").value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Raw JSON must be an object");
      state.draft = parsed;
      markDirty();
      render();
    } catch (error) { window.alert(`Could not apply raw JSON: ${error.message}`); }
  } else if (action === "add-loot-item") {
    const table = state.catalog.lootTables?.[button.dataset.tableId];
    if (!table) return;
    table.entries ||= [];
    table.entries.push({ type: "item", itemId: state.draft.id, weight: 1 });
    markDirty();
    render();
  } else if (action === "remove-loot-item") {
    const table = state.catalog.lootTables?.[button.dataset.tableId];
    const index = Number(button.dataset.entryIndex);
    if (!table?.entries?.[index]) return;
    table.entries.splice(index, 1);
    markDirty();
    render();
  } else if (action === "add-shop-item") {
    const itemId = $("#new-stock-item")?.value.trim();
    if (!itemId) return;
    state.draft.itemsForSale ||= {};
    if (!state.draft.itemsForSale[itemId]) state.draft.itemsForSale[itemId] = { price: 0 };
    markDirty(); render();
  } else if (action === "remove-shop-item") {
    delete state.draft.itemsForSale[button.closest("[data-shop-row]").dataset.itemId];
    markDirty(); render();
  } else if (action === "add-sell-item") {
    const itemId = $("#new-sell-item")?.value.trim();
    if (!itemId) return;
    state.draft.sellValues ||= {};
    if (!Object.prototype.hasOwnProperty.call(state.draft.sellValues, itemId)) state.draft.sellValues[itemId] = 0;
    markDirty(); render();
  } else if (action === "remove-sell-item") {
    delete state.draft.sellValues[button.closest("[data-sell-row]").dataset.itemId];
    markDirty(); render();
  }
}

async function loadCatalog() {
  try {
    const response = await fetch("/api/catalog", { cache: "no-store" });
    if (!response.ok) throw new Error(await response.text());
    state.catalog = await response.json();
    state.validation = state.catalog.validation;
    const ids = Object.keys(state.catalog.encounters || {});
    state.category = "encounters";
    state.selectedId = ids[0] || null;
    state.originalSelectedId = state.selectedId;
    state.draft = state.selectedId ? clone(state.catalog.encounters[state.selectedId]) : null;
    state.dirty = false;
    state.draftDirty = false;
    state.searchByCategory = {};
    state.search = "";
    state.navigationHistory = [];
    render();
  } catch (error) {
    $("#editor-root").innerHTML = `<div class="empty-state"><h2>Could not load Grail content</h2><p>${escapeHtml(error.message)}</p><p>Start the editor with <code>python server.py</code> from the ContentEditor folder.</p></div>`;
  }
}

async function saveChanges() {
  if (!state.catalog) return;
  const snapshot = draftSnapshot();
  state.validationPending = true;
  renderValidation();
  try {
    const response = await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...snapshot, sourceHashes: state.catalog.sourceHashes }) });
    const payload = await response.json();
    if (!response.ok) {
      state.validation = payload.errors ? payload : { errors: [{ severity: "error", source: "save", message: payload.error || "Save failed" }], warnings: [] };
      state.validationPending = false;
      renderValidation();
      window.alert(payload.error || "Save failed. Resolve validation errors or reload.");
      return;
    }
    const selectedAfterSave = state.draft?.id || state.selectedId;
    state.catalog = payload;
    state.category = state.category;
    state.selectedId = selectedAfterSave && state.catalog[state.category][selectedAfterSave] ? selectedAfterSave : Object.keys(state.catalog[state.category])[0] || null;
    state.originalSelectedId = state.selectedId;
    state.draft = state.selectedId ? clone(state.catalog[state.category][state.selectedId]) : null;
    state.dirty = false;
    state.draftDirty = false;
    state.validation = state.catalog.validation;
    state.validationPending = false;
    render();
    const updates = (payload.saveResults || []).filter((result) => result.status === "updated");
    window.alert(updates.length ? `Saved ${updates.map((result) => result.file).join(" and ")}. A recovery backup was kept under Tools/ContentEditor/.backups.` : "No file changes were necessary.");
  } catch (error) {
    state.validationPending = false;
    state.validation = { errors: [{ severity: "error", source: "save", message: error.message }], warnings: [] };
    renderValidation();
  }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (button) handleAction(button);
});
document.addEventListener("input", (event) => handleInput(event.target));
document.addEventListener("change", (event) => {
  if (event.target.matches("textarea[data-object-json]")) handleObjectJson(event.target);
  else handleInput(event.target);
});
$("#entry-search").addEventListener("input", (event) => { setCurrentSearch(event.target.value); renderEntryPaneOnly(); });
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });

loadCatalog();
