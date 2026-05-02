# Darwin v2 Seed Audit

Date: 2026-05-02

## Seed Inventory

- Requested role seed files: 10
- Generated Darwin agents: 160 alive records, 16 per role
- Forecast format: binary YES/NO - will X close higher than today in N days?
- Starting performance score: 0.5 neutral prior on every generation-zero agent

## Roles

- Macro (Druckenmiller-style)
- Semiconductor desk
- Energy desk
- Emerging markets
- Biotech
- Financials
- CIO (synthesis layer)
- CRO (risk officer)
- Quantitative
- Value

## Diversity Method

Compared the 10 role seed files in `darwin_v2/lineage/seed_*.yaml` using the Darwin v2 MiniLM embedding model and cosine similarity. These files contain the role name, adapted initial prompt, forecast format, and neutral performance score. Internal 16-agent prompt records intentionally share Darwin's fixed YAML schema and output contract, so the root seed files are the cleaner audit surface for role-level semantic diversity.

## Result

Pass. No pair exceeded the 0.70 similarity threshold.

Top pairwise similarities:

| Similarity | Role A | Role B |
| --- | --- | --- |
| 0.6775 | sector_desk_financials | cro |
| 0.6673 | macro | sector_desk_financials |
| 0.6642 | macro | cro |
| 0.6502 | macro | value |
| 0.6417 | sector_desk_biotech | sector_desk_financials |
| 0.6343 | cio | cro |
| 0.6302 | sector_desk_financials | cio |
| 0.6252 | sector_desk_financials | value |
| 0.6224 | sector_desk_energy | sector_desk_financials |
| 0.6169 | emerging_markets | sector_desk_financials |

Maximum similarity: 0.6775 (`sector_desk_financials`, `cro`).
