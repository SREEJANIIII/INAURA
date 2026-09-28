# Labour Market Intelligence (P0 #1)

Provider-neutral ingestion + aggregation layer **underneath**
`industry_intelligence.py` (which is unchanged). It converts raw job-posting
observations into canonical, explainable demand signals. It does NOT replace
O*NET/ESCO baselines, the skill taxonomy, role catalog, gap engine, or the
existing `DemoSeedDemandProvider` (still registered as demo fallback).

## Architecture

```
raw posting dicts / LabourMarketPostingProvider.fetch_postings()
  -> sanitize_description()   (email/phone scrub; postings only, never resumes)
  -> normalize_posting()      (role via canonicalize_role_name, location from
                               the posting source only, defensive timestamps)
  -> map_posting_skills()     (taxonomy mapping; unmapped preserved)
  -> ingest_postings()        (dedup by (provider, external_id), then content_hash)
  -> aggregate_demand()       (monthly buckets per provider/role/skill/location)
     -> calculate_demand()    (posting_count, skill_posting_count, skill_share)
     -> calculate_trend()     (recent vs previous month share delta)
     -> small-sample gate     (suppressed cells keep raw counts, capped confidence)
  -> get_demand_signals()     (filtered read with provenance)
  -> to_industry_demand_signals() / LabourMarketDemandProvider
     (IndustryDemandProvider-compatible adapter; registered alongside the demo
     seed via register_labour_market_provider() — build_role_intelligence()
     itself is untouched)
```

Service: `backend/app/services/labour_market_service.py`.
Migration: `backend/supabase/030_labour_market_intelligence.sql`.
Endpoints: `GET /industry/labour-market/signals`, `POST /industry/labour-market/refresh`
(authenticated, idempotent). Frontend: `MarketEvidence.tsx` additive block.

## Data model

- `labour_market_postings`: raw observations. Unique
  `(provider_id, external_posting_id)` where external id exists + `content_hash`
  index for content dedup. `role_mapping_status` = mapped/unresolved.
- `labour_market_posting_skills`: one row per (posting, source_concept).
  `mapping_status` = mapped/unmapped; unmapped rows keep `canonical_skill_slug`
  NULL and are never forced onto unrelated skills.
- `labour_market_demand_signals`: monthly DERIVED cells. Unique logical key =
  provider + role + skill-or-concept + location + period_start (two partial
  unique indexes: canonical-slug cells vs raw-concept cells). Carries raw
  counts (`posting_count`, `skill_posting_count`, `distinct_company_count`)
  beside derived `skill_share`, `demand`, `required_level` (NULL — not observed
  from postings), `importance` (NULL), `trend`, `confidence`, plus
  `evidence_suppressed`, `provider_id`, `data_origin`, `source_version`,
  `evidence_context`, `computed_at`.

## Provider model

`LabourMarketPostingProvider` (fetch_postings) is posting-level and distinct
from `IndustryDemandProvider` (signal-level). New external sources implement
`fetch_postings()` only — normalization/aggregation need no rewrite.
`DemoPostingProvider` (`demo_postings_v1`) returns deterministic synthetic
postings for Software Engineer, Frontend Developer, Backend Developer, Mobile
Developer across Jun–Aug 2026. **It is synthetic and is NOT live
labour-market data**: every row has `data_origin='demo_seeded'`,
`is_live=False`, and UI/API copy always says "not live".

## Skill mapping

`skill_taxonomy.get_canonical_skill` / `extract_known_skills_from_text` only —
no second taxonomy. Provider skill tags map first, then taxonomy phrase
extraction over title+description. Unmapped concepts are stored verbatim with
`mapping_status='unmapped'` and excluded from canonical demand reads unless
`include_raw_concepts=true`.

## Role mapping

`industry_roles.canonicalize_role_name` only. Unresolvable titles keep the raw
`title`, get `role_key=NULL` + `role_mapping_status='unresolved'`, and are
excluded from aggregation (never fabricated into a canonical role).

## Location model

Reuses `industry_intelligence.normalize_location`: global/country/region/city.
Location always comes from the posting source. Global cells match every query;
specific cells match on exact key only. City demand is never fabricated —
unknown-city queries fall back to global baselines in the intelligence view.

## Demand calculation

Separate dimensions, never one opaque score:

- `posting_count` — role postings in the cell's month.
- `skill_posting_count` — of those, postings mentioning the skill.
- `skill_share = skill_posting_count / role_posting_count`.
- `demand = skill_share` rounded to 3dp — the documented 0..1 normalized form
  of the observed share (45/100 → share 0.45 → demand 0.45). Raw counts are
  always preserved beside it. `required_level`/`importance` stay NULL because
  postings do not observe proficiency requirements directly.

## Trend calculation

Recent month vs previous month `skill_share` delta, no LLM:

- `delta >= +0.10` → rising; `delta <= −0.10` → declining; else stable.
- Either month under 10 role postings, or the skill under 3 mentions in both
  months → `insufficient_data`. Suppressed cells always report
  `insufficient_data`, never rising/declining.

## Small-sample policy

Constants in `labour_market_service.py`: `MIN_ROLE_POSTINGS=10`,
`MIN_SKILL_MENTIONS=3`, `MIN_DISTINCT_COMPANIES=2`. Cells below any minimum
are preserved with `evidence_suppressed=true`, trend `insufficient_data`,
confidence capped at 0.40. Confidence otherwise blends posting/skill/company
breadth, capped at 0.95.

## Provenance

Every signal carries `provider_id`, `data_origin`, `period_start/end`,
`posting_count`, `skill_posting_count`, `source_version`, `computed_at`, and a
human `evidence_context` ("Derived from N of M observed postings mentioning
'X' during A → B …"). Origins stay distinct: `source_data` (authentic
benchmarks), `inaura_derived` (aggregation), `demo_seeded` (synthetic demo).

## Demo vs live data

`DemoPostingProvider` and `DemoSeedDemandProvider` are synthetic test
plumbing. `is_live` is False on both; display names/descriptions say "not
live"; the MarketEvidence UI block appends "(synthetic demo data — not live
market data)" whenever all rows are demo-origin.

## Future provider integration

1. Subclass `LabourMarketPostingProvider` with a real `provider_id`,
   `data_origin='source_data'`, `is_live=True`, and `fetch_postings()`.
2. `register_posting_provider()` it, then `POST /industry/labour-market/refresh`
   (authenticated) to import + aggregate.
3. The existing `LabourMarketDemandProvider` adapter already exposes the new
   rows to `industry_intelligence` in the normalized signal shape — no gap,
   retrieval, or taxonomy changes needed.
