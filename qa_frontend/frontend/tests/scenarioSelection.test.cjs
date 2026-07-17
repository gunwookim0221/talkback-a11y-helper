const test = require('node:test');
const assert = require('node:assert/strict');

const { applyPresetSelection } = require('../.test-dist/presets.js');
const { getNavigationName } = require('../.test-dist/utils/navigationMeta.js');
const { groupScenarios } = require('../.test-dist/utils/scenarioGrouping.js');
const {
  RUN_PROFILES,
  currentLanguageLabel,
  getValidationReadiness,
  resolveRunProfile,
} = require('../.test-dist/runProfiles.js');

const scenarios = [
  { id: 'home_main', enabled: true, max_steps: null },
  { id: 'home_safe_plugin', enabled: false, max_steps: 30 },
  { id: 'devices_main', enabled: true, max_steps: null },
  { id: 'life_main', enabled: true, max_steps: null },
  { id: 'routines_main', enabled: true, max_steps: null },
  { id: 'menu_main', enabled: true, max_steps: null },
  { id: 'global_nav_main', enabled: true, max_steps: null },
  { id: 'life_food_plugin', enabled: true, max_steps: null },
  { id: 'device_cleaning_mode_plugin', enabled: true, max_steps: null },
];

function scenarioIdsForGroup(title) {
  return groupScenarios(scenarios).find((group) => group.title === title)?.scenarios.map((scenario) => scenario.id) ?? [];
}

test('routines_main and menu_main are grouped under Navigation', () => {
  const navigationIds = scenarioIdsForGroup('Navigation');

  assert.ok(navigationIds.includes('routines_main'));
  assert.ok(navigationIds.includes('menu_main'));
});

test('life_main is grouped under Navigation', () => {
  const navigationIds = scenarioIdsForGroup('Navigation');
  const lifePluginIds = scenarioIdsForGroup('Life Plugins');

  assert.ok(navigationIds.includes('life_main'));
  assert.ok(!lifePluginIds.includes('life_main'));
});

test('home_safe_plugin stays under Navigation and has Safe display name', () => {
  const navigationIds = scenarioIdsForGroup('Navigation');
  const lifePluginIds = scenarioIdsForGroup('Life Plugins');
  const devicePluginIds = scenarioIdsForGroup('Device Plugins');

  assert.ok(navigationIds.includes('home_safe_plugin'));
  assert.ok(!lifePluginIds.includes('home_safe_plugin'));
  assert.ok(!devicePluginIds.includes('home_safe_plugin'));
  assert.equal(getNavigationName('home_safe_plugin'), 'Safe');
});

test('life plugins remain in Life Plugins', () => {
  const lifePluginIds = scenarioIdsForGroup('Life Plugins');

  assert.ok(lifePluginIds.includes('life_food_plugin'));
});

test('navigation preset includes the five bottom tabs plus global navigation', () => {
  const selected = applyPresetSelection('global', scenarios, new Set());

  assert.deepEqual(
    [...selected].sort(),
    ['devices_main', 'global_nav_main', 'home_main', 'life_main', 'menu_main', 'routines_main'].sort(),
  );
});

test('navigation labels include routines and menu', () => {
  assert.equal(getNavigationName('routines_main'), 'Routines');
  assert.equal(getNavigationName('menu_main'), 'Menu');
});

test('Full Validation profile is the approval-oriented default contract', () => {
  assert.deepEqual(RUN_PROFILES['full-validation'], {
    launchMode: 'clean',
    plannedMode: 'full',
    enableCoverageProbe: true,
    shadowValidation: false,
    evidenceLedger: true,
    identityShadowV2: true,
    traversalIdentityV2: true,
    traversalProfiler: true,
  });
});

test('Quick Smoke retains diagnostics but is not validation ready', () => {
  const profile = RUN_PROFILES['quick-smoke'];
  const readiness = getValidationReadiness({
    ...profile,
    selectedScenarioCount: 32,
    registryScenarioCount: 32,
  });

  assert.equal(profile.launchMode, 'clean');
  assert.equal(profile.enableCoverageProbe, false);
  assert.equal(profile.shadowValidation, false);
  assert.equal(readiness.ready, false);
  assert.deepEqual(readiness.reasons, ['Mode is Smoke', 'Coverage disabled']);
});

test('Custom / Debug preserves the current option combination', () => {
  const current = {
    ...RUN_PROFILES['quick-smoke'],
    launchMode: 'warm',
    enableCoverageProbe: true,
    traversalProfiler: false,
  };

  assert.equal(resolveRunProfile('custom-debug', current), current);
});

test('readiness reports only candidate-impacting missing inputs', () => {
  const readiness = getValidationReadiness({
    ...RUN_PROFILES['full-validation'],
    selectedScenarioCount: 31,
    registryScenarioCount: 32,
    traversalProfiler: false,
    identityShadowV2: false,
  });

  assert.equal(readiness.ready, false);
  assert.deepEqual(readiness.reasons, [
    'Full scenario set not selected',
    'Runtime Profiler disabled',
    'Identity disabled',
  ]);
  assert.equal(
    getValidationReadiness({
      ...RUN_PROFILES['full-validation'],
      selectedScenarioCount: 32,
      registryScenarioCount: 32,
    }).ready,
    true,
  );
});

test('Current language label includes an effective locale when available', () => {
  assert.equal(currentLanguageLabel('ko-KR'), 'Current (ko-KR)');
  assert.equal(currentLanguageLabel('en-US'), 'Current (en-US)');
  assert.equal(currentLanguageLabel(null), 'Current');
});
