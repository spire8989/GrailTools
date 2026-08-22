/* global fetch */

const COMMON_REQUIREMENT_TYPES = [
  "anyOf", "allOf",
  "ownsItem", "notOwnsItem", "carriedItem", "equippedItem", "availableExpeditionItem",
  "knowledge", "companion", "unlockedCompanion", "notUnlockedCompanion", "runFlag", "notRunFlag",
  "campaignFlag", "currentPath", "minimumResource", "minimumHealth", "maximumHealth", "minimumDistance", "notKnowledge",
];
const COMMON_EFFECT_TYPES = [
  "modifyResource", "consumeExpeditionItem", "gainUnsecuredItem", "gainUniqueUnsecuredItem",
  "gainRandomUnsecuredItem", "gainWeightedRandomUnsecuredItem", "rollLootTable", "startCombat",
  "setRunFlag", "setCampaignFlag", "changePath", "unlockCompanion", "applyInjury", "conditional",
  "setCampaignFlagOnSafeReturn",
  "randomChance", "randomOne", "learnRecipe", "markEncounterSeen",
  "startDialogue",
];

const CONTENT_CATEGORIES = [
  ["imageAssets", "Images"],
  ["audioAssets", "Audio"],
  ["encounters", "Encounters"],
  ["injuries", "Injuries"],
  ["campEvents", "Camp Events"],
  ["dialogues", "Dialogue"],
  ["paths", "Paths"],
  ["expeditions", "Expeditions"],
  ["recipes", "Recipes"],
  ["materials", "Materials"],
  ["craftingProviders", "Crafting"],
  ["shops", "Shops"],
  ["npcs", "NPCs"],
  ["destinations", "Destinations"],
  ["locations", "Locations"],
  ["items", "Items"],
  ["combats", "Combat"],
  ["enemyDefinitions", "Enemies"],
  ["enemyActions", "Enemy Actions"],
  ["abilities", "Abilities"],
  ["combatStatuses", "Combat Statuses"],
  ["lootTables", "Loot Tables"],
];

