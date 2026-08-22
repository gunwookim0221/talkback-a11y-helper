const test = require('node:test');
const assert = require('node:assert/strict');

const { projectTalkBackReadiness } = require('../.test-dist/readiness.js');

function device(talkback_enabled) {
  return { talkback_enabled };
}

test('idle null run status does not hide a ready single device', () => {
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [device(true)],
      deviceReadinessLoaded: true,
      runScopedState: null,
    }),
    'enabled',
  );
});

test('a single explicit false device projects Disabled', () => {
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [device(false)],
      deviceReadinessLoaded: true,
      runScopedState: null,
    }),
    'disabled',
  );
});

test('a missing device readiness value projects Unknown', () => {
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [{}],
      deviceReadinessLoaded: true,
      runScopedState: null,
    }),
    'unknown',
  );
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [device(null)],
      deviceReadinessLoaded: true,
      runScopedState: null,
    }),
    'unknown',
  );
});

test('selected devices aggregate conservatively across true, false, and unknown', () => {
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [device(true), device(true)],
      deviceReadinessLoaded: true,
      runScopedState: null,
    }),
    'enabled',
  );
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [device(true), device(false)],
      deviceReadinessLoaded: true,
      runScopedState: null,
    }),
    'disabled',
  );
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [device(true), device(null)],
      deviceReadinessLoaded: true,
      runScopedState: 'enabled',
    }),
    'unknown',
  );
});

test('run-scoped state is only an initial fallback while device readiness is unavailable', () => {
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [],
      deviceReadinessLoaded: false,
      runScopedState: 'enabled',
    }),
    'enabled',
  );
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [device(true)],
      deviceReadinessLoaded: true,
      runScopedState: 'disabled',
    }),
    'enabled',
  );
  assert.equal(
    projectTalkBackReadiness({
      selectedDevices: [],
      deviceReadinessLoaded: true,
      runScopedState: 'enabled',
    }),
    'unknown',
  );
});
