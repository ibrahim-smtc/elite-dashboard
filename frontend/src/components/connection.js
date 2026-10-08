/**
 * What state the live connection is actually in, in one place.
 *
 * The rail and the footer both report the connection, and each used to read
 * the raw state for itself. That is how they came to disagree: the footer said
 * "Drawn live" in every state but "down", and the rail painted every state -
 * reconnecting, offline, snapshot - in the same healthy green, with the dot
 * pulsing through all of them. Two readers of one fact, both wrong in
 * different ways. Now there is one reader, and both surfaces ask it.
 *
 * liveEvents emits six (state, text) pairs. One of them is contradictory: a
 * failed connection on a serverless host arrives as state "live" with the text
 * "snapshot". The text wins there, because the text is the true part.
 */

export function connection(liveStatus = {}) {
  const { state, text = '' } = liveStatus;
  if (state === 'snapshot' || text === 'snapshot') return 'snapshot';
  if (state === 'live') return 'live';
  // "offline" is the browser failing to open the stream at all, and nothing
  // retries it - so it is not reconnecting, and saying so would be a lie.
  if (state === 'down') return text === 'offline' ? 'offline' : 'down';
  return 'connecting';
}

/* A change just landed. liveEvents flags it by setting the text to
   "updated · N tables" for a couple of seconds, which is the one moment the
   indicator has news - and the only moment it should move. */
export function justUpdated(liveStatus = {}) {
  return liveStatus.state === 'live' && String(liveStatus.text || '').startsWith('updated');
}

/* `tone` is what the dot means, and nothing else on the indicator is
   coloured: good when live, warning when the figures may be going stale, and
   plain ink when the sheet is static by design rather than by failure. */
export const CONNECTION = {
  live:       { label: 'Live',         stamp: 'updated',      tone: 'good' },
  down:       { label: 'Reconnecting', stamp: 'last updated', tone: 'warning' },
  offline:    { label: 'Offline',      stamp: 'last updated', tone: 'warning' },
  snapshot:   { label: 'Snapshot',     stamp: 'as of',        tone: 'quiet' },
  connecting: { label: 'Connecting',   stamp: null,           tone: 'quiet' },
};
