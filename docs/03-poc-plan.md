# Part 3 — From the demo to a proof-of-concept

The Part 1 service works on one URL. Part 2 describes what production
should look like. This doc is the bridge: what I'd actually build in the
first six weeks, in what order, and how I'd know it worked.

---

## 1. What the PoC should prove

> The whole pipeline (queue → crawl → parse → classify → store → read)
> works end-to-end on **10 million URLs** across `amazon.com`,
> `walmart.com`, and `bestbuy.com`, hitting the SLOs from
> [docs/02-design.md](02-design.md) at roughly 1/200th of full scale.

I picked 10 million because that's the smallest number where the
problems start being real ones:

- Queue depth varies enough that auto-scaling matters.
- Parquet's "too many small files" problem shows up.
- Per-host rate limits actually bite (especially Amazon).
- It's still cheap (~$300 in crawl + storage) so we can redo it cleanly
  if we mess something up.

### How we'd know it worked

The PoC is done when all six of these are true:

1. At least **90%** of the 10 M URLs have a `PageRecord` written to both
   the KV store and the lake.
2. A topic-rollup query over all 10 M rows runs in under **30 seconds**
   in BigQuery.
3. The read API serves **1,000 QPS** at p99 < 80 ms in a synthetic load
   test.
4. The dashboards for crawl health, lake lag, and API SLIs exist and
   are accurate.
5. One simulated regional failure (drain one region, traffic continues
   from the other) finishes with less than 5 minutes of crawl pause.
6. A runbook exists for the three most likely incidents — queue backlog,
   host block, classifier rollback.

If we hit all six, we move on. If we don't, the PoC review gets specific
about what to fix; we don't paper over a miss.

---

## 2. Work to do

| # | Stream | Effort | Depends on |
|---|---|---|---|
| W1 | Harden the fetcher (Tier A + B, retries, robots cache) | 1.5 weeks | — |
| W2 | URL frontier + dedupe (queue + Redis bloom filter) | 1 week | — |
| W3 | Containerize the Part 1 parse + classify worker | 0.5 weeks | — |
| W4 | Raw HTML object store layout + idempotent writer | 0.5 weeks | — |
| W5 | Lake writer (Parquet/Iceberg) + BigQuery table | 1 week | W4 |
| W6 | Hot KV writer + Read API | 1 week | — |
| W7 | Tier-C Playwright fallback (pilot, one host) | 1 week | W1 |
| W8 | Prometheus, Grafana dashboards, OTel tracing | 1 week | W1, W6 |
| W9 | Cost dashboard and per-component billing tags | 0.5 weeks | W8 |
| W10 | Load test harness (k6 against Read API) | 0.5 weeks | W6 |
| W11 | Runbooks + a game-day exercise | 0.5 weeks | W8 |

W1–W6 are the critical path. Everything else can run alongside.

---

## 3. A six-week plan

```
Week 1   W1 fetcher, W2 frontier, W4 raw store — in parallel
Week 2   W1 finishes; W3 worker integration; W6 KV writer starts
Week 3   W5 lake writer; W8 observability scaffolding; W7 Tier-C pilot
Week 4   End-to-end on 1 million URLs (internal dogfood).
         Iterate on whichever parts of parsing/classification are weak.
Week 5   Scale to 10 million URLs. W10 load test runs. W9 cost tags applied.
Week 6   W11 runbooks + a game-day. PoC review. Go/no-go for prod ramp.
```

Week 4 is deliberately a slack week — by then I expect something to be
wrong that nobody predicted, and the team needs space to fix it without
falling off the schedule.

---

## 4. What I know and what I don't

### Easy and known

- HTML parsing, metadata extraction, topic extraction — already works,
  it's a throughput-tuning exercise from here.
- Object-store writes. Vanilla.
- Stateless workers behind a queue. Standard pattern.

### Known but real work

- **Per-host adaptive rate limiting.** A naive token bucket isn't enough.
  I'd want AIMD (additive-increase, multiplicative-decrease) on
  429/503 responses. About 3 days plus tuning per major host.
- **Iceberg compaction.** Without it, after a few months we'd have
  billions of tiny Parquet files and queries would crawl. Need a
  scheduled compaction job from day one. About a week.
- **Idempotency everywhere.** Queues redeliver. Every writer has to be
  safe to replay. Easier to design in than retrofit.

### Things I'd want to spike on (open questions)

- **How many of our target hosts are bot-defended like REI?** I genuinely
  don't know. Three days of work: sample 10,000 URLs per host, count
  failures, decide if Tier C needs more budget.
