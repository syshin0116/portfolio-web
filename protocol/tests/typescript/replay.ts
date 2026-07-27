import type { Event } from "./protocol.js";
import {
  aegra_raw_events,
  aegra_translation_pairs,
  commands,
  command_responses,
  events,
  normalized_events,
  stream_requests,
  type AegraRawInputRequestedEvent,
} from "./fixture-contract.js";

function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

function normalizeAegraInput(raw: AegraRawInputRequestedEvent): Event {
  const { value, ...rest } = raw.params.data;
  return {
    ...raw,
    params: { ...raw.params, data: { ...rest, payload: value } },
  };
}

invariant(stream_requests.length === 5, "expected five stream requests");
invariant(commands.length === 5, "expected five commands");
invariant(command_responses.length === 5, "expected five command responses");
invariant(events.length === 35, "expected thirty-five native events");
invariant(normalized_events.length === 1, "expected one normalized event");
invariant(aegra_raw_events.length === 1, "expected one raw Aegra event");
invariant(
  aegra_translation_pairs.length === 1,
  "expected one Aegra translation pair",
);

const recordCount =
  stream_requests.length +
  commands.length +
  command_responses.length +
  events.length +
  normalized_events.length +
  aegra_raw_events.length;
invariant(recordCount === 52, "expected all fifty-two fixture records");

for (const pair of aegra_translation_pairs) {
  const normalized = normalizeAegraInput(pair.raw);
  invariant(
    JSON.stringify(normalized) === JSON.stringify(pair.normalized),
    `Aegra value-to-payload translation drifted: ${pair.translation_id}`,
  );
}

const typedEvents: readonly Event[] = [...events, ...normalized_events];
const ids = new Set<string>();
const shapes = new Set<string>();
for (const event of typedEvents) {
  invariant(event.type === "event", "not an event envelope");
  invariant(
    typeof event.event_id === "string" && event.event_id.length > 0,
    "missing event id",
  );
  invariant(!ids.has(event.event_id), `duplicate event id: ${event.event_id}`);
  ids.add(event.event_id);
  const data = event.params.data as { event?: string };
  shapes.add(`${event.method}:${data.event ?? "<none>"}`);
}

const expectedShapes = [
  "input.requested:<none>",
  "lifecycle:completed",
  "lifecycle:running",
  "lifecycle:started",
  "messages:content-block-delta",
  "messages:content-block-finish",
  "messages:content-block-start",
  "messages:message-finish",
  "messages:message-start",
  "tools:tool-finished",
  "tools:tool-output-delta",
  "tools:tool-started",
];
invariant(
  JSON.stringify([...shapes].sort()) === JSON.stringify(expectedShapes),
  `fixture shape coverage drifted: ${JSON.stringify([...shapes].sort())}`,
);
invariant(typedEvents.length === 36, "expected thirty-six typed events");

console.log(
  `typescript protocol fixtures ok: ${recordCount} records, ` +
    `${typedEvents.length} typed events, ${shapes.size} shapes`,
);
