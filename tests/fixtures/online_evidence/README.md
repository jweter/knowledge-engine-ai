# Vendored ke-online-evidence/v1 golden fixture

`bundle.json` and `contents/` are a byte-identical copy of
`knowledge-engine-core`'s own committed contract fixture:

- source path: `tests/fixtures/online_evidence/` (same layout)
- source repository: `jweter/knowledge-engine-core`
- source commit: `02da1f2666e643e6e6f2a42bc93f53ae57c1b977`

Do not hand-edit these files. If Core's golden bundle changes, re-copy both
`bundle.json` and `contents/` from the new Core commit and update the SHA
above and in `docs/roadmap/research_report_v1.md`.