const EDITABLE_REFERENCE_SOURCES = new Set([
  "encounters", "injuries", "campEvents", "dialogues", "expeditions", "recipes", "materials", "craftingProviders", "shops", "npcs", "destinations", "locations", "items", "combats", "abilities", "combatStatuses", "enemyDefinitions", "enemyActions", "lootTables",
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
    abilities: {
      kind: "",
      resource: "",
      tags: [],
      tagMode: "all",
    },
  },
  validation: { errors: [], warnings: [] },
  validationTimer: null,
  validationPending: false,
  navigationHistory: [],
  pathFilters: { search: "", direction: "all", minDistance: "", maxDistance: "", tag: "", sort: "title" },
  uploadTarget: null,
  pendingAssetUpload: null,
  assetPreview: null,
  assetPreviewRequest: 0,
  encounterLayoutDrag: null,
  outcomeLayoutDrag: null,
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

function enemyActionLabel(actionId) {
  const action = state.catalog?.enemyActions?.[actionId];
  return action?.name ? `${action.name} (${actionId})` : actionId;
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

function combatStatusLabel(statusId) {
  const status = state.catalog?.combatStatuses?.[statusId];
  return status?.name ? `${status.name} (${statusId})` : statusId;
}

function campEventLabel(eventId) {
  const event = state.catalog?.campEvents?.[eventId];
  const label = event?.title || state.catalog?.campEventLabels?.[eventId];
  return label ? `${label} (${eventId})` : eventId;
}

function dialogueLabel(dialogueId) {
  const dialogue = state.catalog?.dialogues?.[dialogueId];
  return dialogue?.title || dialogue?.name || state.catalog?.dialogueLabels?.[dialogueId] || dialogueId;
}

function npcLabel(npcId) {
  const npc = state.catalog?.npcs?.[npcId];
  return npc?.name || state.catalog?.npcLabels?.[npcId] || npcId;
}

function destinationLabel(destinationId) {
  const destination = state.catalog?.destinations?.[destinationId];
  return destination?.name || state.catalog?.destinationLabels?.[destinationId] || destinationId;
}

function locationLabel(locationId) {
  const location = state.catalog?.locations?.[locationId];
  return location?.name || state.catalog?.locationLabels?.[locationId] || locationId;
}

function assetTypeForCategory(category) {
  return category === "audioAssets" ? "audio" : "image";
}

function assetPreviewUrl(path) {
  return `/api/assets/file?path=${encodeURIComponent(path || "")}`;
}

function assetOptions(assetType, current, category = "") {
  const sourceCategory = assetType === "audio" ? "audioAssets" : "imageAssets";
  const assets = state.catalog?.[sourceCategory] || {};
  const entries = Object.entries(assets)
    .filter(([, asset]) => !category || asset.category === category)
    .sort(([left], [right]) => left.localeCompare(right));
  return `<option value="">None (use placeholder)</option>${entries.map(([id, asset]) => `<option value="${escapeHtml(id)}"${selected(id, current)}>${escapeHtml(id)} · ${escapeHtml(asset.category || assetType)}</option>`).join("")}`;
}

function renderAssetSelector(label, field, current, assetType = "image", category = "", context = "", optimizationProfile = "") {
  const sourceCategory = assetType === "audio" ? "audioAssets" : "imageAssets";
  const asset = current ? state.catalog?.[sourceCategory]?.[current] : null;
  const displayLabel = field === "campVisualAssetId" || field === "combatVisualAssetId"
    ? `${label} · Scene 16:9`
    : label;
  const helper = field === "travelTransitionAssetId"
    ? `<span class="hint">Optional foreground artwork used to hide Travel Scene changes. Falls back to crossfade.</span>`
    : field === "travelSeamForegroundAssetId"
      ? `<span class="hint">Optional transparent PNG/WebP repeated at each travel panorama seam.</span>`
      : field === "travelParallaxAssetId"
        ? `<span class="hint">Optional transparent foreground cutout imported from a SAM JSON mask; stays aligned at 1.0×.</span>`
        : field === "combatVisualAssetId"
          ? `<span class="hint">Static 16:9 battlefield artwork. This is separate from the normal encounter scene and is never processed as a transparent combat cutout.</span>`
          : "";
  const preview = asset && assetType === "image"
    ? `<img class="asset-field-preview" src="${assetPreviewUrl(asset.path)}" alt="Preview of ${escapeHtml(current)}">`
    : asset && assetType === "audio"
      ? `<audio class="asset-field-audio" controls preload="none" src="${assetPreviewUrl(asset.path)}"></audio>`
      : `<span class="asset-field-placeholder">Placeholder fallback</span>`;
  return `<label class="asset-selector wide"><span>${escapeHtml(displayLabel)}</span>${helper}<span class="asset-selector-controls"><select data-field="${escapeHtml(field)}">${assetOptions(assetType, current, category)}</select><button type="button" class="small-button" data-action="upload-asset" data-asset-type="${assetType}" data-asset-category="${category}" data-asset-field="${escapeHtml(field)}" data-asset-context="${escapeHtml(context)}" data-asset-profile="${escapeHtml(optimizationProfile)}">Upload New</button></span><span class="asset-field-preview-wrap">${preview}</span></label>`;
}

function renderTravelScenes(expedition) {
  const scenes = Array.isArray(expedition.travelScenes) ? expedition.travelScenes : [];
  const rows = scenes.map((scene, index) => {
    const asset = scene?.visualAssetId ? state.catalog?.imageAssets?.[scene.visualAssetId] : null;
    const parallaxAsset = scene?.travelParallaxAssetId ? state.catalog?.imageAssets?.[scene.travelParallaxAssetId] : null;
    const preview = asset
      ? `<img class="asset-field-preview" src="${assetPreviewUrl(asset.path)}" alt="Preview of ${escapeHtml(scene.visualAssetId)}">`
      : `<span class="asset-field-placeholder">Choose or upload an expedition image</span>`;
    return `<div class="travel-scene-editor-row" data-travel-scene-index="${index}">
      <label>Minimum distance<input type="number" min="0" step="any" data-travel-scene-field="minDistance" data-travel-scene-index="${index}" value="${escapeHtml(scene?.minDistance ?? "")}"></label>
       <label class="asset-selector"><span>Travel panorama</span><span class="asset-selector-controls"><select data-travel-scene-field="visualAssetId" data-travel-scene-index="${index}">${assetOptions("image", scene?.visualAssetId, "expedition")}</select><button type="button" class="small-button" data-action="upload-asset" data-asset-type="image" data-asset-category="expedition" data-asset-field="visualAssetId" data-asset-scene-index="${index}" data-asset-context="${escapeHtml(expedition.name || expedition.id || "travel scene")}" data-asset-profile="travel_panorama">Upload New</button></span><span class="asset-field-preview-wrap">${preview}</span></label>
       <label class="asset-selector"><span>Travel foreground (aligned)</span><span class="asset-selector-controls"><select data-travel-scene-field="travelParallaxAssetId" data-travel-scene-index="${index}">${assetOptions("image", scene?.travelParallaxAssetId, "expedition")}</select><button type="button" class="small-button" data-action="upload-asset" data-asset-type="image" data-asset-category="expedition" data-asset-field="travelParallaxAssetId" data-asset-scene-index="${index}" data-asset-context="${escapeHtml(expedition.name || expedition.id || "travel foreground")}" data-asset-profile="travel_panorama">Upload New</button></span><span class="asset-field-preview-wrap">${parallaxAsset ? `<img class="asset-field-preview" src="${assetPreviewUrl(parallaxAsset.path)}" alt="Preview of ${escapeHtml(scene.travelParallaxAssetId)}">` : `<span class="asset-field-placeholder">Optional SAM foreground cutout</span>`}</span></label>
      <label class="travel-motion-selector"><span>Motion</span><select data-travel-scene-field="motion" data-travel-scene-index="${index}"><option value="loop"${scene?.motion === "pan" ? "" : " selected"}>Loop</option><option value="pan"${scene?.motion === "pan" ? " selected" : ""}>Pan</option></select>${scene?.motion === "pan" ? "" : `<span class="travel-seam-loop-toggle"><input type="checkbox" data-travel-scene-field="showSeamForegroundBetweenLoops" data-travel-scene-index="${index}"${checked(scene?.showSeamForegroundBetweenLoops !== false)}>Show seam between loops</span>`}</label>
      <button type="button" class="small-button danger-outline" data-action="remove-travel-scene" data-travel-scene-index="${index}">Remove</button>
    </div>`;
  }).join("");
  return `<section class="section travel-scenes-editor"><div class="section-heading"><div><h3>Travel Scenes</h3><p>Recommended: 3:1 panoramic artwork. Optional distance-based artwork is selected by current distance and must stay sorted from nearest to farthest.</p></div><button type="button" class="small-button" data-action="add-travel-scene">Add Scene</button></div><div class="travel-scene-editor-list">${rows || `<p class="hint">No distance-based scenes. The legacy Travel visual is used for the whole route.</p>`}</div></section>`;
}

const TOWN_LAYOUT_FALLBACKS = Object.freeze({
  northwest: Object.freeze({ x: 0.18, y: 0.27 }),
  northeast: Object.freeze({ x: 0.82, y: 0.27 }),
  southwest: Object.freeze({ x: 0.22, y: 0.56 }),
  southeast: Object.freeze({ x: 0.78, y: 0.56 }),
  center: Object.freeze({ x: 0.50, y: 0.35 }),
});

const TOWN_MARKER_STYLES = Object.freeze(["tag", "ribbon", "ink"]);

function townLayoutMarkerStyle(location) {
  return TOWN_MARKER_STYLES.includes(location?.markerStyle) ? location.markerStyle : "tag";
}

function clampTownLayoutValue(value, fallback = 0.5) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.min(1, Math.max(0, numeric)) : fallback;
}

function townLayoutHotspot(destination) {
  const fallback = TOWN_LAYOUT_FALLBACKS[destination?.scenePosition] || TOWN_LAYOUT_FALLBACKS.center;
  return {
    x: clampTownLayoutValue(destination?.hotspot?.x, fallback.x),
    y: clampTownLayoutValue(destination?.hotspot?.y, fallback.y),
  };
}

function townLayoutDestinations(location) {
  return (Array.isArray(location?.destinations) ? location.destinations : [])
    .map((id) => state.catalog?.destinations?.[id])
    .filter(Boolean);
}

function renderTownLayoutEditor(location) {
  const asset = location?.visualAssetId ? state.catalog?.imageAssets?.[location.visualAssetId] : null;
  const destinations = townLayoutDestinations(location);
  const style = townLayoutMarkerStyle(location);
  if (!asset || asset.category !== "town") {
    return `<section class="section town-layout-editor" data-town-layout-editor><div class="section-heading"><div><h3>Town Layout</h3><p>Select a Town Background 2:3 image above to place destination hotspots.</p></div></div><p class="hint">No town background is selected for this location yet.</p></section>`;
  }
  const markers = destinations.map((destination) => {
    const hotspot = townLayoutHotspot(destination);
    return `<button type="button" class="town-layout-marker town-hotspot-style-${style}" data-town-layout-marker data-town-destination-id="${escapeHtml(destination.id)}" style="left:${hotspot.x * 100}%;top:${hotspot.y * 100}%" title="Drag ${escapeHtml(destination.name || destination.id)}"><span class="town-layout-marker-icon" aria-hidden="true">◆</span><span>${escapeHtml(destination.name || destination.id)}</span></button>`;
  }).join("");
  const fields = destinations.map((destination) => {
    const hotspot = townLayoutHotspot(destination);
    return `<div class="town-layout-coordinate-row" data-town-destination-id="${escapeHtml(destination.id)}"><strong>${escapeHtml(destination.name || destination.id)}</strong><label>X<input type="number" min="0" max="1" step="0.001" data-town-hotspot-input data-town-destination-id="${escapeHtml(destination.id)}" data-town-hotspot-axis="x" value="${hotspot.x.toFixed(3)}"></label><label>Y<input type="number" min="0" max="1" step="0.001" data-town-hotspot-input data-town-destination-id="${escapeHtml(destination.id)}" data-town-hotspot-axis="y" value="${hotspot.y.toFixed(3)}"></label></div>`;
  }).join("");
  return `<section class="section town-layout-editor" data-town-layout-editor><div class="section-heading"><div><h3>Town Layout</h3><p>Drag each destination marker onto the matching building. Coordinates are normalized to the 2:3 artwork.</p></div></div><label class="town-layout-style-selector">Marker style<select data-field="markerStyle" aria-label="Town marker style"><option value="tag"${style === "tag" ? " selected" : ""}>Tag</option><option value="ribbon"${style === "ribbon" ? " selected" : ""}>Ribbon</option><option value="ink"${style === "ink" ? " selected" : ""}>Ink</option></select></label><div class="town-layout-stage town-hotspot-style-${style}" data-town-layout-stage data-town-layout-style="${style}"><img class="town-layout-image" src="${assetPreviewUrl(asset.path)}" alt="${escapeHtml(location.name || "Town background")}" draggable="false"><div class="town-layout-marker-layer">${markers}</div></div><div class="town-layout-coordinate-list">${fields || `<p class="hint">This town has no destination references yet.</p>`}</div></section>`;
}

function updateTownLayoutMarker(destinationId, x, y) {
  const destination = state.catalog?.destinations?.[destinationId];
  if (!destination) return false;
  destination.hotspot = { x: clampTownLayoutValue(x), y: clampTownLayoutValue(y) };
  const marker = document.querySelector(`[data-town-layout-marker][data-town-destination-id="${CSS.escape(destinationId)}"]`);
  if (marker) {
    marker.style.left = `${destination.hotspot.x * 100}%`;
    marker.style.top = `${destination.hotspot.y * 100}%`;
  }
  document.querySelectorAll(`[data-town-hotspot-input][data-town-destination-id="${CSS.escape(destinationId)}"]`).forEach((input) => {
    input.value = destination.hotspot[input.dataset.townHotspotAxis].toFixed(3);
  });
  return true;
}

function townLayoutPosition(stage, event) {
  const bounds = stage.getBoundingClientRect();
  return {
    x: clampTownLayoutValue((event.clientX - bounds.left) / bounds.width),
    y: clampTownLayoutValue((event.clientY - bounds.top) / bounds.height),
  };
}

function finishTownLayoutDrag() {
  if (!state.townLayoutDrag) return;
  state.townLayoutDrag.marker?.releasePointerCapture?.(state.townLayoutDrag.pointerId);
  state.townLayoutDrag = null;
  markDirty();
}

const ENCOUNTER_LAYOUT_FALLBACKS = Object.freeze({
  arthur: Object.freeze({ x: 0.42, y: 0.66 }),
  companion1: Object.freeze({ x: 0.58, y: 0.68 }),
  companion2: Object.freeze({ x: 0.70, y: 0.64 }),
});

const ENCOUNTER_LAYOUT_SLOTS = Object.freeze([
  { id: "arthur", label: "A", name: "Arthur" },
  { id: "companion1", label: "1", name: "Companion 1" },
  { id: "companion2", label: "2", name: "Companion 2" },
]);

function encounterLayoutPosition(encounter, slotId) {
  const fallback = ENCOUNTER_LAYOUT_FALLBACKS[slotId] || ENCOUNTER_LAYOUT_FALLBACKS.arthur;
  const authored = encounter?.encounterLayout?.[slotId];
  const x = Number(authored?.x);
  const y = Number(authored?.y);
  return {
    x: clampTownLayoutValue(Number.isFinite(x) ? x : fallback.x, fallback.x),
    y: clampTownLayoutValue(Number.isFinite(y) ? y : fallback.y, fallback.y),
  };
}

function renderEncounterLayoutEditor(encounter) {
  const asset = encounter?.visualAssetId ? state.catalog?.imageAssets?.[encounter.visualAssetId] : null;
  if (!asset || asset.category !== "encounter") {
    return `<section class="section encounter-layout-editor" data-encounter-layout-editor><div class="section-heading"><div><h3>Encounter Layout</h3><p>Select an encounter background above to place Arthur and the active companions.</p></div></div><p class="hint">No encounter background is selected for this definition yet.</p></section>`;
  }
  const markers = ENCOUNTER_LAYOUT_SLOTS.map((slot) => {
    const position = encounterLayoutPosition(encounter, slot.id);
    return `<button type="button" class="encounter-layout-marker encounter-layout-marker-${slot.id}" data-encounter-layout-marker data-encounter-layout-slot="${slot.id}" style="left:${position.x * 100}%;top:${position.y * 100}%" title="Drag ${slot.name}"><strong>${slot.label}</strong><span>${slot.name}</span></button>`;
  }).join("");
  const fields = ENCOUNTER_LAYOUT_SLOTS.map((slot) => {
    const position = encounterLayoutPosition(encounter, slot.id);
    return `<div class="encounter-layout-coordinate-row" data-encounter-layout-slot="${slot.id}"><strong>${slot.label} · ${slot.name}</strong><label>X<input type="number" min="0" max="1" step="0.001" data-encounter-layout-input data-encounter-layout-slot="${slot.id}" data-encounter-layout-axis="x" value="${position.x.toFixed(3)}"></label><label>Y<input type="number" min="0" max="1" step="0.001" data-encounter-layout-slot="${slot.id}" data-encounter-layout-axis="y" value="${position.y.toFixed(3)}"></label></div>`;
  }).join("");
  return `<section class="section encounter-layout-editor" data-encounter-layout-editor><div class="section-heading"><div><h3>Encounter Layout</h3><p>Drag Arthur and the companion markers over the encounter artwork. Coordinates are normalized to the 16:9 visual frame.</p></div></div><div class="encounter-layout-stage" data-encounter-layout-stage><img class="encounter-layout-image" src="${assetPreviewUrl(asset.path)}" alt="${escapeHtml(encounter.title || "Encounter background")}" draggable="false"><div class="encounter-layout-marker-layer">${markers}</div></div><div class="encounter-layout-coordinate-list">${fields}</div></section>`;
}

function updateEncounterLayoutMarker(slotId, x, y) {
  if (!state.draft || !ENCOUNTER_LAYOUT_FALLBACKS[slotId]) return false;
  const fallback = ENCOUNTER_LAYOUT_FALLBACKS[slotId];
  const position = {
    x: clampTownLayoutValue(x, fallback.x),
    y: clampTownLayoutValue(y, fallback.y),
  };
  state.draft.encounterLayout ||= {};
  state.draft.encounterLayout[slotId] = position;
  const marker = document.querySelector(`[data-encounter-layout-marker][data-encounter-layout-slot="${CSS.escape(slotId)}"]`);
  if (marker) {
    marker.style.left = `${position.x * 100}%`;
    marker.style.top = `${position.y * 100}%`;
  }
  document.querySelectorAll(`[data-encounter-layout-input][data-encounter-layout-slot="${CSS.escape(slotId)}"]`).forEach((input) => {
    input.value = position[input.dataset.encounterLayoutAxis].toFixed(3);
  });
  return true;
}

function encounterLayoutPositionFromPointer(stage, event) {
  const bounds = stage.getBoundingClientRect();
  return {
    x: clampTownLayoutValue((event.clientX - bounds.left) / bounds.width),
    y: clampTownLayoutValue((event.clientY - bounds.top) / bounds.height),
  };
}

function finishEncounterLayoutDrag() {
  if (!state.encounterLayoutDrag) return;
  state.encounterLayoutDrag.marker?.releasePointerCapture?.(state.encounterLayoutDrag.pointerId);
  state.encounterLayoutDrag = null;
  markDirty();
}

function commitEncounterLayoutInput(input) {
  const slotId = input.dataset.encounterLayoutSlot;
  if (!ENCOUNTER_LAYOUT_FALLBACKS[slotId]) return;
  const current = encounterLayoutPosition(state.draft, slotId);
  const value = clampTownLayoutValue(input.value, current[input.dataset.encounterLayoutAxis]);
  updateEncounterLayoutMarker(
    slotId,
    input.dataset.encounterLayoutAxis === "x" ? value : current.x,
    input.dataset.encounterLayoutAxis === "y" ? value : current.y,
  );
  markDirty();
}

function outcomeAtPath(outcomePath) {
  const parent = pathValue(state.draft, outcomePath);
  return parent && typeof parent === "object" ? parent : null;
}

function outcomeVisualIsCustom(outcome) {
  const visual = outcome?.visualOverride;
  return Boolean(visual && (
    visual.backgroundAssetId
    || visual.encounterLayout
    || (Array.isArray(visual.hiddenSlots) && visual.hiddenSlots.length > 0)
  ));
}

function cleanupOutcomeVisual(outcome) {
  const visual = outcome?.visualOverride;
  if (!visual) return;
  if (!visual.backgroundAssetId
    && !visual.encounterLayout
    && (!Array.isArray(visual.hiddenSlots) || visual.hiddenSlots.length === 0)) {
    delete outcome.visualOverride;
  }
}

function encounterVisualAssetOptions(current) {
  const assets = Object.entries(state.catalog?.imageAssets || {})
    .filter(([, asset]) => ["encounter", "expedition"].includes(asset.category))
    .sort(([left], [right]) => left.localeCompare(right));
  return `<option value="">Select encounter image...</option>${assets.map(([id, asset]) => `<option value="${escapeHtml(id)}"${selected(id, current)}>${escapeHtml(id)} · ${escapeHtml(asset.category || "image")}</option>`).join("")}`;
}

function outcomeLayoutPosition(outcome, slotId) {
  const fallback = encounterLayoutPosition(state.draft, slotId);
  const authored = outcome?.visualOverride?.encounterLayout?.[slotId];
  return {
    x: clampTownLayoutValue(authored?.x, fallback.x),
    y: clampTownLayoutValue(authored?.y, fallback.y),
  };
}

function outcomeLayoutAsset(outcome) {
  const assetId = outcome?.visualOverride?.backgroundAssetId || state.draft?.visualAssetId;
  return assetId ? state.catalog?.imageAssets?.[assetId] : null;
}

function renderOutcomeLayoutEditor(outcome, outcomePath) {
  const asset = outcomeLayoutAsset(outcome);
  if (!asset) return `<p class="hint">Select an encounter background to preview the custom party layout.</p>`;
  const markers = ENCOUNTER_LAYOUT_SLOTS.map((slot) => {
    const position = outcomeLayoutPosition(outcome, slot.id);
    return `<button type="button" class="outcome-layout-marker outcome-layout-marker-${slot.id}" data-outcome-layout-marker data-outcome-layout-path="${escapeHtml(outcomePath)}" data-outcome-layout-slot="${slot.id}" style="left:${position.x * 100}%;top:${position.y * 100}%" title="Drag ${slot.name}">${slot.label}</button>`;
  }).join("");
  const fields = ENCOUNTER_LAYOUT_SLOTS.map((slot) => {
    const position = outcomeLayoutPosition(outcome, slot.id);
    return `<div class="encounter-layout-coordinate-row"><strong>${slot.label} · ${slot.name}</strong><label>X<input type="number" min="0" max="1" step="0.001" data-outcome-layout-input data-outcome-layout-path="${escapeHtml(outcomePath)}" data-outcome-layout-slot="${slot.id}" data-outcome-layout-axis="x" value="${position.x.toFixed(3)}"></label><label>Y<input type="number" min="0" max="1" step="0.001" data-outcome-layout-input data-outcome-layout-path="${escapeHtml(outcomePath)}" data-outcome-layout-slot="${slot.id}" data-outcome-layout-axis="y" value="${position.y.toFixed(3)}"></label></div>`;
  }).join("");
  return `<div class="outcome-layout-editor" data-outcome-layout-editor><div class="outcome-layout-stage" data-outcome-layout-stage data-outcome-layout-path="${escapeHtml(outcomePath)}"><img class="encounter-layout-image" src="${assetPreviewUrl(asset.path)}" alt="${escapeHtml(asset.id || "Encounter background")}" draggable="false"><div class="encounter-layout-marker-layer">${markers}</div></div><details class="outcome-layout-advanced"><summary>Advanced coordinates</summary><div class="encounter-layout-coordinate-list">${fields}</div></details></div>`;
}

function renderOutcomeVisualEditor(outcome, outcomePath) {
  if (!outcomePath || !outcome || typeof outcome !== "object") return "";
  const visual = outcome.visualOverride || {};
  const backgroundCustom = Boolean(visual.backgroundAssetId);
  const layoutCustom = Boolean(visual.encounterLayout);
  const status = outcomeVisualIsCustom(outcome) ? "Custom" : "Inherit encounter";
  const hiddenSlots = new Set(Array.isArray(visual.hiddenSlots) ? visual.hiddenSlots : []);
  return `<details class="outcome-visual-editor" data-outcome-visual-editor data-outcome-visual-path="${escapeHtml(outcomePath)}"><summary>Visuals: ${status}</summary><div class="outcome-visual-controls"><div class="form-grid"><label>Background<select data-outcome-visual-field="backgroundMode" data-outcome-visual-path="${escapeHtml(outcomePath)}"><option value="inherit"${backgroundCustom ? "" : " selected"}>Inherit</option><option value="custom"${backgroundCustom ? " selected" : ""}>Custom</option></select></label>${backgroundCustom ? `<label class="wide">Custom background<select data-outcome-visual-field="backgroundAssetId" data-outcome-visual-path="${escapeHtml(outcomePath)}">${encounterVisualAssetOptions(visual.backgroundAssetId)}</select></label>` : ""}<label>Party Layout<select data-outcome-visual-field="layoutMode" data-outcome-visual-path="${escapeHtml(outcomePath)}"><option value="inherit"${layoutCustom ? "" : " selected"}>Inherit</option><option value="custom"${layoutCustom ? " selected" : ""}>Custom</option></select></label></div>${layoutCustom ? renderOutcomeLayoutEditor(outcome, outcomePath) : ""}<fieldset class="outcome-hidden-slots"><legend>Hidden Slots</legend>${ENCOUNTER_LAYOUT_SLOTS.map((slot) => `<label class="check-chip"><input type="checkbox" data-outcome-visual-field="hiddenSlot" data-outcome-visual-path="${escapeHtml(outcomePath)}" data-outcome-visual-slot="${slot.id}"${hiddenSlots.has(slot.id) ? " checked" : ""}>${slot.name}</label>`).join("")}</fieldset></div></details>`;
}

function initializeOutcomeLayout(outcome) {
  outcome.visualOverride ||= {};
  outcome.visualOverride.encounterLayout ||= Object.fromEntries(ENCOUNTER_LAYOUT_SLOTS.map((slot) => [slot.id, encounterLayoutPosition(state.draft, slot.id)]));
}

function handleOutcomeVisualInput(input) {
  const outcome = outcomeAtPath(input.dataset.outcomeVisualPath);
  if (!outcome) return;
  const field = input.dataset.outcomeVisualField;
  if (field === "backgroundMode") {
    outcome.visualOverride ||= {};
    if (input.value === "custom") {
      outcome.visualOverride.backgroundAssetId ||= state.draft.visualAssetId || Object.keys(state.catalog?.imageAssets || {}).find((id) => ["encounter", "expedition"].includes(state.catalog.imageAssets[id]?.category));
    } else {
      delete outcome.visualOverride.backgroundAssetId;
    }
    cleanupOutcomeVisual(outcome);
    markDirty();
    render();
    return;
  }
  if (field === "backgroundAssetId") {
    outcome.visualOverride ||= {};
    if (input.value) outcome.visualOverride.backgroundAssetId = input.value;
    else delete outcome.visualOverride.backgroundAssetId;
    cleanupOutcomeVisual(outcome);
    markDirty();
    return;
  }
  if (field === "layoutMode") {
    if (input.value === "custom") initializeOutcomeLayout(outcome);
    else if (outcome.visualOverride) delete outcome.visualOverride.encounterLayout;
    cleanupOutcomeVisual(outcome);
    markDirty();
    render();
    return;
  }
  if (field === "hiddenSlot") {
    outcome.visualOverride ||= {};
    const hiddenSlots = new Set(Array.isArray(outcome.visualOverride.hiddenSlots) ? outcome.visualOverride.hiddenSlots : []);
    if (input.checked) hiddenSlots.add(input.dataset.outcomeVisualSlot);
    else hiddenSlots.delete(input.dataset.outcomeVisualSlot);
    if (hiddenSlots.size > 0) outcome.visualOverride.hiddenSlots = [...hiddenSlots];
    else delete outcome.visualOverride.hiddenSlots;
    cleanupOutcomeVisual(outcome);
    markDirty();
  }
}

function updateOutcomeLayoutMarker(outcomePath, slotId, x, y) {
  const outcome = outcomeAtPath(outcomePath);
  if (!outcome || !ENCOUNTER_LAYOUT_FALLBACKS[slotId]) return false;
  initializeOutcomeLayout(outcome);
  const fallback = encounterLayoutPosition(state.draft, slotId);
  const position = { x: clampTownLayoutValue(x, fallback.x), y: clampTownLayoutValue(y, fallback.y) };
  outcome.visualOverride.encounterLayout[slotId] = position;
  const selectorPath = CSS.escape(outcomePath);
  const selectorSlot = CSS.escape(slotId);
  const marker = document.querySelector(`[data-outcome-layout-marker][data-outcome-layout-path="${selectorPath}"][data-outcome-layout-slot="${selectorSlot}"]`);
  if (marker) {
    marker.style.left = `${position.x * 100}%`;
    marker.style.top = `${position.y * 100}%`;
  }
  document.querySelectorAll(`[data-outcome-layout-input][data-outcome-layout-path="${selectorPath}"][data-outcome-layout-slot="${selectorSlot}"]`).forEach((input) => {
    input.value = position[input.dataset.outcomeLayoutAxis].toFixed(3);
  });
  return true;
}

function outcomeLayoutPositionFromPointer(stage, event) {
  const bounds = stage.getBoundingClientRect();
  return {
    x: clampTownLayoutValue((event.clientX - bounds.left) / bounds.width),
    y: clampTownLayoutValue((event.clientY - bounds.top) / bounds.height),
  };
}

function finishOutcomeLayoutDrag() {
  if (!state.outcomeLayoutDrag) return;
  state.outcomeLayoutDrag.marker?.releasePointerCapture?.(state.outcomeLayoutDrag.pointerId);
  state.outcomeLayoutDrag = null;
  markDirty();
}

function commitOutcomeLayoutInput(input) {
  const outcome = outcomeAtPath(input.dataset.outcomeLayoutPath);
  if (!outcome) return;
  const current = outcomeLayoutPosition(outcome, input.dataset.outcomeLayoutSlot);
  const value = clampTownLayoutValue(input.value, current[input.dataset.outcomeLayoutAxis]);
  updateOutcomeLayoutMarker(input.dataset.outcomeLayoutPath, input.dataset.outcomeLayoutSlot, input.dataset.outcomeLayoutAxis === "x" ? value : current.x, input.dataset.outcomeLayoutAxis === "y" ? value : current.y);
  markDirty();
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
    ? ` ${normalizedRecipeIngredients(entry).map((ingredient) => ingredient.type === "item" ? itemLabel(ingredient.id) : materialLabel(ingredient.id)).join(" ")} ${entry.output?.itemId ? itemLabel(entry.output.itemId) : "provisions"}`
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
    if (category === "abilities") {
      if (filters.kind && (entry.kind || "active") !== filters.kind) return false;
      if (filters.resource && entry.cost?.resource !== filters.resource) return false;
      if (!tagsMatch(entry.tags, filters.tags, filters.tagMode)) return false;
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
  if (category === "abilities") {
    return [filters.kind, filters.resource, filters.tags.length ? "tags" : ""].filter(Boolean).length;
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
  const map = { combatId: "combats", enemyId: "enemyDefinitions", enemyActionId: "enemyActions", abilityId: "abilities", injuryId: "injuries", treatmentItemId: "items", tableId: "lootTables", pathId: "paths", expeditionId: "expeditions", recipeId: "recipes", materialId: "materials", craftingProvider: "craftingProviders", craftingProviderId: "craftingProviders", shopId: "shops", regionId: "regions", eventId: "campEvents", campEventId: "campEvents", knowledgeId: "knowledge", companionId: "companions", dialogueId: "dialogues", dialogueSequenceId: "dialogues", introDialogueSequenceId: "dialogues", speakerId: "npcs", npcId: "npcs", destinationId: "destinations", locationId: "locations" };
  if (!map[field]) return `<input ${fieldAttribute} value="${escapeHtml(value || "")}">`;
  let values = ["items", "combats", "enemyDefinitions", "enemyActions", "abilities", "injuries", "campEvents", "lootTables", "paths", "expeditions", "recipes", "materials", "craftingProviders", "dialogues", "npcs", "destinations", "locations", "shops"].includes(map[field])
    ? Object.keys(state.catalog?.[map[field]] || {}).sort()
    : known[map[field]] || [];
  if (field === "speakerId" && value === "arthur" && !values.includes("arthur")) values = ["arthur", ...values];
  const labels = map[field] === "items"
    ? Object.fromEntries(values.map((id) => [id, itemLabel(id)]))
    : map[field] === "enemyDefinitions"
      ? Object.fromEntries(values.map((id) => [id, enemyLabel(id)]))
      : map[field] === "enemyActions"
        ? Object.fromEntries(values.map((id) => [id, enemyActionLabel(id)]))
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
            : map[field] === "dialogues"
              ? Object.fromEntries(values.map((id) => [id, dialogueLabel(id)]))
              : map[field] === "npcs"
                ? Object.fromEntries(values.map((id) => [id, npcLabel(id)]))
                : map[field] === "destinations"
                  ? Object.fromEntries(values.map((id) => [id, destinationLabel(id)]))
                  : map[field] === "locations"
                    ? Object.fromEntries(values.map((id) => [id, locationLabel(id)]))
    : {};
  const openCategory = map[field] === "items" ? "items" : map[field] === "combats" ? "combats" : map[field] === "enemyDefinitions" ? "enemyDefinitions" : map[field] === "enemyActions" ? "enemyActions" : map[field] === "abilities" ? "abilities" : map[field] === "injuries" ? "injuries" : map[field] === "campEvents" ? "campEvents" : map[field] === "lootTables" ? "lootTables" : map[field] === "paths" ? "paths" : map[field] === "expeditions" ? "expeditions" : map[field] === "recipes" ? "recipes" : map[field] === "materials" ? "materials" : map[field] === "craftingProviders" ? "craftingProviders" : map[field] === "dialogues" ? "dialogues" : map[field] === "npcs" ? "npcs" : map[field] === "destinations" ? "destinations" : map[field] === "locations" ? "locations" : null;
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
  if ("dialogueId" in object || type === "startDialogue") add("dialogueId", "Dialogue reference", "reference");
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
  if ("flag" in object || /Flag$/.test(type) || type === "setCampaignFlagOnSafeReturn") add("flag", "Flag");
  if ("knowledgeId" in object || type === "knowledge") add("knowledgeId", "Knowledge", "reference");
  if ("companionId" in object || ["companion", "unlockedCompanion", "notUnlockedCompanion", "unlockCompanion"].includes(type)) add("companionId", "Companion", "reference");
  if ("value" in object || ["runFlag", "notRunFlag", "setRunFlag", "setCampaignFlag", "setCampaignFlagOnSafeReturn", "campaignFlag"].includes(type)) add("value", "Value");
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
  if (owner.endsWith("-effects")) return "effects";
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
  return `<section class="combat-resolution-branch"><div class="section-heading"><div><h4>${label}</h4><p>Authored result resolution after this combat branch.</p></div></div><label class="wide">Result text<textarea data-resolution-field="resultText" data-resolution-path="${escapeHtml(branchPath)}">${escapeHtml(branch.resultText || "")}</textarea></label>${renderOutcomeVisualEditor(branch, branchPath)}${renderObjectCollection(`${label} outcomes`, branch.outcomes, "resolution-outcomes", "", -1, branchPath, true)}</section>`;
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
  const choicePath = `stages.${stageId}.choices[${index}]`;
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
    ${renderOutcomeVisualEditor(choice, choicePath)}
    ${renderObjectCollection("Requirements", choice.requirements, "requirements", stageId, index, choicePath)}
    ${renderObjectCollection("Costs", choice.costs, "costs", stageId, index, choicePath)}
    ${renderObjectCollection("Outcomes / effects", choice.outcomes, "outcomes", stageId, index, choicePath)}
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
      ${renderOutcomeVisualEditor(stage, `stages.${stageId}`)}
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
        ${renderAssetSelector("Encounter visual", "visualAssetId", encounter.visualAssetId, "image", "encounter", encounter.title || encounter.id)}
        ${renderAssetSelector("Combat Background Override", "combatVisualAssetId", encounter.combatVisualAssetId, "image", "combat_scene", encounter.title || encounter.id, "scene")}
        ${renderAssetSelector("Encounter ambience", "ambienceAssetId", encounter.ambienceAssetId, "audio", "ambience", encounter.title || encounter.id)}
        ${renderAssetSelector("Encounter sting", "stingAssetId", encounter.stingAssetId, "audio", "sfx", encounter.title || encounter.id)}
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
    ${renderEncounterLayoutEditor(encounter)}
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
     <section class="section"><div class="section-heading"><div><h3>Expedition metadata</h3><p>These fields are authored in <code>js/expedition-data.js</code> and remain the canonical expedition definition.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(expedition.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(expedition.name || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(expedition.description || "")}</textarea></label><label>Danger<input type="number" min="0" step="any" data-field="danger" value="${escapeHtml(expedition.danger ?? "")}"></label><label>Minimum objective distance<input type="number" min="0" step="any" data-field="minimumObjectiveDistance" value="${escapeHtml(expedition.minimumObjectiveDistance ?? "")}"></label><label>Region<select data-field="regionId"><option value="">Select region...</option>${selectOptions(known.regions || [], expedition.regionId)}</select></label><label>Kind<select data-field="kind"><option value="">Select kind...</option>${selectOptions(kinds, expedition.kind)}</select></label><label class="wide">Path${referenceInput("pathId", expedition.pathId, true)}</label></div>${renderAssetSelector("Travel visual", "travelVisualAssetId", expedition.travelVisualAssetId, "image", "expedition", expedition.name || expedition.id, "travel_panorama")}${renderAssetSelector("Travel foreground (aligned)", "travelParallaxAssetId", expedition.travelParallaxAssetId, "image", "expedition", expedition.name || expedition.id, "travel_panorama")}${renderAssetSelector("Travel Transition", "travelTransitionAssetId", expedition.travelTransitionAssetId, "image", "expedition", expedition.name || expedition.id)}${renderAssetSelector("Camp visual", "campVisualAssetId", expedition.campVisualAssetId, "image", "expedition", expedition.name || expedition.id)}${renderAssetSelector("Default Combat Background", "combatVisualAssetId", expedition.combatVisualAssetId, "image", "combat_scene", expedition.name || expedition.id, "scene")}${renderAssetSelector("Travel ambience", "travelAmbienceAssetId", expedition.travelAmbienceAssetId, "audio", "ambience", expedition.name || expedition.id)}${renderAssetSelector("Camp ambience", "campAmbienceAssetId", expedition.campAmbienceAssetId, "audio", "ambience", expedition.name || expedition.id)}</section>
    ${renderTravelScenes(expedition)}
    ${renderAssetSelector("Travel Seam Foreground", "travelSeamForegroundAssetId", expedition.travelSeamForegroundAssetId, "image", "expedition", expedition.name || expedition.id, "none")}
    <section class="section"><div class="section-heading"><div><h3>Camp event tables</h3><p>Choose reusable table IDs from <code>CAMP_EVENT_TABLE_DEFINITIONS</code>.</p></div></div>${renderReferenceChecks("campEventTableIds", expedition.campEventTableIds || [], known.campEventTables || [])}<div class="button-row">${campEventLinks || `<span class="hint">Selected tables have no editable camp-event entries.</span>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Prerequisites</h3><p>These are item IDs required by the existing expedition runtime.</p></div></div>${renderReferenceChecks("prerequisites", expedition.prerequisites || [], known.items || [], Object.fromEntries((known.items || []).map((id) => [id, itemLabel(id)])))}</section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known encounter and location references are shown before an expedition is deleted.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No known current references to this expedition.")}</div></section>
    <section class="section"><details><summary>Raw expedition JSON (advanced)</summary><p class="hint">Use raw JSON for future schema fields while preserving validation and surgical source updates.</p><textarea id="raw-json" class="raw-editor">${jsonText(expedition)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function collectClientReferences(value, source, references) {
  const scalarTypes = {
    portraitAssetId: "imageAssets", visualAssetId: "imageAssets", backgroundAssetId: "imageAssets", travelVisualAssetId: "imageAssets", travelParallaxAssetId: "imageAssets", travelTransitionAssetId: "imageAssets", travelSeamForegroundAssetId: "imageAssets", campVisualAssetId: "imageAssets", combatVisualAssetId: "imageAssets", travelAmbienceAssetId: "audioAssets", campAmbienceAssetId: "audioAssets", ambienceAssetId: "audioAssets", stingAssetId: "audioAssets",
    itemId: "items", treatmentItemId: "items", combatId: "combats", abilityId: "abilities", statusId: "combatStatuses", injuryId: "injuries",
    tableId: "lootTables", lootTableId: "lootTables", pathId: "paths", expeditionId: "expeditions",
    nextExpeditionId: "expeditions", materialId: "materials", recipeId: "recipes",
    craftingProvider: "craftingProviders", craftingProviderId: "craftingProviders", eventId: "campEvents", campEventId: "campEvents", knowledgeId: "knowledge", companionId: "companions", dialogueId: "dialogues", dialogueSequenceId: "dialogues", introDialogueSequenceId: "dialogues", speakerId: "npcs", npcId: "npcs", destinationId: "destinations", locationId: "locations",
  };
  const listTypes = {
    itemIds: "items", injuryIds: "injuries", prerequisites: "items", enemyIds: "enemies", abilityIds: "abilities",
    grantedAbilityIds: "abilities", combatAbilities: "abilities", actionPattern: "enemyActions", suppressedByStatuses: "combatStatuses",
    pathIds: "paths", expeditionIds: "expeditions", availableExpeditions: "expeditions", campEventTableIds: "campEventTables", recipeIds: "recipes", npcIds: "npcs", locationIds: "locations", destinationIds: "destinations", destinations: "destinations", npcs: "npcs", locations: "locations",
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
      if (scalarType && typeof child === "string" && !(key === "speakerId" && child === "arthur")) {
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
  ["encounters", "injuries", "campEvents", "dialogues", "expeditions", "recipes", "materials", "craftingProviders", "shops", "npcs", "destinations", "locations", "items", "combats", "abilities", "enemyDefinitions", "enemyActions", "lootTables"].forEach((source) => {
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
  return { encounters: "encounters", injuries: "injuries", campEvents: "campEvents", dialogues: "dialogues", campEventTables: "campEvents", expeditions: "expeditions", recipes: "recipes", materials: "materials", craftingProviders: "craftingProviders", shops: "shops", npcs: "npcs", destinations: "destinations", locations: "locations", items: "items", combats: "combats", enemyDefinitions: "enemyDefinitions", enemyActions: "enemyActions", abilities: "abilities", lootTables: "lootTables" }[source] || null;
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
  if (source === "dialogues") return dialogueLabel(id);
  if (source === "npcs") return npcLabel(id);
  if (source === "destinations") return destinationLabel(id);
  if (source === "locations") return locationLabel(id);
  if (source === "enemyDefinitions") return enemyLabel(id);
  if (source === "enemyActions") return enemyActionLabel(id);
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

function normalizedRecipeIngredients(recipe) {
  if (Array.isArray(recipe?.ingredients)) {
    return recipe.ingredients.map((ingredient) => ({
      type: ingredient?.type === "item" ? "item" : "material",
      id: ingredient?.id || "",
      quantity: ingredient?.quantity ?? 1,
    }));
  }
  const type = recipe?.ingredientType === "item" ? "item" : "material";
  return Object.entries(recipe?.ingredients || {}).map(([id, quantity]) => ({ type, id, quantity }));
}

function typedRecipeIngredientOptions(type, currentId) {
  const values = type === "item" ? Object.keys(state.catalog.items || {}).sort() : Object.keys(state.catalog.materials || {}).sort();
  const labels = type === "item"
    ? Object.fromEntries(values.map((id) => [id, itemLabel(id)]))
    : Object.fromEntries(values.map((id) => [id, materialLabel(id)]));
  return `<option value="">Select ${type}...</option>${selectOptions(values, currentId, labels)}`;
}

function renderRecipeIngredientRows(recipe) {
  const ingredients = normalizedRecipeIngredients(recipe);
  return ingredients.map(({ type, id, quantity }, index) => `<div class="recipe-ingredient-row" data-recipe-ingredient-row data-ingredient-id="${escapeHtml(id)}">
    <select data-recipe-ingredient-field="type" data-ingredient-index="${index}"><option value="item"${selected("item", type)}>Item</option><option value="material"${selected("material", type)}>Material</option></select>
    <select data-recipe-ingredient-field="id" data-ingredient-index="${index}">${typedRecipeIngredientOptions(type, id)}</select>
    <input type="number" min="1" step="1" data-recipe-ingredient-field="quantity" data-ingredient-index="${index}" value="${escapeHtml(quantity ?? "")}" aria-label="Ingredient quantity">
    ${id && type === "item" ? `<button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="items" data-reference-id="${escapeHtml(id)}">Open Item</button>` : `<span class="recipe-ref-kind">${type === "item" ? "Item" : "Material"}</span>`}
    <button type="button" class="small-button" data-action="move-recipe-ingredient" data-ingredient-index="${index}" data-direction="up"${index === 0 ? " disabled" : ""}>↑</button><button type="button" class="small-button" data-action="move-recipe-ingredient" data-ingredient-index="${index}" data-direction="down"${index === ingredients.length - 1 ? " disabled" : ""}>↓</button><button type="button" class="small-button" data-action="duplicate-recipe-ingredient" data-ingredient-index="${index}">Duplicate</button><button type="button" class="small-button danger-outline" data-action="remove-recipe-ingredient" data-ingredient-index="${index}">Remove</button>
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
  const legacyIngredientType = recipe.ingredientType || (normalizedRecipeIngredients(recipe).every((ingredient) => ingredient.type === "item") ? "item" : "material");
  return `<div class="editor-title"><div><h2>${escapeHtml(recipe.name || recipe.id || "New recipe")}</h2><p>${escapeHtml(recipe.id || "Unsaved ID")} · Produces: ${escapeHtml(outputType === "item" ? itemLabel(output.itemId || "") : `${output.provisions ?? 0} provisions`)}</p></div><span class="schema-badge">Recipe schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Recipe identity</h3><p>Recipes are authored in <code>js/crafting-data.js</code>.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(recipe.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(recipe.name || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(recipe.description || "")}</textarea></label><label>Rarity<select data-field="rarity"><option value="">No rarity</option>${selectOptions(rarityIds, recipe.rarity)}</select></label><label class="check-chip"><input type="checkbox" data-field="starter"${checked(recipe.starter)}> Starter recipe</label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Crafting provider</h3><p>Provider IDs are selected from the live <code>CRAFTING_PROVIDER_DEFINITIONS</code> catalog.</p></div></div><div class="form-grid"><label>Provider${referenceInput("craftingProvider", recipe.craftingProvider, true)}</label><label>Gold cost<input type="number" min="0" step="1" data-field="goldCost" value="${escapeHtml(recipe.goldCost ?? "")}"></label><label>Crafting duration (ms)<input type="number" min="1" step="1" data-field="craftingDurationMs" value="${escapeHtml(recipe.craftingDurationMs ?? "")}" placeholder="provider default"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Ingredients</h3><p>Each row names its source explicitly. Item and material rows can be mixed; older map recipes are displayed as typed rows and migrate on save.</p></div><button type="button" class="small-button" data-action="add-recipe-ingredient">Add ingredient</button></div><div class="recipe-ingredient-type"><label>Legacy type compatibility<select data-field="ingredientType"><option value="material"${selected("material", legacyIngredientType)}>Materials</option><option value="item"${selected("item", legacyIngredientType)}>Items</option></select></label><span class="hint">Changing this compatibility control converts every row; use row types for mixed recipes.</span></div><div class="recipe-ingredient-list">${renderRecipeIngredientRows(recipe) || `<p class="hint">No ingredients. Add one to make this recipe craftable.</p>`}</div>${recipe.ingredientType ? `<p class="hint">Deprecated legacy ingredientType: ${escapeHtml(recipe.ingredientType)}. Saving converts this recipe to canonical typed rows.</p>` : ""}</section>
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

function renderItemOnHitEffects(effects) {
  const entries = Array.isArray(effects.onHitEffects) ? effects.onHitEffects : [];
  const statusIds = state.catalog.known?.combatStatuses || Object.keys(state.catalog.combatStatuses || {}).sort();
  const statusLabels = Object.fromEntries(statusIds.map((id) => [id, combatStatusLabel(id)]));
  const rows = entries.map((effect, index) => `<div class="reference-row" data-item-on-hit-row>
    <span class="panel-count">${index + 1}</span>
    <select data-item-on-hit-field="type" data-item-on-hit-index="${index}">${selectOptions(["applyStatus"], effect.type)}</select>
    <select data-item-on-hit-field="statusId" data-item-on-hit-index="${index}"><option value="">Select status...</option>${selectOptions(statusIds, effect.statusId, statusLabels)}</select>
    <label>Chance<input type="number" min="0" max="1" step="any" data-item-on-hit-field="chance" data-item-on-hit-index="${index}" value="${escapeHtml(effect.chance ?? "")}"></label>
    <button type="button" class="small-button danger-outline" data-action="remove-item-on-hit" data-item-on-hit-index="${index}">Remove</button>
  </div>`).join("");
  return `<section class="section"><div class="section-heading"><div><h3>On-hit effects</h3><p>Successful normal Arthur attacks can apply referenced combat statuses.</p></div><button type="button" class="small-button" data-action="add-item-on-hit">Add effect</button></div>${rows || `<p class="hint">No on-hit effects.</p>`}</section>`;
}

function renderItemCombatTriggers(effects) {
  const entries = Array.isArray(effects.combatTriggers) ? effects.combatTriggers : [];
  const triggerIds = ["defendDamagePrevented", "beforeNormalAttack"];
  const effectIds = ["storeCharge", "consumeChargeForBonusDamage"];
  const rows = entries.map((trigger, index) => `<div class="reference-row" data-item-trigger-row>
    <span class="panel-count">${index + 1}</span>
    <select data-item-trigger-field="trigger" data-item-trigger-index="${index}">${selectOptions(triggerIds, trigger.trigger)}</select>
    <select data-item-trigger-field="effect" data-item-trigger-index="${index}">${selectOptions(effectIds, trigger.effect)}</select>
    <label>Charge ID<input data-item-trigger-field="chargeId" data-item-trigger-index="${index}" value="${escapeHtml(trigger.chargeId || "")}"></label>
    <label>Cap<input type="number" min="0" step="1" data-item-trigger-field="cap" data-item-trigger-index="${index}" value="${escapeHtml(trigger.cap ?? "")}" placeholder="optional"></label>
    <button type="button" class="small-button danger-outline" data-action="remove-item-trigger" data-item-trigger-index="${index}">Remove</button>
  </div>`).join("");
  return `<section class="section"><div class="section-heading"><div><h3>Combat triggers</h3><p>Author event-driven passive effects such as charge storage and spending.</p></div><button type="button" class="small-button" data-action="add-item-trigger">Add trigger</button></div>${rows || `<p class="hint">No combat triggers.</p>`}</section>`;
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
  const speedMarkup = Object.prototype.hasOwnProperty.call(effects, "combatSpeed") || item.equippable
    ? `<div class="form-grid" style="margin-top:11px"><label>Combat speed modifier<input type="number" step="any" data-item-effect-field="combatSpeed" value="${escapeHtml(effects.combatSpeed ?? "")}" placeholder="optional"></label></div>`
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
  const usedAsIngredient = recipeEntries.filter(([, recipe]) => normalizedRecipeIngredients(recipe).some((ingredient) => ingredient.type === "item" && ingredient.id === item.id));
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
    <section class="section"><div class="section-heading"><div><h3>Combat effects</h3><p>Weapon damage, armor defense, speed, and granted abilities are typed fields.</p></div></div>${damageMarkup}${defenseMarkup}${speedMarkup}<div class="section-heading" style="margin-top:14px"><div><h4>Granted abilities</h4><p>Validated against COMBAT_ABILITY_DEFINITIONS.</p></div></div><div class="check-grid ability-grid">${abilityMarkup || `<span class="hint">No combat abilities are available.</span>`}</div></section>
    ${renderItemOnHitEffects(effects)}
    ${renderItemCombatTriggers(effects)}
    ${combatMarkup}${treatmentMarkup}
    <section class="section"><div class="section-heading"><div><h3>Crafting</h3><p>Recipe relationships update from the current in-memory catalog.</p></div></div><h4>Produced By</h4><div class="reference-list">${recipeRelationshipRows(producedBy, "No recipe currently produces this item.")}</div><h4 style="margin-top:13px">Used As Ingredient In</h4><div class="reference-list">${recipeRelationshipRows(usedAsIngredient, "This item is not currently used as a recipe ingredient.")}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Loot table drops</h3><p>Focused support for adding this item to an existing table, including Bandit Leader. Other loot entry types remain read-only.</p></div></div><div class="loot-list">${lootMarkup || `<p class="hint">No loot tables are available.</p>`}</div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known live references are shown before deletion.</p></div></div><div class="reference-list">${referenceMarkup}</div></section>
    <section class="section"><details><summary>Advanced effects JSON</summary><p class="hint">Use this for uncommon effect shapes; known nested fields remain validated.</p><textarea id="effects-json" class="raw-editor">${jsonText(effects)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-effects">Apply effects JSON</button></div></details></section>
    <section class="section"><details><summary>Raw item JSON (advanced)</summary><p class="hint">Apply raw JSON to update the in-memory draft. Validation still blocks unsafe writes.</p><textarea id="raw-json" class="raw-editor">${jsonText(item)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function enemyActionOptions(current) {
  const ids = Object.keys(state.catalog.enemyActions || {}).sort();
  return `<option value="">Select an enemy action...</option>${selectOptions(ids, current, Object.fromEntries(ids.map((id) => [id, enemyActionLabel(id)])))}`;
}

function renderEnemyPatternRows(enemy) {
  const pattern = Array.isArray(enemy.actionPattern) ? enemy.actionPattern : [];
  return pattern.map((actionId, index) => `<div class="reference-row" data-enemy-pattern-row>
    <span class="panel-count">${index + 1}</span><select data-enemy-pattern-field="actionId" data-enemy-pattern-index="${index}">${enemyActionOptions(actionId)}</select><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="enemyActions" data-reference-id="${escapeHtml(actionId)}">Open Action</button><button type="button" class="small-button" data-action="move-enemy-action" data-enemy-pattern-index="${index}" data-direction="up"${index === 0 ? " disabled" : ""}>↑</button><button type="button" class="small-button" data-action="move-enemy-action" data-enemy-pattern-index="${index}" data-direction="down"${index === pattern.length - 1 ? " disabled" : ""}>↓</button><button type="button" class="small-button danger-outline" data-action="remove-enemy-action-pattern" data-enemy-pattern-index="${index}">Remove</button>
  </div>`).join("");
}

function renderEnemyTraitRows(enemy) {
  const traits = Array.isArray(enemy.traits) ? enemy.traits : [];
  const statusIds = state.catalog.known?.combatStatuses || Object.keys(state.catalog.combatStatuses || {}).sort();
  return traits.map((trait, index) => `<div class="section-card" data-enemy-trait-row>
    <div class="form-grid"><label>Type<select data-enemy-trait-field="type" data-enemy-trait-index="${index}"><option value="regeneration"${trait.type === "regeneration" ? " selected" : ""}>Regeneration</option></select></label><label>Amount<input type="number" min="0" step="any" data-enemy-trait-field="amount" data-enemy-trait-index="${index}" value="${escapeHtml(trait.amount ?? "")}"></label><label>Trigger<select data-enemy-trait-field="trigger" data-enemy-trait-index="${index}"><option value="activation"${trait.trigger === "activation" ? " selected" : ""}>Enemy activation</option></select></label></div>
    <div><strong>Suppressed by statuses</strong><div class="check-grid compact-check-grid">${statusIds.map((statusId) => `<label class="check-chip"><input type="checkbox" data-enemy-trait-status-toggle data-enemy-trait-index="${index}" data-status-id="${escapeHtml(statusId)}"${checked((trait.suppressedByStatuses || []).includes(statusId))}>${escapeHtml(statusId)}</label>`).join("") || `<span class="hint">No combat statuses are available.</span>`}</div></div>
    <div class="button-row"><button type="button" class="small-button danger-outline" data-action="remove-enemy-trait" data-enemy-trait-index="${index}">Remove trait</button></div>
  </div>`).join("");
}

function renderEnemy() {
  const enemy = state.draft;
  if (!enemy) return `<div class="empty-state">Choose an enemy to edit.</div>`;
  const references = (liveReferences().enemies || []).filter((reference) => reference.id === enemy.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(enemy.name || enemy.id || "New enemy")}</h2><p>${escapeHtml(enemy.id || "Unsaved ID")}</p></div><span class="schema-badge">Enemy schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Enemy identity and combat stats</h3><p>Enemies are reusable definitions authored in <code>COMBAT_ENEMY_DEFINITIONS</code>.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(enemy.id || "")}"></label><label>Name<input data-enemy-field="name" value="${escapeHtml(enemy.name || "")}"></label><label>Maximum HP<input type="number" min="1" step="1" data-enemy-field="maxHp" value="${escapeHtml(enemy.maxHp ?? "")}"></label><label>Speed<input type="number" min="1" step="any" data-enemy-field="speed" value="${escapeHtml(enemy.speed ?? "")}"></label><label>Defense<input type="number" min="0" step="any" data-enemy-field="defense" value="${escapeHtml(enemy.defense ?? "")}"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Action pattern</h3><p>Choose reusable Enemy Actions in their authored order. Repeated action IDs remain meaningful.</p></div><button type="button" class="small-button" data-action="add-enemy-action-pattern">Add action</button></div>${renderEnemyPatternRows(enemy) || `<p class="hint">No actions. Add an action to author this enemy's pattern.</p>`}</section>
    <section class="section"><div class="section-heading"><div><h3>Traits</h3><p>Traits are generic runtime behaviors. Regeneration may be suppressed by authored combat statuses.</p></div><button type="button" class="small-button" data-action="add-enemy-trait">Add trait</button></div>${renderEnemyTraitRows(enemy) || `<p class="hint">No traits. Add one to author a reusable enemy behavior.</p>`}</section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Combat definitions that include this enemy.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No combat currently uses this enemy.")}</div></section>
    <section class="section"><details><summary>Raw enemy JSON (advanced)</summary><p class="hint">Use this for future enemy presentation or runtime fields not yet present in the canonical definitions.</p><textarea id="raw-json" class="raw-editor">${jsonText(enemy)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderEnemyActionDefinition() {
  const action = state.draft;
  if (!action) return `<div class="empty-state">Choose an enemy action to edit.</div>`;
  const damage = action.damage || {};
  const injuries = state.catalog.known?.injuries || [];
  const targetModes = uniqueSorted(["arthur", ...Object.values(state.catalog.enemyActions || {}).map((value) => value?.target), action.target]);
  const references = (liveReferences().enemyActions || []).filter((reference) => reference.id === action.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(action.name || action.id || "New enemy action")}</h2><p>${escapeHtml(action.id || "Unsaved ID")}</p></div><span class="schema-badge">Enemy Action schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Action identity and damage</h3><p>Enemy Actions are reusable definitions authored in <code>COMBAT_ENEMY_ACTION_DEFINITIONS</code>.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(action.id || "")}"></label><label>Name / intent text<input data-enemy-action-field="name" value="${escapeHtml(action.name || "")}"></label><label>Damage minimum<input type="number" min="0" step="any" data-enemy-action-field="damage.minimum" value="${escapeHtml(damage.minimum ?? "")}"></label><label>Damage maximum<input type="number" min="0" step="any" data-enemy-action-field="damage.maximum" value="${escapeHtml(damage.maximum ?? "")}"></label><label>Target mode<select data-enemy-action-field="target"><option value="">Select target...</option>${selectOptions(targetModes, action.target)}</select></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Injury effect</h3><p>Optional injury references use the live Injury catalog.</p></div></div><div class="form-grid"><label>Injury${referenceInput("injuryId", action.injuryId, true)}</label><label>Injury chance<input type="number" min="0" max="1" step="any" data-enemy-action-field="injuryChance" value="${escapeHtml(action.injuryChance ?? "")}"></label><label class="check-chip"><input type="checkbox" data-enemy-action-field="telegraphed"${action.telegraphed ? " checked" : ""}>Telegraphed heavy attack</label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Enemy action patterns that reference this action.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No enemy currently uses this action.")}</div></section>
    <section class="section"><details><summary>Raw Enemy Action JSON (advanced)</summary><p class="hint">Use this for uncommon future effect, weight, or presentation fields.</p><textarea id="raw-json" class="raw-editor">${jsonText(action)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderCombat() {
  const combat = state.draft;
  if (!combat) return `<div class="empty-state">Choose a combat to edit.</div>`;
  const enemyIds = Array.isArray(combat.enemyIds) ? combat.enemyIds : [];
  const enemyOptions = Object.fromEntries((state.catalog.known?.enemies || []).map((id) => [id, enemyLabel(id)]));
  const enemyMarkup = enemyIds.map((enemyId, index) => `<div class="reference-row" data-combat-enemy-row><span class="panel-count">${index + 1}</span><select data-combat-enemy-field="id" data-enemy-index="${index}">${selectOptions(state.catalog.known?.enemies || [], enemyId, enemyOptions)}</select><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="enemyDefinitions" data-reference-id="${escapeHtml(enemyId)}">Open Enemy</button><button type="button" class="small-button" data-action="move-combat-enemy" data-enemy-index="${index}" data-direction="up"${index === 0 ? " disabled" : ""}>↑</button><button type="button" class="small-button" data-action="move-combat-enemy" data-enemy-index="${index}" data-direction="down"${index === enemyIds.length - 1 ? " disabled" : ""}>↓</button><button type="button" class="small-button danger-outline" data-action="remove-enemy" data-enemy-index="${index}">Remove</button></div>`).join("");
  const references = (liveReferences().combats || []).filter((reference) => reference.id === combat.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(combat.name || combat.title || combat.id || "New combat")}</h2><p>${enemyIds.length} enemy occurrence${enemyIds.length === 1 ? "" : "s"}</p></div><span class="schema-badge">Combat composition schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Combat metadata</h3><p>Combat definitions compose reusable Enemy IDs; enemy stats and action patterns are edited in their first-class categories.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(combat.id || "")}"></label><label>Title / display name<input data-field="name" value="${escapeHtml(combat.name || combat.title || "")}" placeholder="optional authored field"></label></div></section>
    <section class="section"><div class="section-heading"><div><h3>Enemy roster</h3><p>Repeated IDs remain independent occurrences in the combat lineup.</p></div><button type="button" class="small-button" data-action="add-enemy">Add enemy</button></div>${enemyMarkup || `<div class="empty-state">Add an enemy to begin authoring this combat.</div>`}</section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known encounter and camp-event references to this combat.</p></div></div><div class="reference-list">${renderReferenceRows(references)}</div></section>
    <section class="section"><details><summary>Raw combat JSON (advanced)</summary><p class="hint">Use raw JSON only for uncommon combat-level fields owned by the runtime.</p><textarea id="raw-json" class="raw-editor">${jsonText(combat)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

const COMBAT_EFFECT_TYPES = [
  "dealDamage", "weaponDamage", "heal", "modifyGauge", "applyStatus", "removeStatus",
  "modifyStat", "modifyResource", "storeCharge", "consumeCharge", "conditional", "randomChance",
  "setDefending", "setFlag", "attemptFlee", "applyInjury",
];
const COMBAT_EVENT_TYPES = [
  "combatStart", "actorReady", "turnStart", "beforeAction", "actionUsed", "beforeDamage",
  "damageDealt", "damageTaken", "damagePrevented", "afterDamage", "attackHit", "turnEnd",
  "actorDefeated", "enemyDefeated", "allyDefeated", "combatVictory", "combatDefeat", "combatFled", "combatEnd",
];

function abilityPathValue(path) {
  return pathValue(state.draft, path);
}

function setAbilityPathValue(path, value) {
  const tokens = path.match(/[^.[\]]+|\[\d+\]/g) || [];
  if (!tokens.length) return;
  let target = state.draft;
  tokens.slice(0, -1).forEach((token, index) => {
    const key = token.startsWith("[") ? Number(token.slice(1, -1)) : token;
    const nextToken = tokens[index + 1];
    if (target[key] === undefined) target[key] = nextToken?.startsWith("[") ? [] : {};
    target = target[key];
  });
  const last = tokens.at(-1);
  const key = last.startsWith("[") ? Number(last.slice(1, -1)) : last;
  if (value === undefined || value === "") delete target[key];
  else target[key] = value;
}

function combatTargetOptions(current) {
  return selectOptions(["target", "self", "source"], current, { target: "Selected target", self: "Ability owner", source: "Event source" });
}

function renderAbilityConditionEditor(condition, path) {
  const value = condition && typeof condition === "object" && !Array.isArray(condition) ? condition : {};
  const usesCombinator = Array.isArray(value.all) || Array.isArray(value.any);
  const statusIds = state.catalog.known?.combatStatuses || Object.keys(state.catalog.combatStatuses || {}).sort();
  const fields = usesCombinator
    ? `<p class="hint">This uses an all/any condition group. Edit the full group in the advanced condition JSON below.</p>`
    : `<div class="form-grid three">
      <label>Source side<select data-ability-condition-field="sourceSide" data-ability-condition-path="${escapeHtml(path)}"><option value="">Any side</option><option value="ally"${selected("ally", value.sourceSide)}>Ally</option><option value="enemy"${selected("enemy", value.sourceSide)}>Enemy</option></select></label>
      <label>Target side<select data-ability-condition-field="targetSide" data-ability-condition-path="${escapeHtml(path)}"><option value="">Any side</option><option value="ally"${selected("ally", value.targetSide)}>Ally</option><option value="enemy"${selected("enemy", value.targetSide)}>Enemy</option></select></label>
      <label>Action ID<input data-ability-condition-field="actionId" data-ability-condition-path="${escapeHtml(path)}" value="${escapeHtml(value.actionId || "")}" placeholder="optional"></label>
      <label>Health below<input type="number" min="0" max="1" step="0.05" data-ability-condition-field="healthBelowPercent" data-ability-condition-path="${escapeHtml(path)}" value="${escapeHtml(value.healthBelowPercent ?? "")}" placeholder="0.4"></label>
      <label>Health above<input type="number" min="0" max="1" step="0.05" data-ability-condition-field="healthAbovePercent" data-ability-condition-path="${escapeHtml(path)}" value="${escapeHtml(value.healthAbovePercent ?? "")}" placeholder="0.8"></label>
      <label>Target health below<input type="number" min="0" max="1" step="0.05" data-ability-condition-field="targetHealthBelowPercent" data-ability-condition-path="${escapeHtml(path)}" value="${escapeHtml(value.targetHealthBelowPercent ?? "")}"></label>
      <label>Status present<select data-ability-condition-field="hasStatus" data-ability-condition-path="${escapeHtml(path)}"><option value="">Any</option>${selectOptions(statusIds, value.hasStatus, Object.fromEntries(statusIds.map((id) => [id, id])))}</select></label>
      <label>Status missing<select data-ability-condition-field="missingStatus" data-ability-condition-path="${escapeHtml(path)}"><option value="">Any</option>${selectOptions(statusIds, value.missingStatus, Object.fromEntries(statusIds.map((id) => [id, id])))}</select></label>
      <label>Chance<input type="number" min="0" max="1" step="0.05" data-ability-condition-field="chance" data-ability-condition-path="${escapeHtml(path)}" value="${escapeHtml(value.chance ?? "")}" placeholder="1"></label>
      <label class="check-chip"><input type="checkbox" data-ability-condition-field="firstUse" data-ability-condition-path="${escapeHtml(path)}"${checked(value.firstUse)}> First use only</label>
      <label class="check-chip"><input type="checkbox" data-ability-condition-field="oncePerCombat" data-ability-condition-path="${escapeHtml(path)}"${checked(value.oncePerCombat)}> Once per combat</label>
    </div>`;
  return `<div class="ability-condition-editor"><strong>Trigger conditions</strong>${fields}<details><summary>Condition JSON (advanced)</summary><textarea class="raw-editor" data-ability-condition-json="${escapeHtml(path)}">${jsonText(condition || {})}</textarea></details></div>`;
}

function renderAbilityEffectSpecificFields(effect, path) {
  const type = effect.type;
  const target = ["dealDamage", "weaponDamage", "heal", "modifyGauge", "applyStatus", "removeStatus", "modifyStat", "setDefending", "setFlag", "applyInjury"].includes(type)
    ? `<label>Target<select data-ability-effect-field="target" data-ability-effect-path="${escapeHtml(path)}">${combatTargetOptions(effect.target || "target")}</select></label>` : "";
  const amount = ["dealDamage", "heal", "modifyGauge", "modifyResource", "modifyStat", "storeCharge"].includes(type)
    ? `<label>Amount<input type="number" step="any" data-ability-effect-field="amount" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.amount ?? "")}"></label>` : "";
  const multiplier = type === "weaponDamage"
    ? `<label>Weapon multiplier<input type="number" min="0" step="0.05" data-ability-effect-field="multiplier" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.multiplier ?? 1)}"></label><label class="check-chip"><input type="checkbox" data-ability-effect-field="triggersOnHit" data-ability-effect-path="${escapeHtml(path)}"${checked(effect.triggersOnHit !== false)}> Triggers on hit</label>` : "";
  const resource = type === "modifyResource"
    ? `<label>Resource<select data-ability-effect-field="resource" data-ability-effect-path="${escapeHtml(path)}"><option value="faith"${selected("faith", effect.resource)}>Faith</option><option value="health"${selected("health", effect.resource)}>Health</option><option value="provisions"${selected("provisions", effect.resource)}>Provisions</option></select></label>` : "";
  const status = ["applyStatus", "removeStatus"].includes(type)
    ? `<label>Status<select data-ability-effect-field="statusId" data-ability-effect-path="${escapeHtml(path)}">${selectOptions(state.catalog.known?.combatStatuses || [], effect.statusId)}</select></label>${type === "applyStatus" ? `<label>Chance<input type="number" min="0" max="1" step="0.05" data-ability-effect-field="chance" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.chance ?? "")}"></label>` : ""}` : "";
  const injury = type === "applyInjury"
    ? `<label>Injury<select data-ability-effect-field="injuryId" data-ability-effect-path="${escapeHtml(path)}">${selectOptions(state.catalog.known?.injuries || [], effect.injuryId)}</select></label><label>Chance<input type="number" min="0" max="1" step="0.05" data-ability-effect-field="chance" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.chance ?? "")}"></label>` : "";
  const stat = type === "modifyStat"
    ? `<label>Stat<input data-ability-effect-field="stat" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.stat || "")}" placeholder="defense, speed..."></label><label>Mode<select data-ability-effect-field="mode" data-ability-effect-path="${escapeHtml(path)}"><option value="add"${selected("add", effect.mode || "add")}>Add</option><option value="set"${selected("set", effect.mode)}>Set</option></select></label>` : "";
  const charge = ["storeCharge", "consumeCharge"].includes(type)
    ? `<label>Charge ID<input data-ability-effect-field="chargeId" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.chargeId || "")}" placeholder="resolve"></label>${type === "storeCharge" ? `<label>Cap<input type="number" min="0" step="1" data-ability-effect-field="cap" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.cap ?? "")}"></label>` : ""}` : "";
  const flag = type === "setFlag"
    ? `<label>Flag<input data-ability-effect-field="flag" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.flag || "")}"></label><label class="check-chip"><input type="checkbox" data-ability-effect-field="value" data-ability-effect-path="${escapeHtml(path)}"${checked(effect.value)}> Set true</label>` : "";
  const defending = type === "setDefending"
    ? `<label class="check-chip"><input type="checkbox" data-ability-effect-field="value" data-ability-effect-path="${escapeHtml(path)}"${checked(effect.value !== false)}> Set defending</label>` : "";
  const chance = type === "randomChance"
    ? `<label>Chance<input type="number" min="0" max="1" step="0.05" data-ability-effect-field="chance" data-ability-effect-path="${escapeHtml(path)}" value="${escapeHtml(effect.chance ?? "")}"></label>` : "";
  return `${target}${amount}${multiplier}${resource}${status}${injury}${stat}${charge}${flag}${defending}${chance}`;
}

function renderAbilityEffects(effects, path, depth = 0) {
  const list = Array.isArray(effects) ? effects : [];
  return `<div class="ability-effects" data-ability-effects-path="${escapeHtml(path)}"><div class="nested-heading"><span>${depth ? "Nested effects" : "Effects"} <span class="panel-count">${list.length}</span></span><button type="button" class="small-button" data-action="add-ability-effect" data-ability-effects-path="${escapeHtml(path)}">Add effect</button></div>${list.map((effect, index) => {
    const effectPath = `${path}[${index}]`;
    const nested = ["conditional", "randomChance"].includes(effect?.type);
    return `<div class="section-card ability-effect-row"><div class="form-grid"><label>Effect type<select data-ability-effect-field="type" data-ability-effect-path="${escapeHtml(effectPath)}">${selectOptions(COMBAT_EFFECT_TYPES, effect?.type)}</select></label>${renderAbilityEffectSpecificFields(effect || {}, effectPath)}</div>${effect?.type === "conditional" ? renderAbilityConditionEditor(effect.condition ?? effect.conditions, `${effectPath}.condition`) : ""}${nested && depth < 2 ? renderAbilityEffects(effect.effects, `${effectPath}.effects`, depth + 1) : ""}${nested && depth < 2 ? renderAbilityEffects(effect.elseEffects, `${effectPath}.elseEffects`, depth + 1) : ""}<div class="button-row"><button type="button" class="small-button danger-outline" data-action="remove-ability-effect" data-ability-effects-path="${escapeHtml(path)}" data-ability-effect-index="${index}">Remove effect</button></div></div>`;
  }).join("") || `<p class="hint">No effects authored.</p>`}</div>`;
}

function renderAbility() {
  const ability = state.draft;
  if (!ability) return `<div class="empty-state">Choose an ability to edit.</div>`;
  const references = (liveReferences().abilities || []).filter((reference) => reference.id === ability.id);
  const tags = Array.isArray(ability.tags) ? ability.tags.join(", ") : "";
  const trigger = ability.trigger || {};
  const effects = ability.kind === "passive" ? [] : ability.effects;
  return `<div class="editor-title"><div><h2>${escapeHtml(ability.name || ability.id || "New ability")}</h2><p>${escapeHtml(ability.id || "Unsaved ID")} · ${escapeHtml(ability.kind || "active")}</p></div><span class="schema-badge">Combat ability schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Identity and loadout behavior</h3><p>Active and passive abilities use one shared authoring surface. Tags and descriptions are visible in combat and loadout screens.</p></div></div><div class="form-grid">
      <label>ID<input data-field="id" value="${escapeHtml(ability.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(ability.name || "")}"></label>
      <label class="wide">Description<textarea data-field="description">${escapeHtml(ability.description || "")}</textarea></label>
      <label>Kind<select data-ability-field="kind"><option value="active"${selected("active", ability.kind || "active")}>Active</option><option value="passive"${selected("passive", ability.kind)}>Passive</option></select></label>
      <label class="wide">Tags<input data-ability-tags value="${escapeHtml(tags)}" placeholder="martial, faith, control"></label>
      <label>Target<select data-ability-field="target">${selectOptions(["enemy", "ally", "self", "menu", "none"], ability.target || "none")}</select></label>
      <label>Target mode<select data-ability-field="targetMode">${selectOptions(["self", "singleEnemy", "singleAlly", "allEnemies", "allAllies", "none"], ability.targetMode || "none")}</select></label>
      <label class="wide">Selection prompt<input data-ability-field="selectionPrompt" value="${escapeHtml(ability.selectionPrompt || "")}"></label>
    </div></section>
    ${ability.kind === "passive" ? `<section class="section"><div class="section-heading"><div><h3>Passive trigger</h3><p>Choose from the runtime combat lifecycle. Conditions use source/target sides, health, statuses, action/event, chance, and once-per-combat gates.</p></div></div><div class="form-grid"><label>Event<select data-ability-trigger-field="event"><option value="">Select event...</option>${selectOptions(COMBAT_EVENT_TYPES, trigger.event)}</select></label><label class="check-chip"><input type="checkbox" data-ability-trigger-field="oncePerCombat"${checked(trigger.oncePerCombat)}> Once per combat</label></div>${renderAbilityConditionEditor(trigger.conditions, "trigger.conditions")}${renderAbilityEffects(trigger.effects, "trigger.effects")}</section>` : `<section class="section"><div class="section-heading"><div><h3>Active cost and timing</h3><p>Costs are paid before effects resolve. Cooldowns count completed activations; charges reset for each combat.</p></div></div><div class="form-grid"><label>Cost resource<select data-ability-cost-field="resource"><option value="">No cost</option><option value="faith"${selected("faith", ability.cost?.resource)}>Faith</option><option value="health"${selected("health", ability.cost?.resource)}>Health</option><option value="provisions"${selected("provisions", ability.cost?.resource)}>Provisions</option></select></label><label>Cost amount<input type="number" min="0" step="1" data-ability-cost-field="amount" value="${escapeHtml(ability.cost?.amount ?? "")}"></label><label>Cooldown activations<input type="number" min="1" step="1" data-ability-field="cooldownActivations" value="${escapeHtml(ability.cooldownActivations ?? "")}"></label><label>Charges per combat<input type="number" min="1" step="1" data-ability-field="chargesPerCombat" value="${escapeHtml(ability.chargesPerCombat ?? "")}"></label></div></section>${renderAbilityEffects(effects, "effects")}`}
    <section class="section"><div class="section-heading"><div><h3>Used by / references</h3><p>Items, companions, encounters, and other authored content that grants or teaches this ability.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No current references.")}</div></section>
    <section class="section"><details><summary>Raw ability JSON (advanced)</summary><p class="hint">Use this for arbitrary future fields or condition groups deeper than the structured editor. Unknown fields are preserved.</p><textarea id="raw-json" class="raw-editor">${jsonText(ability)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderCombatStatus() {
  const status = state.draft;
  if (!status) return `<div class="empty-state">Choose a combat status to edit.</div>`;
  const references = (liveReferences().combatStatuses || []).filter((reference) => reference.id === status.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(status.name || status.id || "New combat status")}</h2><p>${escapeHtml(status.id || "Unsaved ID")}</p></div><span class="schema-badge">Combat Status schema</span></div>
    <section class="section"><div class="section-heading"><div><h3>Status definition</h3><p>Statuses are authored in <code>COMBAT_STATUS_DEFINITIONS</code> and tick on enemy activation.</p></div></div><div class="form-grid">
      <label>ID<input data-field="id" value="${escapeHtml(status.id || "")}"></label>
      <label>Name<input data-field="name" value="${escapeHtml(status.name || "")}"></label>
      <label class="wide">Description<textarea data-field="description">${escapeHtml(status.description || "")}</textarea></label>
      <label>Periodic damage<input type="number" min="0" step="1" data-field="periodicDamage" value="${escapeHtml(status.periodicDamage ?? "")}"></label>
      <label>Duration in activations<input type="number" min="1" step="1" data-field="durationActivations" value="${escapeHtml(status.durationActivations ?? "")}"></label>
      <label>Refresh behavior<select data-field="refreshBehavior"><option value="refresh"${selected("refresh", status.refreshBehavior)}>Refresh duration</option></select></label>
    </div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Items and other known definitions that reference this status.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No current item references.")}</div></section>
    <section class="section"><details><summary>Raw status JSON (advanced)</summary><textarea id="raw-json" class="raw-editor">${jsonText(status)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
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

function assetUsages(assetId, assetType) {
  const fields = assetType === "image"
    ? new Set(["portraitAssetId", "visualAssetId", "travelVisualAssetId", "travelParallaxAssetId", "travelTransitionAssetId", "travelSeamForegroundAssetId", "campVisualAssetId", "combatVisualAssetId"])
    : new Set(["travelAmbienceAssetId", "campAmbienceAssetId", "ambienceAssetId", "stingAssetId"]);
  const usages = [];
  const visit = (value, source, path) => {
    if (Array.isArray(value)) {
      value.forEach((child, index) => visit(child, source, `${path}[${index}]`));
      return;
    }
    if (!value || typeof value !== "object") return;
    Object.entries(value).forEach(([key, child]) => {
      const childPath = path ? `${path}.${key}` : key;
      if (fields.has(key) && child === assetId) usages.push({ source, path: childPath });
      visit(child, source, childPath);
    });
  };
  const snapshot = draftSnapshot();
  Object.entries(snapshot).forEach(([category, entries]) => {
    if (["imageAssets", "audioAssets", "known", "files", "sourceHashes", "validation", "references", "paths", "projectRoot"].includes(category)) return;
    if (!entries || typeof entries !== "object") return;
    Object.entries(entries).forEach(([id, entry]) => visit(entry, category, id));
  });
  const referenceType = assetType === "image" ? "imageAssets" : "audioAssets";
  const seen = new Set(usages.map((usage) => `${usage.source}:${usage.path}`));
  (state.catalog?.references?.[referenceType] || []).forEach((reference) => {
    if (reference.id !== assetId) return;
    const key = `${reference.source}:${reference.path}`;
    if (seen.has(key)) return;
    seen.add(key);
    usages.push({ source: reference.source, path: reference.path });
  });
  return usages;
}

function renderAsset() {
  const asset = state.draft;
  const assetType = assetTypeForCategory(state.category);
  const categoryValues = assetType === "image" ? ["location", "town", "expedition", "encounter", "combat", "combat_scene", "portrait", "ui"] : ["ambience", "sfx", "music"];
  const categoryLabel = categoryValues[0];
  if (!asset) {
    return `<div class="empty-state"><h2>No ${assetType} assets yet</h2><p>Upload a file to add it to the game's canonical assets folder and catalog.</p><label class="asset-upload-category">Asset category<select id="asset-browser-category">${categoryValues.map((category) => `<option value="${category}">${category}</option>`).join("")}</select></label><button type="button" class="primary" data-action="upload-asset" data-asset-browser="true" data-asset-type="${assetType}" data-asset-category="${categoryLabel}">Upload New ${assetType}</button></div>`;
  }
  const preview = assetType === "image"
    ? `<img class="asset-browser-preview" src="${assetPreviewUrl(asset.path)}" alt="Preview of ${escapeHtml(asset.id)}">`
    : `<audio controls preload="none" src="${assetPreviewUrl(asset.path)}"></audio>`;
  const usages = assetUsages(asset.id, assetType);
  return `<div class="editor-title"><div><h2>${escapeHtml(asset.id || "Asset")}</h2><p>${escapeHtml(asset.path || "No path")}</p></div><span class="schema-badge">${assetType} asset</span></div>
    <section class="section"><div class="asset-browser-card">${preview}<div><strong>${escapeHtml(asset.id)}</strong><span>${escapeHtml(asset.category || "Uncategorized")} · ${escapeHtml(asset.path || "")}</span><button type="button" class="small-button" data-action="replace-asset" data-asset-type="${assetType}" data-asset-id="${escapeHtml(asset.id)}" data-asset-category="${escapeHtml(asset.category || categoryLabel)}">Replace File</button></div></div></section>
    <section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Current authored references to this stable asset ID.</p></div></div>${usages.length ? `<div class="asset-usage-list">${usages.map((usage) => `<div class="asset-usage-row"><strong>${escapeHtml(usage.source)}</strong><code>${escapeHtml(usage.path)}</code></div>`).join("")}</div>` : `<p class="hint">No authored references yet.</p>`}</section>
    <section class="section"><details><summary>Raw asset metadata (read-only)</summary><pre class="raw-json-preview">${jsonText(asset)}</pre></details></section>`;
}

function injectAssetEditors() {
  if (!state.draft || ["paths", "imageAssets", "audioAssets", "encounters", "expeditions", "npcs"].includes(state.category)) return;
  if (["destinations", "locations", "enemyDefinitions", "campEvents"].includes(state.category)) {
    const form = $("#editor-root .form-grid");
    if (!form) return;
    const config = {
      destinations: ["Visual asset", "visualAssetId", "location"],
      locations: ["Visual asset", "visualAssetId", "town"],
      enemyDefinitions: ["Combat visual", "visualAssetId", "combat"],
      campEvents: ["Event visual", "visualAssetId", "encounter"],
    }[state.category];
    form.insertAdjacentHTML("beforeend", renderAssetSelector(config[0], config[1], state.draft[config[1]], "image", config[2], state.draft.name || state.draft.id));
    if (state.category === "locations") {
      form.closest(".section")?.insertAdjacentHTML("afterend", renderTownLayoutEditor(state.draft));
    }
    if (state.category === "campEvents") {
      form.insertAdjacentHTML("beforeend", renderAssetSelector("Event ambience", "ambienceAssetId", state.draft.ambienceAssetId, "audio", "ambience", state.draft.title || state.draft.id));
      form.insertAdjacentHTML("beforeend", renderAssetSelector("Event sting", "stingAssetId", state.draft.stingAssetId, "audio", "sfx", state.draft.title || state.draft.id));
    }
  }
  if (state.category === "dialogues") {
    document.querySelectorAll(".dialogue-node-card").forEach((card) => {
      const speaker = card.querySelector("[data-dialogue-node-field='speakerId']");
      if (!speaker || card.querySelector("[data-dialogue-node-field='portraitAssetId']")) return;
      const nodeId = speaker.dataset.dialogueNodeId;
      const node = state.draft.nodes?.[nodeId] || {};
      const field = `<label class="asset-selector wide"><span>Portrait override</span><span class="asset-selector-controls"><select data-dialogue-node-field="portraitAssetId" data-dialogue-node-id="${escapeHtml(nodeId)}">${assetOptions("image", node.portraitAssetId, "portrait")}</select><button type="button" class="small-button" data-action="upload-asset" data-asset-type="image" data-asset-category="portrait" data-asset-field="portraitAssetId" data-asset-node-id="${escapeHtml(nodeId)}" data-asset-context="${escapeHtml(node.speakerId || nodeId)}">Upload New</button></span></label>`;
      speaker.closest(".form-grid")?.insertAdjacentHTML("beforeend", field);
    });
  }
}

function referenceArrayOptions(category, current) {
  const values = Object.keys(state.catalog?.[category] || {}).sort();
  const labels = category === "items" ? Object.fromEntries(values.map((id) => [id, itemLabel(id)]))
    : category === "recipes" ? Object.fromEntries(values.map((id) => [id, recipeLabel(id)]))
      : category === "npcs" ? Object.fromEntries(values.map((id) => [id, npcLabel(id)]))
        : category === "destinations" ? Object.fromEntries(values.map((id) => [id, destinationLabel(id)]))
          : category === "locations" ? Object.fromEntries(values.map((id) => [id, locationLabel(id)]))
            : {};
  return `<option value="">Select reference...</option>${selectOptions(values, current, labels)}`;
}

function renderReferenceArray(label, field, values, category) {
  const entries = Array.isArray(values) ? values : [];
  return `<section class="reference-array"><div class="nested-heading"><span>${escapeHtml(label)} <span class="panel-count">${entries.length}</span></span><button type="button" class="small-button" data-action="add-reference-array" data-reference-array-field="${field}" data-reference-array-category="${category}">Add</button></div>${entries.map((value, index) => `<div class="reference-array-row"><select data-reference-array-field="${field}" data-reference-array-category="${category}" data-reference-array-index="${index}">${referenceArrayOptions(category, value)}</select><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="${category}" data-reference-id="${escapeHtml(value)}">Open</button><button type="button" class="small-button danger-outline" data-action="remove-reference-array" data-reference-array-field="${field}" data-reference-array-index="${index}">Remove</button></div>`).join("") || `<p class="hint">None.</p>`}</section>`;
}

function renderStringArray(label, field, values) {
  const entries = Array.isArray(values) ? values : [];
  return `<section class="reference-array"><div class="nested-heading"><span>${escapeHtml(label)} <span class="panel-count">${entries.length}</span></span><button type="button" class="small-button" data-action="add-string-array" data-string-array-field="${field}">Add</button></div>${entries.map((value, index) => `<div class="reference-array-row"><input data-string-array-field="${field}" data-string-array-index="${index}" value="${escapeHtml(value)}"><button type="button" class="small-button danger-outline" data-action="remove-string-array" data-string-array-field="${field}" data-string-array-index="${index}">Remove</button></div>`).join("") || `<p class="hint">None.</p>`}</section>`;
}

function dialogueNodeOptions(nodes, current) {
  return `<option value="">No next node</option>${selectOptions(Object.keys(nodes || {}), current)}`;
}

function dialogueSpeakerOptions(current) {
  const ids = ["arthur", ...Object.keys(state.catalog?.npcs || {}).sort()];
  const labels = { arthur: "Arthur (arthur)", ...Object.fromEntries(ids.slice(1).map((id) => [id, npcLabel(id)])) };
  return `<option value="">Select speaker...</option>${selectOptions(ids, current, labels)}`;
}

function renderDialogueChoice(nodeId, choice, index, nodes) {
  const choicePath = `nodes.${nodeId}.choices[${index}]`;
  return `<div class="choice-card dialogue-choice-card"><div class="object-top"><strong>Choice ${index + 1}</strong><div class="button-row"><button type="button" class="small-button" data-action="move-dialogue-choice" data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}" data-direction="up">Up</button><button type="button" class="small-button" data-action="move-dialogue-choice" data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}" data-direction="down">Down</button><button type="button" class="small-button danger-outline" data-action="remove-dialogue-choice" data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}">Remove</button></div></div><div class="form-grid"><label>ID<input data-dialogue-choice-field="id" data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}" value="${escapeHtml(choice.id || "")}"></label><label>Label<input data-dialogue-choice-field="label" data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}" value="${escapeHtml(choice.label || "")}"></label><label>Next node<select data-dialogue-choice-field="next" data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}">${dialogueNodeOptions(nodes, choice.next)}</select></label><label class="check-chip"><input type="checkbox" data-dialogue-choice-field="end" data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}"${checked(choice.end)}> End dialogue</label></div>${renderObjectCollection("Choice requirements", choice.requirements || choice.conditions, "dialogue-requirements", "", -1, choicePath, true)}${renderObjectCollection("Choice effects", choice.effects, "dialogue-effects", "", -1, choicePath, true)}<details><summary>Advanced choice JSON</summary><textarea class="object-json" data-dialogue-choice-json data-dialogue-node-id="${escapeHtml(nodeId)}" data-dialogue-choice-index="${index}">${jsonText(choice)}</textarea></details></div>`;
}

function renderDialogueNode(nodeId, node, nodes) {
  const nodePath = `nodes.${nodeId}`;
  const choices = Array.isArray(node.choices) ? node.choices : [];
  return `<details class="stage-card dialogue-node-card" open><summary>${escapeHtml(nodeId)}</summary><div class="form-grid"><label>Node ID<input data-dialogue-node-id-field="id" data-dialogue-node-id="${escapeHtml(nodeId)}" value="${escapeHtml(nodeId)}"></label><label>Speaker<select data-dialogue-node-field="speakerId" data-dialogue-node-id="${escapeHtml(nodeId)}">${dialogueSpeakerOptions(node.speakerId)}</select></label><label>Portrait key<input data-dialogue-node-field="portraitKey" data-dialogue-node-id="${escapeHtml(nodeId)}" value="${escapeHtml(node.portraitKey || "")}"></label><label class="wide">Text<textarea data-dialogue-node-field="text" data-dialogue-node-id="${escapeHtml(nodeId)}">${escapeHtml(node.text || "")}</textarea></label><label>Next node<select data-dialogue-node-field="next" data-dialogue-node-id="${escapeHtml(nodeId)}">${dialogueNodeOptions(nodes, node.next)}</select></label><label class="check-chip"><input type="checkbox" data-dialogue-node-field="end" data-dialogue-node-id="${escapeHtml(nodeId)}"${checked(node.end)}> End dialogue</label></div>${renderObjectCollection("Node requirements", node.requirements, "dialogue-requirements", "", -1, nodePath, true)}${renderObjectCollection("Node effects", node.effects, "dialogue-effects", "", -1, nodePath, true)}<div class="nested-heading"><span>Choices <span class="panel-count">${choices.length}</span></span><button type="button" class="small-button" data-action="add-dialogue-choice" data-dialogue-node-id="${escapeHtml(nodeId)}">Add choice</button></div>${choices.map((choice, index) => renderDialogueChoice(nodeId, choice, index, nodes)).join("") || `<p class="hint">No choices. The node advances through its Next node field.</p>`}<div class="button-row"><button type="button" class="small-button danger-outline" data-action="remove-dialogue-node" data-dialogue-node-id="${escapeHtml(nodeId)}">Remove node</button></div></details>`;
}

function renderDialogue() {
  const dialogue = state.draft;
  if (!dialogue) return `<div class="empty-state">Choose a dialogue sequence to edit.</div>`;
  const nodes = dialogue.nodes || {};
  const references = (liveReferences().dialogues || []).filter((reference) => reference.id === dialogue.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(dialogue.title || dialogue.name || dialogue.id || "New dialogue")}</h2><p>${escapeHtml(dialogue.id || "Unsaved ID")}</p></div><span class="schema-badge">Dialogue schema</span></div><section class="section"><div class="section-heading"><div><h3>Dialogue identity</h3><p>Reusable sequences are authored in <code>js/dialogue-data.js</code>. Nodes and choices use shared requirement/effect semantics.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(dialogue.id || "")}"></label><label>Title<input data-field="title" value="${escapeHtml(dialogue.title || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(dialogue.description || "")}</textarea></label><label>Start node<select data-field="start">${dialogueNodeOptions(nodes, dialogue.start)}</select></label></div></section><section class="section"><div class="section-heading"><div><h3>Nodes and branches</h3><p>Use selectors for speaker and node links; uncommon fields remain in Advanced JSON.</p></div><button type="button" class="small-button" data-action="add-dialogue-node">Add node</button></div>${Object.entries(nodes).map(([nodeId, node]) => renderDialogueNode(nodeId, node, nodes)).join("") || `<p class="empty-state">Add a node to begin authoring this sequence.</p>`}</section><section class="section"><div class="section-heading"><div><h3>Used by</h3><p>NPCs, destinations, encounters, camp events, and other content that invoke this sequence.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No current references.")}</div></section><section class="section"><details><summary>Raw dialogue JSON (advanced)</summary><textarea id="raw-json" class="raw-editor">${jsonText(dialogue)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderNpc() {
  const npc = state.draft;
  if (!npc) return `<div class="empty-state">Choose an NPC to edit.</div>`;
  const references = (liveReferences().npcs || []).filter((reference) => reference.id === npc.id);
  const locations = Object.keys(state.catalog.locations || {}).sort();
  return `<div class="editor-title"><div><h2>${escapeHtml(npc.name || npc.id || "New NPC")}</h2><p>${escapeHtml(npc.id || "Unsaved ID")}</p></div><span class="schema-badge">NPC schema</span></div><section class="section"><div class="section-heading"><div><h3>NPC identity</h3><p>NPCs are authored in <code>js/location-data.js</code> and referenced by stable ID.</p></div></div><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(npc.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(npc.name || "")}"></label><label>Role<input data-field="role" value="${escapeHtml(npc.role || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(npc.description || "")}</textarea></label><label>Dialogue sequence${referenceInput("dialogueSequenceId", npc.dialogueSequenceId, true)}</label><label>Intro sequence${referenceInput("introDialogueSequenceId", npc.introDialogueSequenceId, true)}</label>${renderAssetSelector("Portrait asset", "portraitAssetId", npc.portraitAssetId, "image", "portrait", npc.name || npc.id)}</div></section><section class="section"><div class="form-grid"><label class="wide">Simple dialogue lines<textarea data-lines-field="dialogue" placeholder="One line per entry">${escapeHtml((npc.dialogue || []).join("\n"))}</textarea></label><label class="wide">Rumor lines<textarea data-lines-field="rumors" placeholder="One line per entry">${escapeHtml((npc.rumors || []).join("\n"))}</textarea></label></div><div class="nested-heading"><span>Locations</span></div><div class="check-grid">${locations.map((id) => `<div class="reference-array-row"><label class="check-chip"><input type="checkbox" data-reference-toggle-field="locationIds" data-reference-toggle-value="${escapeHtml(id)}"${checked((npc.locationIds || []).includes(id))}>${escapeHtml(locationLabel(id))}</label><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="locations" data-reference-id="${escapeHtml(id)}">Open Location</button></div>`).join("")}</div></section><section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Destinations, locations, and dialogue references.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No current references.")}</div></section><section class="section"><details><summary>Raw NPC JSON (advanced)</summary><textarea id="raw-json" class="raw-editor">${jsonText(npc)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderDestination() {
  const destination = state.draft;
  if (!destination) return `<div class="empty-state">Choose a destination to edit.</div>`;
  const npcIds = Array.isArray(destination.npcIds) ? destination.npcIds : [];
  const actions = Array.isArray(destination.actions) ? destination.actions : [];
  return `<div class="editor-title"><div><h2>${escapeHtml(destination.name || destination.id || "New destination")}</h2><p>${escapeHtml(destination.id || "Unsaved ID")}</p></div><span class="schema-badge">Destination schema</span></div><section class="section"><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(destination.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(destination.name || "")}"></label><label>Type<input data-field="type" value="${escapeHtml(destination.type || "")}"></label><label>Visual key<input data-field="visualKey" value="${escapeHtml(destination.visualKey || "")}"></label><label>Scene position<input data-field="scenePosition" value="${escapeHtml(destination.scenePosition || "")}"></label><label>Shop${referenceInput("shopId", destination.shopId, true)}</label><label>Crafting provider${referenceInput("craftingProviderId", destination.craftingProviderId, true)}</label><label class="wide">Description<textarea data-field="description">${escapeHtml(destination.description || "")}</textarea></label><label class="check-chip"><input type="checkbox" data-field="requiresIntro"${checked(destination.requiresIntro)}> Requires intro</label></div></section><section class="section"><div class="nested-heading"><span>NPCs <span class="panel-count">${npcIds.length}</span></span><button type="button" class="small-button" data-action="add-destination-npc">Add NPC</button></div>${npcIds.map((id, index) => `<div class="reference-array-row"><select data-destination-npc-index="${index}">${referenceArrayOptions("npcs", id)}</select><button type="button" class="small-button inline-open" data-action="open-reference" data-reference-category="npcs" data-reference-id="${escapeHtml(id)}">Open NPC</button><button type="button" class="small-button danger-outline" data-action="remove-destination-npc" data-destination-npc-index="${index}">Remove</button></div>`).join("") || `<p class="hint">No NPC assigned.</p>`}</section><section class="section"><div class="nested-heading"><span>Actions <span class="panel-count">${actions.length}</span></span><button type="button" class="small-button" data-action="add-destination-action">Add action</button></div>${actions.map((action, index) => `<div class="reference-array-row"><input data-destination-action-index="${index}" value="${escapeHtml(action)}"><button type="button" class="small-button danger-outline" data-action="remove-destination-action" data-destination-action-index="${index}">Remove</button></div>`).join("") || `<p class="hint">No actions assigned.</p>`}</section><section class="section"><details><summary>Raw destination JSON (advanced)</summary><textarea id="raw-json" class="raw-editor">${jsonText(destination)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function renderLocation() {
  const location = state.draft;
  if (!location) return `<div class="empty-state">Choose a location to edit.</div>`;
  const references = (liveReferences().locations || []).filter((reference) => reference.id === location.id);
  return `<div class="editor-title"><div><h2>${escapeHtml(location.name || location.id || "New location")}</h2><p>${escapeHtml(location.id || "Unsaved ID")}</p></div><span class="schema-badge">Location schema</span></div><section class="section"><div class="form-grid"><label>ID<input data-field="id" value="${escapeHtml(location.id || "")}"></label><label>Name<input data-field="name" value="${escapeHtml(location.name || "")}"></label><label>Type<input data-field="type" value="${escapeHtml(location.type || "")}"></label><label>Chapter ID<input data-field="chapterId" value="${escapeHtml(location.chapterId || "")}"></label><label>Region${referenceInput("regionId", location.regionId, true)}</label><label>Visual key<input data-field="visualKey" value="${escapeHtml(location.visualKey || "")}"></label><label class="wide">Description<textarea data-field="description">${escapeHtml(location.description || "")}</textarea></label></div></section><section class="section">${renderReferenceArray("Destinations", "destinations", location.destinations, "destinations")}${renderReferenceArray("NPCs", "npcs", location.npcs, "npcs")}${renderReferenceArray("Shops", "shops", location.shops, "shops")}${renderReferenceArray("Expeditions", "availableExpeditions", location.availableExpeditions, "expeditions")}${renderStringArray("Quests", "availableQuests", location.availableQuests)}${renderObjectCollection("Location requirements", location.requirements, "location-requirements", "", -1, "", true)}</section><section class="section"><div class="section-heading"><div><h3>Used by</h3><p>Known references to this location.</p></div></div><div class="reference-list">${renderReferenceRows(references, "No current references.")}</div></section><section class="section"><details><summary>Raw location JSON (advanced)</summary><textarea id="raw-json" class="raw-editor">${jsonText(location)}</textarea><div class="button-row"><button type="button" class="small-button" data-action="apply-raw">Apply raw JSON</button></div></details></section>`;
}

function currentEntries() {
  if (!state.catalog) return {};
  const entries = { ...state.catalog[state.category] };
  if (state.draft && !["paths", "imageAssets", "audioAssets"].includes(state.category)) {
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

function renderAbilityFilters(entries) {
  const filters = filterState("abilities");
  const values = Object.values(entries);
  const tags = values.flatMap((ability) => Array.isArray(ability.tags) ? ability.tags : []);
  const resources = values.map((ability) => ability.cost?.resource);
  return `<div class="filter-drawer"><div class="form-grid filter-grid">
    <label>Kind<select data-filter-category="abilities" data-filter-field="kind"><option value="">Active and passive</option><option value="active"${selected("active", filters.kind)}>Active</option><option value="passive"${selected("passive", filters.kind)}>Passive</option></select></label>
    <label>Cost resource<select data-filter-category="abilities" data-filter-field="resource"><option value="">Any resource</option>${filterOptions(resources, filters.resource)}</select></label>
    <label class="wide">Tags<select multiple size="4" data-filter-category="abilities" data-filter-field="tags">${multiFilterOptions(tags, filters.tags)}</select></label>
    <label>Tag matching<select data-filter-category="abilities" data-filter-field="tagMode"><option value="all"${selected("all", filters.tagMode)}>Match ALL</option><option value="any"${selected("any", filters.tagMode)}>Match ANY</option></select></label>
  </div></div>`;
}

function renderFilterControls(entries, filtered) {
  const category = state.category;
  if (!filterState(category)) return "";
  const active = activeFilterCount(category);
  const drawer = state.filterOpen ? (category === "items" ? renderItemFilters(entries) : category === "encounters" ? renderEncounterFilters(entries) : renderAbilityFilters(entries)) : "";
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
      ? ` ${normalizedRecipeIngredients(entry).map((ingredient) => ingredient.type === "item" ? itemLabel(ingredient.id) : materialLabel(ingredient.id)).join(" ")} ${entry.output?.itemId ? itemLabel(entry.output.itemId) : "provisions"}`
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
  const readonlyPaths = ["paths", "imageAssets", "audioAssets"].includes(state.category);
  $("[data-action='add']").disabled = readonlyPaths;
  $("[data-action='duplicate']").disabled = readonlyPaths;
  $("[data-action='delete']").disabled = readonlyPaths;
  $("#editor-root").innerHTML = state.category === "imageAssets" || state.category === "audioAssets"
    ? renderAsset()
    : state.category === "encounters"
    ? renderEncounter()
    : state.category === "injuries"
    ? renderInjury()
    : state.category === "campEvents"
        ? renderCampEvent()
    : state.category === "dialogues"
      ? renderDialogue()
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
        : state.category === "npcs"
          ? renderNpc()
        : state.category === "destinations"
          ? renderDestination()
        : state.category === "locations"
          ? renderLocation()
        : state.category === "items"
          ? renderItem()
        : state.category === "combats"
          ? renderCombat()
          : state.category === "enemyDefinitions"
            ? renderEnemy()
            : state.category === "enemyActions"
              ? renderEnemyActionDefinition()
          : state.category === "abilities"
             ? renderAbility()
             : state.category === "combatStatuses"
               ? renderCombatStatus()
             : renderLootTable();
   if (state.navigationHistory.length) $("#editor-root").insertAdjacentHTML("afterbegin", renderNavigationControls());
   injectAssetEditors();
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
    dialogues: clone(state.catalog.dialogues),
    expeditions: clone(state.catalog.expeditions),
    recipes: clone(state.catalog.recipes),
    materials: clone(state.catalog.materials),
    craftingProviders: clone(state.catalog.craftingProviders),
    shops: clone(state.catalog.shops),
    npcs: clone(state.catalog.npcs),
    destinations: clone(state.catalog.destinations),
    locations: clone(state.catalog.locations),
    items: clone(state.catalog.items),
    combats: clone(state.catalog.combats),
    abilities: clone(state.catalog.abilities),
    combatStatuses: clone(state.catalog.combatStatuses),
    enemyDefinitions: clone(state.catalog.enemyDefinitions),
    enemyActions: clone(state.catalog.enemyActions),
    lootTables: clone(state.catalog.lootTables),
  };
  Object.values(snapshot.recipes || {}).forEach((recipe) => {
    if (!recipe || Array.isArray(recipe.ingredients)) return;
    recipe.ingredients = normalizedRecipeIngredients(recipe);
    delete recipe.ingredientType;
  });
  if (state.draft && !["paths", "imageAssets", "audioAssets"].includes(state.category)) {
    const map = snapshot[state.category];
    const draftId = state.draft.id || state.originalSelectedId;
    const draftCopy = clone(state.draft);
    if (state.category === "recipes" && !Array.isArray(draftCopy.ingredients)) {
      draftCopy.ingredients = normalizedRecipeIngredients(draftCopy);
      delete draftCopy.ingredientType;
    }
    if (draftId === state.originalSelectedId || !Object.prototype.hasOwnProperty.call(map, draftId)) {
      delete map[state.originalSelectedId];
      map[draftId] = draftCopy;
    } else {
      // Preserve the collision so the server reports the key/id mismatch
      // instead of silently overwriting an existing authored definition.
      map[state.originalSelectedId] = draftCopy;
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
  if (category === "dialogues") return {
    id: "new_dialogue",
    title: "New Dialogue",
    description: "",
    start: "start",
    nodes: { start: { speakerId: "arthur", text: "", end: true, choices: [] } },
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
  if (category === "abilities") return { id: "new_ability", name: "New Ability", description: "", kind: "active", tags: [], target: "enemy", targetMode: "singleEnemy", effects: [] };
  if (category === "combatStatuses") return {
    id: "new_status",
    name: "New Status",
    description: "",
    periodicDamage: 1,
    durationActivations: 1,
    refreshBehavior: "refresh",
  };
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
  if (category === "npcs") return { id: "new_npc", name: "New NPC", role: "", description: "", dialogue: [], rumors: [], locationIds: [] };
  if (category === "destinations") return { id: "new_destination", name: "New Destination", type: "story", description: "", npcIds: [], actions: [] };
  if (category === "locations") return { id: "new_location", name: "New Location", type: "village", description: "", destinations: [], npcs: [], shops: [], availableExpeditions: [], requirements: [] };
  if (category === "enemyDefinitions") return {
    id: "new_enemy",
    name: "New Enemy",
    maxHp: 10,
    speed: 10,
    defense: 0,
    actionPattern: [Object.keys(state.catalog.enemyActions || {}).sort()[0] || ""],
    traits: [],
  };
  if (category === "enemyActions") return {
    id: "new_enemy_action",
    name: "New Enemy Action",
    damage: { minimum: 1, maximum: 2 },
    target: "arthur",
    telegraphed: false,
  };
  if (category === "recipes") return {
    id: "new_recipe",
    name: "New Recipe",
    description: "",
    craftingProvider: Object.keys(state.catalog.craftingProviders || {})[0] || "",
    ingredients: [{ type: "material", id: Object.keys(state.catalog.materials || {}).sort()[0] || "", quantity: 1 }],
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
  if (["encounters", "campEvents", "dialogues"].includes(state.category)) entry.title = `${entry.title || "Event"} Copy`;
  else if (state.category === "injuries") entry.name = `${entry.name || "Injury"} Copy`;
  else if (state.category === "enemyDefinitions") entry.name = `${entry.name || "Enemy"} Copy`;
  else if (state.category === "enemyActions") entry.name = `${entry.name || "Enemy Action"} Copy`;
  else if (state.category === "shops") entry.displayName = `${entry.displayName || "Shop"} Copy`;
  else if (["items", "abilities"].includes(state.category)) entry.name = `${entry.name || "Entry"} Copy`;
  else if (["expeditions", "recipes", "materials", "craftingProviders", "npcs", "destinations", "locations"].includes(state.category)) entry.name = `${entry.name || "Entry"} Copy`;
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
  const refType = state.category === "shops" ? "shops" : state.category === "items" ? "items" : state.category === "combats" ? "combats" : state.category === "enemyDefinitions" ? "enemies" : state.category === "enemyActions" ? "enemyActions" : state.category === "abilities" ? "abilities" : state.category === "combatStatuses" ? "combatStatuses" : state.category === "injuries" ? "injuries" : state.category === "campEvents" ? "campEvents" : state.category === "dialogues" ? "dialogues" : state.category === "npcs" ? "npcs" : state.category === "destinations" ? "destinations" : state.category === "locations" ? "locations" : state.category === "lootTables" ? "lootTables" : state.category === "expeditions" ? "expeditions" : state.category === "recipes" ? "recipes" : state.category === "materials" ? "materials" : state.category === "craftingProviders" ? "craftingProviders" : "encounters";
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
  if (input.dataset.townHotspotInput) return;
  if (!state.draft) return;
  if (input.dataset.abilityTags !== undefined) {
    state.draft.tags = splitList(input.value);
    markDirty();
    return;
  }
  if (input.dataset.abilityField) {
    const field = input.dataset.abilityField;
    const value = parseInputValue(input, field);
    setAbilityPathValue(field, value);
    markDirty();
    if (field === "kind" || field === "target" || field === "targetMode") render();
    return;
  }
  if (input.dataset.abilityCostField) {
    state.draft.cost ||= {};
    const value = parseInputValue(input, input.dataset.abilityCostField);
    if (value === undefined || value === "") delete state.draft.cost[input.dataset.abilityCostField];
    else state.draft.cost[input.dataset.abilityCostField] = value;
    if (!state.draft.cost.resource && state.draft.cost.amount === undefined) delete state.draft.cost;
    markDirty();
    if (input.dataset.abilityCostField === "resource") render();
    return;
  }
  if (input.dataset.abilityTriggerField) {
    state.draft.trigger ||= { event: "combatStart", effects: [] };
    const value = parseInputValue(input, input.dataset.abilityTriggerField);
    if (value === undefined || value === "") delete state.draft.trigger[input.dataset.abilityTriggerField];
    else state.draft.trigger[input.dataset.abilityTriggerField] = value;
    markDirty();
    if (input.dataset.abilityTriggerField === "event") render();
    return;
  }
  if (input.dataset.abilityEffectField) {
    const path = input.dataset.abilityEffectPath;
    const effect = abilityPathValue(path);
    if (!effect) return;
    const value = parseInputValue(input, input.dataset.abilityEffectField);
    if (value === undefined || value === "") delete effect[input.dataset.abilityEffectField];
    else effect[input.dataset.abilityEffectField] = value;
    markDirty();
    if (input.dataset.abilityEffectField === "type") render();
    return;
  }
  if (input.dataset.abilityConditionField) {
    const path = input.dataset.abilityConditionPath;
    const condition = abilityPathValue(path) || {};
    setAbilityPathValue(path, condition);
    const value = parseInputValue(input, input.dataset.abilityConditionField);
    if (value === undefined || value === "") delete condition[input.dataset.abilityConditionField];
    else condition[input.dataset.abilityConditionField] = value;
    markDirty();
    return;
  }
  if (input.dataset.abilityConditionJson) {
    try {
      const value = JSON.parse(input.value);
      setAbilityPathValue(input.dataset.abilityConditionJson, value);
      markDirty();
      render();
    } catch (error) {
      input.setCustomValidity(`Invalid condition JSON: ${error.message}`);
    }
    return;
  }
  if (input.dataset.linesField) {
    state.draft[input.dataset.linesField] = input.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    markDirty();
    return;
  }
  if (input.dataset.referenceToggleField) {
    state.draft[input.dataset.referenceToggleField] = toggleArray(
      state.draft[input.dataset.referenceToggleField],
      input.dataset.referenceToggleValue,
      input.checked,
    );
    markDirty();
    return;
  }
  if (input.dataset.referenceArrayField) {
    state.draft[input.dataset.referenceArrayField] ||= [];
    state.draft[input.dataset.referenceArrayField][Number(input.dataset.referenceArrayIndex)] = input.value;
    markDirty();
    render();
    return;
  }
  if (input.dataset.stringArrayField) {
    state.draft[input.dataset.stringArrayField] ||= [];
    state.draft[input.dataset.stringArrayField][Number(input.dataset.stringArrayIndex)] = input.value;
    markDirty();
    return;
  }
  if (input.dataset.destinationNpcIndex !== undefined) {
    state.draft.npcIds ||= [];
    state.draft.npcIds[Number(input.dataset.destinationNpcIndex)] = input.value;
    markDirty();
    render();
    return;
  }
  if (input.dataset.destinationActionIndex !== undefined) {
    state.draft.actions ||= [];
    state.draft.actions[Number(input.dataset.destinationActionIndex)] = input.value;
    markDirty();
    return;
  }
  if (input.dataset.dialogueNodeIdField === "id") {
    const oldId = input.dataset.dialogueNodeId;
    const newId = input.value.trim();
    const nodes = state.draft.nodes || {};
    if (!newId || newId === oldId || Object.prototype.hasOwnProperty.call(nodes, newId)) {
      if (newId !== oldId) render();
      return;
    }
    const nextNodes = {};
    Object.entries(nodes).forEach(([id, node]) => { nextNodes[id === oldId ? newId : id] = node; });
    Object.values(nextNodes).forEach((node) => {
      if (node.next === oldId) node.next = newId;
      (node.choices || []).forEach((choice) => { if (choice.next === oldId) choice.next = newId; });
    });
    if (state.draft.start === oldId) state.draft.start = newId;
    state.draft.nodes = nextNodes;
    markDirty();
    render();
    return;
  }
  if (input.dataset.dialogueNodeField) {
    const node = state.draft.nodes?.[input.dataset.dialogueNodeId];
    if (!node) return;
    const value = parseInputValue(input, input.dataset.dialogueNodeField);
    if (value === undefined || value === "") delete node[input.dataset.dialogueNodeField];
    else node[input.dataset.dialogueNodeField] = value;
    markDirty();
    if (input.dataset.dialogueNodeField === "speakerId" || input.dataset.dialogueNodeField === "next") render();
    return;
  }
  if (input.dataset.dialogueChoiceField) {
    const node = state.draft.nodes?.[input.dataset.dialogueNodeId];
    const choice = node?.choices?.[Number(input.dataset.dialogueChoiceIndex)];
    if (!choice) return;
    const value = parseInputValue(input, input.dataset.dialogueChoiceField);
    if (value === undefined || value === "") delete choice[input.dataset.dialogueChoiceField];
    else choice[input.dataset.dialogueChoiceField] = value;
    markDirty();
    if (input.dataset.dialogueChoiceField === "next") render();
    return;
  }
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
    const entries = normalizedRecipeIngredients(state.draft);
    const index = Number(input.dataset.ingredientIndex);
    const current = entries[index];
    if (!current) return;
    state.draft.ingredients = entries;
    delete state.draft.ingredientType;
    if (input.dataset.recipeIngredientField === "type") {
      current.type = input.value === "item" ? "item" : "material";
      const ids = current.type === "item" ? Object.keys(state.catalog.items || {}).sort() : Object.keys(state.catalog.materials || {}).sort();
      if (!ids.includes(current.id)) current.id = ids[0] || "";
      markDirty();
      render();
      return;
    }
    if (input.dataset.recipeIngredientField === "id") current.id = input.value;
    else current.quantity = input.value === "" ? undefined : Number(input.value);
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
    if (input.dataset.combatEnemyField === "id" && state.draft.enemyIds) state.draft.enemyIds[index] = input.value;
    markDirty();
    render();
    return;
  }
  if (input.dataset.enemyTraitStatusToggle) {
    const trait = state.draft.traits?.[Number(input.dataset.enemyTraitIndex)];
    if (!trait) return;
    trait.suppressedByStatuses = toggleArray(trait.suppressedByStatuses, input.dataset.statusId, input.checked);
    markDirty();
    return;
  }
  if (input.dataset.enemyTraitField) {
    const trait = state.draft.traits?.[Number(input.dataset.enemyTraitIndex)];
    if (!trait) return;
    setNested(trait, input.dataset.enemyTraitField, parseInputValue(input, input.dataset.enemyTraitField));
    markDirty();
    return;
  }
  if (input.dataset.enemyActionField) {
    const value = parseInputValue(input, input.dataset.enemyActionField);
    if (state.category === "enemyActions") {
      setNested(state.draft, input.dataset.enemyActionField, value);
    } else {
      const action = state.catalog.enemyActions?.[input.dataset.actionId];
      if (!action) return;
      setNested(action, input.dataset.enemyActionField, value);
    }
    markDirty();
    return;
  }
  if (input.dataset.enemyField) {
    setNested(state.draft, input.dataset.enemyField, parseInputValue(input, input.dataset.enemyField));
    markDirty();
    return;
  }
  if (input.dataset.enemyPatternField) {
    state.draft.actionPattern ||= [];
    state.draft.actionPattern[Number(input.dataset.enemyPatternIndex)] = input.value;
    markDirty();
    render();
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
  if (input.dataset.itemOnHitField) {
    state.draft.effects ||= {};
    state.draft.effects.onHitEffects ||= [];
    const effect = state.draft.effects.onHitEffects[Number(input.dataset.itemOnHitIndex)];
    if (!effect) return;
    const value = parseInputValue(input, input.dataset.itemOnHitField);
    if (value === undefined || value === "") delete effect[input.dataset.itemOnHitField];
    else effect[input.dataset.itemOnHitField] = value;
    markDirty();
    if (input.dataset.itemOnHitField === "type" || input.dataset.itemOnHitField === "statusId") render();
    return;
  }
  if (input.dataset.itemTriggerField) {
    state.draft.effects ||= {};
    state.draft.effects.combatTriggers ||= [];
    const trigger = state.draft.effects.combatTriggers[Number(input.dataset.itemTriggerIndex)];
    if (!trigger) return;
    const value = parseInputValue(input, input.dataset.itemTriggerField);
    if (value === undefined || value === "") delete trigger[input.dataset.itemTriggerField];
    else trigger[input.dataset.itemTriggerField] = value;
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
  if (input.dataset.travelSceneField) {
    const scene = state.draft.travelScenes?.[Number(input.dataset.travelSceneIndex)];
    if (!scene) return;
    const value = parseInputValue(input, input.dataset.travelSceneField);
    if (value === undefined || value === "") delete scene[input.dataset.travelSceneField];
    else scene[input.dataset.travelSceneField] = value;
    markDirty();
    if (input.dataset.travelSceneField === "motion") render();
    return;
  }
  if (input.dataset.outcomeVisualField) {
    handleOutcomeVisualInput(input);
    return;
  }
  if (input.dataset.field) {
    if (input.dataset.field === "ingredientType" && state.category === "recipes") {
      const type = input.value === "item" ? "item" : "material";
      const ids = type === "item" ? Object.keys(state.catalog.items || {}).sort() : Object.keys(state.catalog.materials || {}).sort();
      state.draft.ingredients = normalizedRecipeIngredients(state.draft).map((ingredient) => ({
        ...ingredient,
        type,
        id: ids.includes(ingredient.id) ? ingredient.id : ids[0] || "",
      }));
      state.draft.ingredientType = type;
      markDirty();
      render();
      return;
    }
    const value = input.dataset.field === "combatVisualAssetId" && input.value === ""
      ? null
      : parseInputValue(input, input.dataset.field);
    setNested(state.draft, input.dataset.field, value);
    markDirty();
    if (["category"].includes(input.dataset.field)
      || (state.category === "locations" && ["visualAssetId", "markerStyle"].includes(input.dataset.field))
      || (state.category === "encounters" && input.dataset.field === "visualAssetId")) render();
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
    if (input.dataset.objectField === "type" && ["anyOf", "allOf"].includes(value)) {
      collection[index].requirements ||= [];
    }
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

function suggestClientAssetId(filename, assetType, category, context = "") {
  const stem = filename.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "asset";
  const contextSlug = String(context || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const prefix = category === "portrait" ? "portrait" : category;
  return [prefix, contextSlug, stem].filter(Boolean).join("_").slice(0, 64).replace(/_+$/, "") || (assetType === "audio" ? "audio_asset" : "image_asset");
}

function imageProfileForCategory(category) {
  return { portrait: "portrait", location: "scene", town: "town", expedition: "scene", encounter: "scene", combat: "combat", combat_scene: "scene", ui: "ui" }[category] || "none";
}

function formatAssetBytes(bytes) {
  if (!Number.isFinite(bytes)) return "unknown size";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatAssetImageSummary(processing) {
  const source = processing.source;
  const output = processing.output;
  const title = processing.profile === "none" ? "Original" : `${processing.profileLabel} · Quality 85 · ${processing.cropAnchor[0].toUpperCase()}${processing.cropAnchor.slice(1)} crop`;
  const warnings = (processing.warnings || []).map((warning) => `<div class="warning">Warning: ${escapeHtml(warning)}</div>`).join("");
  return `<div><strong>Source</strong><br>${source.width} × ${source.height} ${escapeHtml(source.format)}<br>${formatAssetBytes(source.bytes)}</div><div><strong>${processing.profile === "none" ? "Output" : "Optimized"}</strong><br>${output.width} × ${output.height} ${escapeHtml(output.format)}<br>${formatAssetBytes(output.bytes)}</div><div>${escapeHtml(title)}</div>${warnings}`;
}

function closeAssetImportDialog() {
  state.pendingAssetUpload = null;
  state.assetPreview = null;
  state.assetPreviewRequest += 1;
  const dialog = $("#asset-import-dialog");
  if (dialog) dialog.hidden = true;
}

function importOptions() {
  const optimize = $("#asset-optimize-toggle")?.checked ?? true;
  return {
    optimize,
    profile: optimize ? $("#asset-optimization-profile")?.value || "none" : "none",
    cropAnchor: $("#asset-crop-anchor")?.value || "center",
  };
}

async function refreshImageImportPreview() {
  const pending = state.pendingAssetUpload;
  if (!pending) return;
  const status = $("#asset-import-status");
  const summary = $("#asset-import-summary");
  const preview = $("#asset-import-preview");
  const parallaxPreview = $("#asset-import-parallax-preview");
  const confirm = $("[data-action='confirm-asset-upload']");
  const profile = $("#asset-optimization-profile");
  const anchor = $("#asset-crop-anchor");
  const options = importOptions();
  if (profile) profile.disabled = !options.optimize;
  if (anchor) anchor.disabled = !options.optimize || options.profile === "none";
  if (confirm) confirm.disabled = true;
  if (status) status.textContent = "Processing preview…";
  if (summary) summary.textContent = "";
  const requestId = ++state.assetPreviewRequest;
  const form = new FormData();
  form.append("assetType", "image");
  form.append("category", pending.target.category);
  form.append("assetId", pending.assetId);
  form.append("optimizeForGame", String(options.optimize));
  form.append("optimizationProfile", options.profile);
  form.append("cropAnchor", options.cropAnchor);
  if (pending.samMaskFile) form.append("samMaskFile", pending.samMaskFile, pending.samMaskFile.name);
  form.append("file", pending.file, pending.file.name);
  try {
    const response = await fetch("/api/assets/preview", { method: "POST", body: form });
    const payload = await response.json();
    if (requestId !== state.assetPreviewRequest || !state.pendingAssetUpload) return;
    if (!response.ok) throw new Error(payload.error || payload.errors?.[0]?.message || "Image preview failed.");
    state.assetPreview = { ...payload, options: { ...options, samMaskFile: pending.samMaskFile } };
    if (preview) preview.src = payload.previewDataUrl;
    if (parallaxPreview) {
      parallaxPreview.hidden = !payload.parallaxPreviewDataUrl;
      if (payload.parallaxPreviewDataUrl) parallaxPreview.src = payload.parallaxPreviewDataUrl;
    }
    if (summary) summary.innerHTML = formatAssetImageSummary(payload.imageProcessing);
    if (status) status.textContent = "Ready to import. The source file remains untouched.";
    if (confirm) confirm.disabled = false;
  } catch (error) {
    if (requestId !== state.assetPreviewRequest) return;
    state.assetPreview = null;
    if (status) status.textContent = error.message;
    if (summary) summary.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  }
}

function openImageImportDialog(file, target, assetId) {
  state.pendingAssetUpload = { file, target, assetId, samMaskFile: null };
  state.assetPreview = null;
  const dialog = $("#asset-import-dialog");
  const filename = $("#asset-import-filename");
  const profile = $("#asset-optimization-profile");
  const anchor = $("#asset-crop-anchor");
  const optimize = $("#asset-optimize-toggle");
  const samMaskControl = $("#asset-sam-mask-control");
  const samMaskInput = $("#asset-sam-mask-input");
  if (filename) filename.textContent = `${target.replace ? "Replace" : "Upload"} · ${assetId} · ${file.name}`;
  if (profile) profile.value = target.optimizationProfile || imageProfileForCategory(target.category);
  if (anchor) anchor.value = "center";
  if (optimize) optimize.checked = true;
  if (samMaskControl) samMaskControl.hidden = target.category !== "expedition";
  if (samMaskInput) samMaskInput.value = "";
  if (dialog) dialog.hidden = false;
  refreshImageImportPreview();
}

async function submitAssetUpload(file, target, assetId, options = {}, samMaskFile = null) {
  const form = new FormData();
  form.append("assetType", target.assetType);
  form.append("category", target.category);
  form.append("assetId", assetId.trim());
  form.append("sourceHash", state.catalog?.sourceHashes?.["js/asset-data.js"] || "");
  if (target.assetType === "image") {
    form.append("optimizeForGame", String(options.optimize ?? true));
    form.append("optimizationProfile", options.profile || "none");
    form.append("cropAnchor", options.cropAnchor || "center");
  }
  if (samMaskFile) form.append("samMaskFile", samMaskFile, samMaskFile.name);
  form.append("file", file, file.name);
  const response = await fetch(target.replace ? "/api/assets/replace" : "/api/assets/upload", { method: "POST", body: form });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || payload.errors?.[0]?.message || "Asset upload failed.");
  state.catalog = payload;
  if (target.field && state.draft) {
    if (target.sceneIndex !== null && target.sceneIndex !== undefined) {
      state.draft.travelScenes ||= [];
      const scene = state.draft.travelScenes[Number(target.sceneIndex)];
      scene[target.field] = payload.assetResult.assetId;
      if (payload.assetResult.parallaxAssetId) scene.travelParallaxAssetId = payload.assetResult.parallaxAssetId;
    } else if (target.nodeId) state.draft.nodes[target.nodeId][target.field] = payload.assetResult.assetId;
    else {
      state.draft[target.field] = payload.assetResult.assetId;
      if (payload.assetResult.parallaxAssetId) state.draft.travelParallaxAssetId = payload.assetResult.parallaxAssetId;
    }
    markDirty();
  } else {
    state.category = target.assetType === "audio" ? "audioAssets" : "imageAssets";
    state.selectedId = payload.assetResult.assetId;
    state.originalSelectedId = state.selectedId;
    state.draft = clone(state.catalog[state.category][state.selectedId]);
    state.dirty = false;
    state.draftDirty = false;
  }
  render();
}

async function uploadSelectedAsset(file) {
  const target = state.uploadTarget;
  state.uploadTarget = null;
  if (!file || !target) return;
  const defaultId = target.assetId || suggestClientAssetId(file.name, target.assetType, target.category, target.context);
  const assetId = target.replace ? defaultId : window.prompt("Asset ID (lowercase slug)", defaultId);
  if (!assetId) return;
  if (target.assetType === "image") {
    openImageImportDialog(file, target, assetId.trim());
    return;
  }
  try {
    await submitAssetUpload(file, target, assetId);
  } catch (error) {
    window.alert(error.message);
  }
}

function handleAction(button) {
  const action = button.dataset.action;
  if (action === "cancel-asset-upload") {
    closeAssetImportDialog();
  } else if (action === "confirm-asset-upload") {
    const pending = state.pendingAssetUpload;
    const preview = state.assetPreview;
    if (!pending || !preview) return;
    button.disabled = true;
    submitAssetUpload(pending.file, pending.target, pending.assetId, preview.options, pending.samMaskFile)
      .then(() => closeAssetImportDialog())
      .catch((error) => {
        button.disabled = false;
        const status = $("#asset-import-status");
        if (status) status.textContent = error.message;
      });
  } else if (action === "upload-asset" || action === "replace-asset") {
    if (action === "replace-asset" && !window.confirm("Replace this file while keeping the same stable asset ID? A recovery backup will be created.")) return;
    state.uploadTarget = {
      assetType: button.dataset.assetType,
      category: button.dataset.assetBrowser === "true" ? $("#asset-browser-category")?.value || button.dataset.assetCategory : button.dataset.assetCategory,
      field: button.dataset.assetField || null,
      nodeId: button.dataset.assetNodeId || null,
      sceneIndex: button.dataset.assetSceneIndex ?? null,
      assetId: button.dataset.assetId || null,
      replace: action === "replace-asset",
      context: button.dataset.assetContext || state.draft?.name || state.draft?.id || "asset",
      optimizationProfile: button.dataset.assetProfile || imageProfileForCategory(button.dataset.assetCategory),
    };
    const input = $("#asset-upload-input");
    if (input) {
      input.value = "";
      input.click();
    }
  } else if (action === "add-travel-scene") {
    state.draft.travelScenes ||= [];
    const lastDistance = Number(state.draft.travelScenes.at(-1)?.minDistance);
    state.draft.travelScenes.push({
      minDistance: Number.isFinite(lastDistance) ? lastDistance + 1 : 0,
      visualAssetId: Object.keys(state.catalog?.imageAssets || {})
        .filter((id) => state.catalog.imageAssets[id]?.category === "expedition")
        .sort()[0] || "",
      motion: "loop",
    });
    markDirty();
    render();
  } else if (action === "remove-travel-scene") {
    state.draft.travelScenes?.splice(Number(button.dataset.travelSceneIndex), 1);
    markDirty();
    render();
  } else if (action === "add-dialogue-node") {
    state.draft.nodes ||= {};
    const id = uniqueId("new_node", state.draft.nodes);
    state.draft.nodes[id] = { speakerId: "arthur", text: "", end: true, choices: [] };
    if (!state.draft.start) state.draft.start = id;
    markDirty();
    render();
  } else if (action === "remove-dialogue-node") {
    const nodeId = button.dataset.dialogueNodeId;
    if (Object.keys(state.draft.nodes || {}).length <= 1) return window.alert("A dialogue needs at least one node.");
    delete state.draft.nodes[nodeId];
    Object.values(state.draft.nodes).forEach((node) => {
      if (node.next === nodeId) delete node.next;
      (node.choices || []).forEach((choice) => { if (choice.next === nodeId) delete choice.next; });
    });
    if (state.draft.start === nodeId) state.draft.start = Object.keys(state.draft.nodes)[0];
    markDirty();
    render();
  } else if (action === "add-dialogue-choice") {
    const node = state.draft.nodes?.[button.dataset.dialogueNodeId];
    if (!node) return;
    node.choices ||= [];
    node.choices.push({ id: uniqueId("new_choice", Object.fromEntries(node.choices.map((choice) => [choice.id, true]))), label: "New choice", end: true, requirements: [], effects: [] });
    markDirty();
    render();
  } else if (action === "remove-dialogue-choice") {
    const node = state.draft.nodes?.[button.dataset.dialogueNodeId];
    if (!node?.choices) return;
    node.choices.splice(Number(button.dataset.dialogueChoiceIndex), 1);
    markDirty();
    render();
  } else if (action === "move-dialogue-choice") {
    const node = state.draft.nodes?.[button.dataset.dialogueNodeId];
    const index = Number(button.dataset.dialogueChoiceIndex);
    const nextIndex = button.dataset.direction === "up" ? index - 1 : index + 1;
    if (!node?.choices || nextIndex < 0 || nextIndex >= node.choices.length) return;
    [node.choices[index], node.choices[nextIndex]] = [node.choices[nextIndex], node.choices[index]];
    markDirty();
    render();
  } else if (action === "add-reference-array") {
    const field = button.dataset.referenceArrayField;
    const category = button.dataset.referenceArrayCategory;
    const first = Object.keys(state.catalog?.[category] || {}).sort()[0];
    if (!first) return window.alert(`No ${category} definitions are available.`);
    state.draft[field] ||= [];
    state.draft[field].push(first);
    markDirty();
    render();
  } else if (action === "remove-reference-array") {
    state.draft[button.dataset.referenceArrayField]?.splice(Number(button.dataset.referenceArrayIndex), 1);
    markDirty();
    render();
  } else if (action === "add-string-array") {
    state.draft[button.dataset.stringArrayField] ||= [];
    state.draft[button.dataset.stringArrayField].push("");
    markDirty();
    render();
  } else if (action === "remove-string-array") {
    state.draft[button.dataset.stringArrayField]?.splice(Number(button.dataset.stringArrayIndex), 1);
    markDirty();
    render();
  } else if (action === "add-destination-npc") {
    const first = Object.keys(state.catalog.npcs || {}).sort()[0];
    if (!first) return window.alert("No NPC definitions are available.");
    state.draft.npcIds ||= [];
    state.draft.npcIds.push(first);
    markDirty();
    render();
  } else if (action === "remove-destination-npc") {
    state.draft.npcIds?.splice(Number(button.dataset.destinationNpcIndex), 1);
    markDirty();
    render();
  } else if (action === "add-destination-action") {
    state.draft.actions ||= [];
    state.draft.actions.push("talk");
    markDirty();
    render();
  } else if (action === "remove-destination-action") {
    state.draft.actions?.splice(Number(button.dataset.destinationActionIndex), 1);
    markDirty();
    render();
  } else if (action === "toggle-filters") {
    state.filterOpen = !state.filterOpen;
    renderEntryPaneOnly();
  } else if (action === "clear-filters") {
    if (state.filters[state.category]) {
      state.filters[state.category] = state.category === "items"
        ? { category: "", rarity: "", equippable: "any", equipmentSlot: "", carriable: "any", consumable: "any", questItem: "any", campaignItem: "any", unique: "any", sellable: "any", protected: "any", tags: [], tagMode: "all" }
        : state.category === "encounters"
          ? { pathIds: [], regionIds: [], direction: "all", minDistance: "", maxDistance: "", repeatable: "any", tags: [], tagMode: "all", combat: "any", hasRequirements: "any" }
          : { kind: "", resource: "", tags: [], tagMode: "all" };
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
  } else if (action === "add-ability-effect") {
    const path = button.dataset.abilityEffectsPath;
    let collection = abilityPathValue(path);
    if (!Array.isArray(collection)) {
      collection = [];
      setAbilityPathValue(path, collection);
    }
    collection.push({ type: "dealDamage", amount: 1 });
    markDirty();
    render();
  } else if (action === "remove-ability-effect") {
    const collection = abilityPathValue(button.dataset.abilityEffectsPath);
    if (!Array.isArray(collection)) return;
    collection.splice(Number(button.dataset.abilityEffectIndex), 1);
    markDirty();
    render();
  } else if (action === "move-ability-effect") {
    const collection = abilityPathValue(button.dataset.abilityEffectsPath);
    const index = Number(button.dataset.abilityEffectIndex);
    const nextIndex = button.dataset.direction === "up" ? index - 1 : index + 1;
    if (!Array.isArray(collection) || nextIndex < 0 || nextIndex >= collection.length) return;
    [collection[index], collection[nextIndex]] = [collection[nextIndex], collection[index]];
    markDirty();
    render();
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
    const ingredients = normalizedRecipeIngredients(recipe);
    const type = "material";
    const candidates = Object.keys(state.catalog.materials || {}).sort();
    const ingredientId = candidates.find((id) => !ingredients.some((entry) => entry.type === type && entry.id === id));
    if (!ingredientId) return window.alert("No unused material references are available.");
    recipe.ingredients = ingredients;
    delete recipe.ingredientType;
    recipe.ingredients.push({ type, id: ingredientId, quantity: 1 });
    markDirty();
    render();
  } else if (action === "duplicate-recipe-ingredient") {
    const recipe = state.draft;
    const entries = normalizedRecipeIngredients(recipe);
    const source = entries[Number(button.dataset.ingredientIndex)];
    if (!source) return;
    const candidates = source.type === "item" ? Object.keys(state.catalog.items || {}).sort() : Object.keys(state.catalog.materials || {}).sort();
    const ingredientId = candidates.find((id) => !entries.some((entry) => entry.type === source.type && entry.id === id));
    if (!ingredientId) return window.alert("No unused ingredient references are available.");
    recipe.ingredients = entries;
    delete recipe.ingredientType;
    recipe.ingredients.splice(Number(button.dataset.ingredientIndex) + 1, 0, { ...source, id: ingredientId });
    markDirty();
    render();
  } else if (action === "remove-recipe-ingredient") {
    const entries = normalizedRecipeIngredients(state.draft);
    if (!entries[Number(button.dataset.ingredientIndex)]) return;
    state.draft.ingredients = entries;
    delete state.draft.ingredientType;
    state.draft.ingredients.splice(Number(button.dataset.ingredientIndex), 1);
    markDirty();
    render();
  } else if (action === "move-recipe-ingredient") {
    const entries = normalizedRecipeIngredients(state.draft);
    const index = Number(button.dataset.ingredientIndex);
    const nextIndex = button.dataset.direction === "up" ? index - 1 : index + 1;
    if (nextIndex < 0 || nextIndex >= entries.length) return;
    [entries[index], entries[nextIndex]] = [entries[nextIndex], entries[index]];
    state.draft.ingredients = entries;
    delete state.draft.ingredientType;
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
  } else if (action === "move-combat-enemy") {
    const index = Number(button.dataset.enemyIndex);
    const nextIndex = button.dataset.direction === "up" ? index - 1 : index + 1;
    if (!state.draft.enemyIds || nextIndex < 0 || nextIndex >= state.draft.enemyIds.length) return;
    [state.draft.enemyIds[index], state.draft.enemyIds[nextIndex]] = [state.draft.enemyIds[nextIndex], state.draft.enemyIds[index]];
    markDirty();
    render();
  } else if (action === "add-enemy-action-pattern") {
    const actionId = Object.keys(state.catalog.enemyActions || {}).sort()[0];
    if (!actionId) return window.alert("No enemy actions are available.");
    state.draft.actionPattern ||= [];
    state.draft.actionPattern.push(actionId);
    markDirty();
    render();
  } else if (action === "add-enemy-trait") {
    state.draft.traits ||= [];
    state.draft.traits.push({ type: "regeneration", amount: 1, trigger: "activation", suppressedByStatuses: [] });
    markDirty();
    render();
  } else if (action === "remove-enemy-trait") {
    state.draft.traits?.splice(Number(button.dataset.enemyTraitIndex), 1);
    markDirty();
    render();
  } else if (action === "move-enemy-action") {
    const index = Number(button.dataset.enemyPatternIndex);
    const nextIndex = button.dataset.direction === "up" ? index - 1 : index + 1;
    if (!state.draft.actionPattern || nextIndex < 0 || nextIndex >= state.draft.actionPattern.length) return;
    [state.draft.actionPattern[index], state.draft.actionPattern[nextIndex]] = [state.draft.actionPattern[nextIndex], state.draft.actionPattern[index]];
    markDirty();
    render();
  } else if (action === "remove-enemy-action-pattern") {
    if (!state.draft.actionPattern) return;
    state.draft.actionPattern.splice(Number(button.dataset.enemyPatternIndex), 1);
    markDirty();
    render();
  } else if (action === "remove-enemy") {
    state.draft.enemyIds.splice(Number(button.dataset.enemyIndex), 1);
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
  } else if (action === "add-item-on-hit") {
    const statusId = state.catalog.known?.combatStatuses?.[0] || Object.keys(state.catalog.combatStatuses || {}).sort()[0];
    if (!statusId) return window.alert("No combat status definitions are available.");
    state.draft.effects ||= {};
    state.draft.effects.onHitEffects ||= [];
    state.draft.effects.onHitEffects.push({ type: "applyStatus", statusId, chance: 0.2 });
    markDirty();
    render();
  } else if (action === "remove-item-on-hit") {
    state.draft.effects?.onHitEffects?.splice(Number(button.dataset.itemOnHitIndex), 1);
    markDirty();
    render();
  } else if (action === "add-item-trigger") {
    state.draft.effects ||= {};
    state.draft.effects.combatTriggers ||= [];
    state.draft.effects.combatTriggers.push({
      trigger: "defendDamagePrevented",
      effect: "storeCharge",
      chargeId: "resolve",
      cap: 10,
    });
    markDirty();
    render();
  } else if (action === "remove-item-trigger") {
    state.draft.effects?.combatTriggers?.splice(Number(button.dataset.itemTriggerIndex), 1);
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
    const payload = await response.json();
    const migrated = migrateLegacyOutcomeVisuals(payload);
    state.catalog = payload;
    state.validation = state.catalog.validation;
    const ids = Object.keys(state.catalog.encounters || {});
    state.category = "encounters";
    state.selectedId = ids[0] || null;
    state.originalSelectedId = state.selectedId;
    state.draft = state.selectedId ? clone(state.catalog.encounters[state.selectedId]) : null;
    state.dirty = migrated;
    state.draftDirty = migrated;
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
    window.alert(updates.length ? `Saved ${updates.map((result) => result.file).join(" and ")}. A recovery backup was kept by the editor.` : "No file changes were necessary.");
  } catch (error) {
    state.validationPending = false;
    state.validation = { errors: [{ severity: "error", source: "save", message: error.message }], warnings: [] };
    renderValidation();
  }
}

function migrateLegacyOutcomeVisuals(catalog) {
  let changed = false;
  const migrateParent = (parent) => {
    if (!parent || typeof parent !== "object") return;
    const collections = ["outcomes", "effects", "elseEffects"];
    const entries = collections.flatMap((key) => Array.isArray(parent[key]) ? parent[key] : []);
    const legacy = entries.find((entry) => entry && typeof entry === "object" && entry.outcomeVisual)?.outcomeVisual;
    if (!parent.visualOverride && legacy && typeof legacy === "object") {
      parent.visualOverride = clone(legacy);
      changed = true;
    }
    entries.forEach((entry) => {
      if (!entry || typeof entry !== "object") return;
      if (entry.outcomeVisual) {
        delete entry.outcomeVisual;
        changed = true;
      }
      ["victory", "fled", "secondaryOutcome"].forEach((branchKey) => {
        if (entry[branchKey] && typeof entry[branchKey] === "object") migrateParent(entry[branchKey]);
      });
    });
  };
  ["encounters", "campEvents"].forEach((category) => {
    Object.values(catalog?.[category] || {}).forEach((definition) => {
      Object.values(definition?.stages || {}).forEach((stage) => {
        migrateParent(stage);
        (stage.choices || []).forEach((choice) => {
          migrateParent(choice);
          (choice.branches || []).forEach((branch) => migrateParent(branch));
        });
      });
    });
  });
  return changed;
}

function commitTownLayoutInput(input) {
  const destination = state.catalog?.destinations?.[input.dataset.townDestinationId];
  if (!destination) return;
  const hotspot = townLayoutHotspot(destination);
  hotspot[input.dataset.townHotspotAxis] = clampTownLayoutValue(input.value, hotspot[input.dataset.townHotspotAxis]);
  updateTownLayoutMarker(destination.id, hotspot.x, hotspot.y);
  markDirty();
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (button) handleAction(button);
});
document.addEventListener("pointerdown", (event) => {
  const marker = event.target.closest?.("[data-outcome-layout-marker]");
  if (!marker) return;
  const stage = marker.closest("[data-outcome-layout-stage]");
  const outcomePath = marker.dataset.outcomeLayoutPath;
  const slotId = marker.dataset.outcomeLayoutSlot;
  if (!stage || !outcomePath || !ENCOUNTER_LAYOUT_FALLBACKS[slotId]) return;
  event.preventDefault();
  state.outcomeLayoutDrag = { marker, stage, outcomePath, slotId, pointerId: event.pointerId };
  marker.setPointerCapture?.(event.pointerId);
  const position = outcomeLayoutPositionFromPointer(stage, event);
  updateOutcomeLayoutMarker(outcomePath, slotId, position.x, position.y);
});
document.addEventListener("pointermove", (event) => {
  const drag = state.outcomeLayoutDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  event.preventDefault();
  const position = outcomeLayoutPositionFromPointer(drag.stage, event);
  updateOutcomeLayoutMarker(drag.outcomePath, drag.slotId, position.x, position.y);
});
document.addEventListener("pointerup", (event) => {
  if (state.outcomeLayoutDrag?.pointerId === event.pointerId) finishOutcomeLayoutDrag();
});
document.addEventListener("pointercancel", (event) => {
  if (state.outcomeLayoutDrag?.pointerId === event.pointerId) finishOutcomeLayoutDrag();
});
document.addEventListener("pointerdown", (event) => {
  const marker = event.target.closest?.("[data-encounter-layout-marker]");
  if (!marker) return;
  const stage = marker.closest("[data-encounter-layout-stage]");
  const slotId = marker.dataset.encounterLayoutSlot;
  if (!stage || !ENCOUNTER_LAYOUT_FALLBACKS[slotId]) return;
  event.preventDefault();
  state.encounterLayoutDrag = { marker, stage, slotId, pointerId: event.pointerId };
  marker.setPointerCapture?.(event.pointerId);
  const position = encounterLayoutPositionFromPointer(stage, event);
  updateEncounterLayoutMarker(slotId, position.x, position.y);
});
document.addEventListener("pointermove", (event) => {
  const drag = state.encounterLayoutDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  event.preventDefault();
  const position = encounterLayoutPositionFromPointer(drag.stage, event);
  updateEncounterLayoutMarker(drag.slotId, position.x, position.y);
});
document.addEventListener("pointerup", (event) => {
  if (state.encounterLayoutDrag?.pointerId === event.pointerId) finishEncounterLayoutDrag();
});
document.addEventListener("pointercancel", (event) => {
  if (state.encounterLayoutDrag?.pointerId === event.pointerId) finishEncounterLayoutDrag();
});
document.addEventListener("pointerdown", (event) => {
  const marker = event.target.closest?.("[data-town-layout-marker]");
  if (!marker) return;
  const stage = marker.closest("[data-town-layout-stage]");
  const destinationId = marker.dataset.townDestinationId;
  if (!stage || !destinationId) return;
  event.preventDefault();
  state.townLayoutDrag = { marker, stage, destinationId, pointerId: event.pointerId };
  marker.setPointerCapture?.(event.pointerId);
  const position = townLayoutPosition(stage, event);
  updateTownLayoutMarker(destinationId, position.x, position.y);
});
document.addEventListener("pointermove", (event) => {
  const drag = state.townLayoutDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  event.preventDefault();
  const position = townLayoutPosition(drag.stage, event);
  updateTownLayoutMarker(drag.destinationId, position.x, position.y);
});
document.addEventListener("pointerup", (event) => {
  if (state.townLayoutDrag?.pointerId === event.pointerId) finishTownLayoutDrag();
});
document.addEventListener("pointercancel", (event) => {
  if (state.townLayoutDrag?.pointerId === event.pointerId) finishTownLayoutDrag();
});
document.addEventListener("input", (event) => {
  if (!event.target.matches("[data-town-hotspot-input]")) handleInput(event.target);
});
document.addEventListener("change", (event) => {
  if (event.target.matches("#asset-upload-input")) uploadSelectedAsset(event.target.files?.[0]);
  else if (event.target.matches("#asset-sam-mask-input")) {
    if (state.pendingAssetUpload) state.pendingAssetUpload.samMaskFile = event.target.files?.[0] || null;
    refreshImageImportPreview();
  }
  else if (event.target.matches("#asset-optimize-toggle, #asset-optimization-profile, #asset-crop-anchor")) refreshImageImportPreview();
  else if (event.target.matches("[data-outcome-layout-input]")) commitOutcomeLayoutInput(event.target);
  else if (event.target.matches("[data-encounter-layout-input]")) commitEncounterLayoutInput(event.target);
  else if (event.target.matches("[data-town-hotspot-input]")) commitTownLayoutInput(event.target);
  else if (event.target.matches("textarea[data-object-json]")) handleObjectJson(event.target);
  else if (event.target.matches("textarea[data-dialogue-choice-json]")) {
    try {
      const node = state.draft.nodes?.[event.target.dataset.dialogueNodeId];
      const choice = node?.choices?.[Number(event.target.dataset.dialogueChoiceIndex)];
      const parsed = JSON.parse(event.target.value);
      if (!choice || !parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Choice JSON must be an object");
      node.choices[Number(event.target.dataset.dialogueChoiceIndex)] = parsed;
      markDirty();
      render();
    } catch (error) { window.alert(`Could not apply choice JSON: ${error.message}`); }
  }
  else handleInput(event.target);
});
$("#entry-search").addEventListener("input", (event) => { setCurrentSearch(event.target.value); renderEntryPaneOnly(); });
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });

loadCatalog();