- **Is YAKE + JSON-LD good enough for topics?** Or do we need a
  fine-tuned model? About a week: label ~1,000 pages by hand, measure F1
  against the current pipeline. That tells us whether classifier quality
  is the bottleneck or not.
- **Hot KV: Bigtable, DynamoDB, or Spanner?** Depends on the read pattern.
  Maybe 4 days replaying a synthetic trace against each.

### Biggest risks

| Risk | Likelihood | Impact | What I'd do about it |
|---|---|---|---|
| Tier C eats the budget | Medium | High | Hard cap at 5% of traffic. Dead-letter beyond N retries. |
| Legal pushback from a target host | Low | High | Respect robots.txt. Identify the bot. Have a per-host kill switch. |
| Classifier quality stalls | Medium | Medium | Lake stores raw signals, so re-classification is a job, not a re-crawl. |
| Single-region capacity ceiling | Low | High | Spin up a second region by week 5. |
| Hot-spotting in KV (Amazon traffic) | Medium | Medium | Hash-prefix partition keys; pre-split Bigtable tablets. |

---

## 5. How we'd evaluate the PoC

Concrete numbers, not vibes. Pass/fail on each:

| What | How we measure | Bar |
|---|---|---|
| Correctness | Replay 1,000 hand-labeled URLs; compare extracted fields against labels | ≥ 95% title match, ≥ 85% description, ≥ 80% top-3 topic overlap |
| Throughput | Sustained 24-hour crawl rate | ≥ 500 URLs/sec with under 5% retries |
| Read latency | 30 min of k6 at 1,000 QPS | p99 ≤ 80 ms, errors ≤ 0.1% |
| Reliability | Chaos drill: kill half the workers, drain a zone | No data loss; backlog drained in 30 min |
| Cost | Per-URL cost from the billing export | ≤ $0.00003 per URL |
| Coverage | URLs producing useful metadata | ≥ 92% |

The PoC review at end of week 6 walks through each row with the
dashboards as evidence.

---

## 6. Releasing to production

I would not flip a switch and send 2 billion URLs at this thing. I'd ramp:

| Stage | What | How long | What has to be true to advance |
|---|---|---|---|
| Internal | 10 M URLs/week from three known-friendly domains | 2 weeks | All SLOs met. On-call rotation set up. |
| Shadow | 100 M URLs/week, results written but not served to customers | 2 weeks | No regressions vs. internal. Runbook drills passed. |
| GA | 500 M URLs/week, then double weekly until 2 B/month | 4 weeks | Customer SLAs met. Cost within 20% of the model. |

Each ramp step needs a **24-hour soak** at the new volume with green
dashboards before advancing. If a burn-rate alert fires during soak, the
ramp halts. We don't roll forward through a budget violation just to
stay on the calendar.

### What "high-quality release" means here

- Feature flags on the read path so we can dark-launch new fields.
- Automatic rollback: bad classifier deploy → traffic served from the
  previous classifier version. (Per-record `classifier_version` makes
  this just a query change.)
- Pre-prod load test that hits 2× the current peak. Never let production
  traffic be the thing that reveals a capacity ceiling.
- Runbooks + game days for the top five incident types **before** GA.
- Cost dashboard reviewed weekly for the first two months. Alert on
  1.5× baseline.

---

## 7. What this needs from the team

To deliver in six weeks, the minimum that feels realistic:

- 2 backend engineers (crawl, KV, API)
- 1 data engineer (lake, analytics)
- 1 platform / SRE person (observability, cost, on-call)
- 0.5 of a PM or TPM (scope, comms, risks)
- A senior engineer for design review (~30% of their time)

Optional but useful: a part-time data scientist in weeks 4–6 to look at
classifier quality and start planning a v2.

---

## 8. What comes after the PoC

Not committed, but the next things I'd look at:

- **Cheaper Tier C.** Sharing Chromium contexts within a domain cuts
  per-page cost a lot — 5–10× is realistic.
- **Classifier v2.** Use the hand-labeled data from the PoC to fine-tune
  a small zero-shot model. Drop YAKE for English; keep it for languages
  we don't have models for.
- **Premium freshness tier.** Some customers will pay for "under 1 hour"
  freshness. That probably means a separate streaming path.
- **Sitemap and RSS ingestion.** Replace ad-hoc URL submission with
  sitemap.xml-driven discovery for the hosts that publish one. Friendlier
  to crawl, cheaper to operate.
