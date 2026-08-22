const test = require('node:test');
const assert = require('node:assert/strict');

const {
  TerminalNotificationTracker,
  shouldNotifyTerminalRefresh,
} = require('../.test-dist/terminalNotification.js');

const MOUNTED_AT = Date.parse('2026-08-22T19:00:00Z');

function observation(overrides = {}) {
  return {
    previousState: null,
    currentState: 'finished',
    previousIdentity: null,
    currentIdentity: 'batch:batch_20260822_192125',
    startedAt: '2026-08-22T19:21:25Z',
    finishedAt: '2026-08-22T19:31:33Z',
    ...overrides,
  };
}

test('running to finished notifies once for the same run identity', () => {
  const tracker = new TerminalNotificationTracker(MOUNTED_AT);
  assert.equal(tracker.shouldNotify(observation({
    previousState: 'running',
    previousIdentity: 'batch:batch_20260822_192125',
  })), true);
  assert.equal(tracker.shouldNotify(observation({
    previousState: 'finished',
    previousIdentity: 'batch:batch_20260822_192125',
  })), false);
});

test('first observed terminal state for a newly started run notifies once', () => {
  const tracker = new TerminalNotificationTracker(MOUNTED_AT);
  assert.equal(tracker.shouldNotify(observation()), true);
  assert.equal(tracker.shouldNotify(observation()), false);
});

test('old terminal state on page load does not create a refresh storm', () => {
  const tracker = new TerminalNotificationTracker(MOUNTED_AT);
  const old = observation({
    currentIdentity: 'run:old-history',
    startedAt: '2026-08-22T16:31:19Z',
    finishedAt: '2026-08-22T16:31:19Z',
  });
  assert.equal(tracker.shouldNotify(old), false);
  assert.equal(tracker.shouldNotify(old), false);
});

test('stopped and error terminal transitions retain existing notification behavior', () => {
  for (const state of ['stopped', 'error']) {
    assert.equal(shouldNotifyTerminalRefresh(observation({
      previousState: 'running',
      previousIdentity: 'run:active',
      currentIdentity: 'run:active',
      currentState: state,
    })), true);
  }
});

test('idle and repeated terminal snapshots do not notify', () => {
  const tracker = new TerminalNotificationTracker(MOUNTED_AT);
  assert.equal(tracker.shouldNotify(observation({ currentState: 'idle' })), false);
  assert.equal(tracker.shouldNotify(observation()), true);
  assert.equal(tracker.shouldNotify(observation({ currentState: 'idle' })), false);
  assert.equal(tracker.shouldNotify(observation()), false);
});
