/**
 * The wire contract is generated and locked at the repository root.
 *
 * Keep this file as a type-only seam: runtime code consumes the exact official
 * snake_case binding without copying or hand-maintaining protocol shapes.
 */
export type {
  AgentStatus,
  BlockDelta,
  Channel,
  Checkpoint,
  CheckpointRef,
  Command,
  CommandResponse,
  ContentBlock,
  ContentBlockDelta,
  ErrorCode,
  ErrorResponse,
  Event,
  EventStreamRequest,
  FinalizedContentBlock,
  InputRespondEntry,
  InputRespondMany,
  InputRespondOne,
  LifecycleCause,
  Message,
  MessageMetadata,
  MessageRole,
  Namespace,
  RunStart,
  RunStartParams,
  UsageInfo,
} from "../../../../protocol/generated/typescript/protocol"
