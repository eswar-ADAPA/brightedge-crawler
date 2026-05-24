# Part 3 — From the demo to a proof-of-concept

The Part 1 service works on one URL. Part 2 describes what production
should look like. This doc is the bridge: what I'd actually build in the
first three weeks to prove the pipeline shape end-to-end, and what comes
after.

I'm deliberately keeping this short. A PoC is meant to *de-risk* the
design, not pre-build production.

---

## 1. What the PoC has to prove

> The pipeline (queue → crawl → parse → classify → store → read) works
> end-to-end on **10 million URLs** across `amazon.com`, `walmart.com`,
> and `bestbuy.com`, on a single region, with enough observability to
> tell when it breaks.

I picked 10 million because it's the smallest number where the problems
become real: queue depth varies, Parquet's small-file issue shows up,
per-host rate limits start to bite. It's also cheap to redo (~$300 in
crawl + storage) if we mess something up.

### Done = these four things are true

1. ≥ 90% of the 10 M URLs have a `PageRecord` written to both the KV
   store and the lake.
2. A topic-rollup query over all 10 M rows runs in under 30 seconds.
3. The Read API serves 1,000 QPS at p99 < 80 ms in a 30-min synthetic
   load test.
4. Basic dashboards exist for crawl health, lake lag, and API latency,
   and they show actual numbers, not zeros.

That's the bar. Anything else — Tier C, chaos drills, runbooks, cost
dashboards — comes after we know the spine works.

---

## 2. The three-week plan

```
Week 1   Build the spine
         - Fetcher (Tier A only): httpx + retries + robots cache
         - URL queue (PubSub / SQS) + Redis dedupe bloom
         - Raw HTML object store writer (idempotent, keyed by sha256)
         - Parse + classify worker = the Part 1 container

Week 2   Wire up storage and reads
         - Parquet/Iceberg lake writer, partitioned by date + domain
         - Hot KV writer (Bigtable or DynamoDB)
         - Read API: GET /metadata, GET /classify
         - Basic observability: structured logs + Prometheus + 3 dashboards

Week 3   Scale and measure
         - Dry run on 1 M URLs, fix whatever cracks
         - Scale to 10 M URLs
         - Run the 30-min load test against the Read API
         - PoC review: walk through the four "done" criteria with numbers
```

### What's deliberately *not* in the PoC

- **Tier B + C crawl** (residential IPs, Playwright). Tier A is enough
  to prove the pipeline. Adding tiers earlier just lets us claim more
  coverage; it doesn't validate any new design risk.
- **Multi-region**. One region for the PoC. Multi-region is part of the
  production ramp, not the proof-of-concept.
- **Per-host adaptive rate limiting.** Naive 4-concurrent-per-host is
  fine at 10 M URLs. AIMD is a production refinement.
- **Game day / chaos drills.** Before GA, yes. Before the PoC review, no.
- **Cost dashboard**. We can read the billing export by hand for now.

Cutting these is what turns 6 weeks into 3.

---

## 3. What I know, what I don't, what could go wrong

### Low risk (already de-risked)

- HTML parsing + metadata extraction — working in Part 1.
- Object store ingest, stateless workers behind a queue — vanilla patterns.
- The 3 test URLs already gave me one clean case (CNN), one variable case
  (Amazon), one hard-blocked case (REI). I know the shape of what we'll hit.

### Medium risk

- **Iceberg / Parquet small-file problem.** Without compaction we'll have
  millions of tiny files by the end of week 3. Need a scheduled compaction
  job from day one.
- **Idempotency.** Queues redeliver. Every writer has to be safe to replay.
  Easier to design in than retrofit.
- **Topic-quality ceiling with YAKE + JSON-LD.** This is the open question
  I'd want to spike on alongside the build — label ~500 pages by hand,
  measure F1, decide if a v2 classifier is needed before GA.

### Biggest risks (and what I'd do about them)

| Risk | What I'd do |
|---|---|
| Hot-spot in the KV (Amazon traffic dominates) | Hash-prefix the partition key from day one. |
| Per-host blocks during scale-up | Per-host circuit breaker: 5 consecutive blocks → 30 min cooldown. |
| Classifier change ruins recent rows | `classifier_version` per row; roll back is a query change, not a re-crawl. |
| 10 M URLs cost more than budgeted | Hard cap on per-URL spend; bail at 1.5× the model. |

---

## 4. How we'd evaluate the PoC

Pass/fail, not vibes:

| What | How we measure | Bar |
|---|---|---|
| Correctness | Replay 500 hand-labeled URLs; compare titles, descriptions, top topics | ≥ 95% title match, ≥ 80% top-3 topic overlap |
| Throughput | Sustained crawl rate over the 10 M run | ≥ 500 URLs/sec, < 5% retries |
| Read latency | k6 at 1,000 QPS for 30 min | p99 ≤ 80 ms, errors ≤ 0.1% |
| Cost | Per-URL cost from the billing export | ≤ $0.00003 per URL |

A short review meeting at the end of week 3 walks through each row with
the dashboards as evidence.

---

## 5. After the PoC

If the four "done" criteria are met, the PoC report becomes the input to
a production ramp:

| Stage | Scope | Duration |
|---|---|---|
| Internal | 10 M URLs/week from friendly domains | 2 weeks |
| Shadow | 100 M URLs/week, results written but not served | 2 weeks |
| GA | Ramp 2× weekly to 2 B/month | 4 weeks |

Each ramp step needs a 24-h soak at the new volume with green dashboards
before advancing.

### What "high quality release" means here

- Feature flags on the read path so we can dark-launch new fields.
- `classifier_version` per row, so a bad classifier deploy is a config
  flip, not a re-crawl.
- Pre-prod load test at 2× current peak before each ramp.
- Runbooks for the top three incident types before GA: queue backlog,
  host block, classifier rollback.
- Cost dashboard reviewed weekly for the first two months.

These didn't fit in the 3-week PoC, but they're not optional for prod.

---

## 6. Team

For a 3-week PoC, realistic minimum:

- 2 backend engineers
- 0.5 SRE / platform (observability + the queue + cost setup)
- 0.5 PM (scope, comms)

The production ramp needs more — a data engineer for the lake, a full
SRE for on-call. But not for the PoC.

---

## 7. Next things after PoC (not committed)

- **Tier B + C crawl.** Decide based on the actual block rate we see in
  the PoC. If ≥ 10% of URLs are blocked, Tier B is worth building.
- **Classifier v2.** Use the 500 hand-labeled pages from the PoC eval
  to fine-tune a small zero-shot model.
- **Sitemap / RSS ingestion.** Replace ad-hoc URL submission for hosts
  that publish sitemaps. Friendlier and cheaper.
