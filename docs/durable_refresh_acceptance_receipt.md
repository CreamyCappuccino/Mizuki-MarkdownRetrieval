# Durable refresh CLI acceptance receipt

Status: **ACCEPT / operational refresh slice CLOSED**

The durable index mutation boundary remains CLI-only. The accepted MCP v0 remains read-only and unchanged.

## Accepted operational route

```text
mizuki-mdr --config <config.toml> refresh <scope>
```

The configured scope owns:

- Markdown discovery/root rules
- state snapshot path
- durable SQLite path
- provider/search representation revision
- Ruri model path/device

Callers do not provide arbitrary database/model/revision values to the refresh command.

## Safety / consistency contract

The accepted refresh flow is:

1. load the committed state baseline;
2. discover current Markdown and prepare a desired-state plan;
3. model-free preflight the durable SQLite namespace against the **committed baseline** before any incremental/no-op apply;
4. if baseline matches, continue the planned delta;
5. if the committed durable index is missing, discard the partial plan and rebuild all current documents from source;
6. if durable data exists but differs from the committed baseline, fail closed before opening the write provider;
7. open the Ruri-backed writable provider only when a changed plan will actually be applied;
8. perform the shared atomic SearchE apply;
9. commit the new local state snapshot only after provider success.

The preflight result distinguishes:

- `match`: safe to continue;
- `missing`: recoverable from current source via full rebuild;
- `mismatch`: unknown drift; refuse automatic overwrite.

## Provider revision changes

Provider/search representation revision is persisted independently from the Markdown chunker representation.

A provider revision change with unchanged Markdown forces:

- every current document to `full_reindex`;
- every current chunk to receive a fresh embedding;
- zero embedding reuse from the old provider revision;
- one atomic replacement from the committed old document versions to the new provider revision.

State schemas v2/v3 load with an unknown legacy provider revision, causing a safe fresh reindex rather than pretending the missing historical revision is known.

## Recovery cases accepted

The real SearchE/Ruri acceptance covered:

1. initial 3-document build;
2. normal no-op refresh (`changed=0`) without loading the write/Ruri provider;
3. one-file source edit and incremental apply;
4. provider revision v1 -> v2 with source bytes unchanged, resulting in all-current fresh reindex;
5. durable SQLite deletion while state remains, resulting in automatic all-current rebuild;
6. **durable SQLite deletion and one source edit occurring before the same refresh**, resulting in baseline-missing detection before the one-file delta and an all-current rebuild;
7. existing durable/state mismatch fails closed before write-provider open.

## Real acceptance evidence

Codex/SearchE integration acceptance at source HEAD `aeac633`:

- expanded real Ruri refresh E2E: `1 passed in 6.06s`
- focused refresh/preflight/state/provider tests: `30 passed`
- only known SWIG `DeprecationWarning` noise

Post-recovery verification:

- durable/state parity: `match`
- all 3 expected documents restored
- literal search: related `signal.md` top-1
- semantic search: related `signal.md` top-1
- hybrid search: related `signal.md` top-1
- provider v1 -> v2 leaves no mixed old-revision index state

## Boundary retained

Public/local MCP still exposes only:

- `list_markdown_scopes`
- `list_markdown_files`
- `search_related_markdown`
- `read_markdown`

No MCP tool can refresh or mutate the durable index.
