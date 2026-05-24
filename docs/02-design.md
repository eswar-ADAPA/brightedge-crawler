# Part 2 — Scaling to billions of URLs a month

The Part 1 service handles one URL at a time. This doc covers how I'd grow
it into a real pipeline that processes billions of URLs a month (for
example, all of `amazon.com`, `walmart.com`, and `bestbuy.com` for July),
stores everything in one shared schema, and answers millions of read
requests against it.

I picked the trade-offs with this order in mind: **cost first, then
reliability, then performance, then scale.** Scale is last only because the
other three force most of the design — once they're right, scale is mostly
a matter of adding workers.

---

## 1. Rough math

Before deciding on anything, I worked out how big the problem actually is:

- 2 billion URLs a month ≈ **770 URLs per second** on average.
- News and product inventory comes in bursts, so peaks are roughly **3×** that
  — say **2,300/sec**.
- An average HTML page is about **80 KB gzipped**. That's **~160 TB of raw
  HTML per month**.
- Once parsed, each page boils down to about **3 KB of metadata**. So
  **~6 TB of metadata per month**.
- "Millions of requests" on the read side translates to roughly **10–50k
  QPS** if it's spread across the day, or higher if it's bursty.

These numbers drive every later decision (storage tiering, queue depth,
how many workers).

---

## 2. The pipeline

The flow is queue-driven. URLs come in at one end; metadata comes out the
other. Nothing in the middle holds state that can't be rebuilt.

```
        URL frontier (dedupe + scheduler)
                │
                ▼
        URL queue, partitioned by host
                │
       ┌────────┼─────────┐
       ▼        ▼         ▼
    Tier A   Tier B    Tier C
    (httpx)  (httpx +  (Playwright
              proxy)    headless)
       └────────┼─────────┘
                ▼
        Raw HTML object store
        (gzipped, keyed by content hash)
                │
                ▼
        Parse + classify workers
        (the Part 1 container, scaled out)
                │
       ┌────────┴────────┐
       ▼                 ▼
   Hot KV store     Analytical lake
   (latest meta     (Parquet on
    per URL)         GCS/S3, queried
                     from BigQuery)
       │                 │
       ▼                 ▼
   Read API         Batch jobs
   (point lookup)   (rollups, ML)
```

### Why two stores instead of one

The read pattern split nicely in half:

- **Point lookups** — "what's the latest metadata for this URL?" — need to
  be fast and cheap per request. A key-value store (DynamoDB or Bigtable)
  is perfect for that.
- **Bulk queries** — "how many product pages on walmart.com mention 'air
  fryer' this month?" — would be ruinously expensive against a KV store
  but are cheap against Parquet in object storage queried by BigQuery or
  Athena.

So I'd keep both. The KV holds only the latest version per URL. The lake
holds every crawl, append-only, partitioned by date and domain.

### Why three crawl tiers

Not every page is equally hard to fetch. From what I saw just on the three
test URLs:

- **CNN** worked first try with plain `httpx`.
- **Amazon** worked, but sometimes returned an anti-bot stub instead of
  the real product page.
- **REI** dropped the connection at the TLS layer — Akamai bot detection
  spots `httpx` even with browser-like headers.

That spread is typical. My rough split:

- **Tier A** — plain `httpx`. About 85% of pages. Cheap.
- **Tier B** — `httpx` plus a residential IP pool. Another ~10%.
- **Tier C** — real headless browser (Playwright). Last ~5%, including
  the REI-style cases.

Tier C is roughly 30× the cost of Tier A per page, so URLs only land
there after Tier B has failed twice.

---

## 3. The data schema

One record per `(URL, crawl_time)`. Same shape everywhere — protobuf in
queues, Parquet in the lake, JSON on the public API. Schema is versioned
so I can add fields without breaking old readers.

The important fields:

```proto
message PageRecord {
  int32  schema_version = 1;

  // Identity
  string url               = 10;   // original
  string final_url         = 11;   // after redirects
  string url_hash          = 12;   // sha256(url) — used for partitioning
  string registered_domain = 13;   // "amazon.com"
  string host              = 14;   // "www.amazon.com"

  // How and when we got it
  int64  crawled_at_ms     = 20;
  string crawler_tier      = 21;   // A | B | C
  string crawler_version   = 22;   // git sha
  int32  http_status       = 23;
  string raw_html_uri      = 25;   // gs://…/<sha256>.html.gz
  string raw_html_sha256   = 26;

  // Extracted metadata
  string title             = 30;
  string description       = 31;
  string canonical_url     = 32;
  string language          = 33;
  string author            = 34;
  string published_iso     = 35;
  string page_type         = 37;

  // Raw signals (kept so I can re-classify later without re-crawling)
  repeated KV     open_graph    = 40;
  repeated string json_ld_types = 42;
  bytes           json_ld_raw   = 43;

  // Content
  string body_text     = 50;
  int32  word_count    = 51;
  string body_excerpt  = 52;

  // Classification (re-runnable)
  string page_category       = 60;
  float  category_confidence = 61;   // Part 1 ships a coarse low|medium|high
                                     // string; production stores a float so
                                     // downstream consumers can sort/threshold.
  repeated Topic topics      = 62;
  string classifier_version  = 63;
  bool   partial             = 64;   // anti-bot interstitial or thin content
  string partial_reason      = 65;
}
```

The thing I want to highlight is that **raw signals are kept verbatim** —
the `open_graph` map, the JSON-LD blob, the OG image. If we change the
classifier next month, we re-run it over the lake. No re-crawl needed.
That's been the bit that bites teams the hardest in practice: throwing
away the inputs you'd need to re-derive things.

### Where each piece lives

| Where | Format | Keyed by | Kept for |
|---|---|---|---|
| Object store (raw HTML) | gzipped | `sha256` of body | 90 days hot, 1 year cold |
| Object store (lake) | Parquet, partitioned by date + domain | — | Indefinite |
| Hot KV | One row per URL, latest only | `url_hash` | 30 days, then TTL |

Partitioning the lake by `registered_domain` means a query like "all
amazon.com pages from last week" scans one folder, not the whole lake.

### Dedupe

Two layers:

- **At ingest** — Redis bloom filter on URL hash. Drops duplicate submissions.
- **At crawl** — if `sha256(html)` already exists in object storage, skip the
  re-parse and just emit a new `PageRecord` pointing at the existing blob.
  Amazon pages change very little between crawls; this saves a lot.

---

## 4. SLOs and SLAs

I'd split the two carefully. SLOs are what we promise ourselves internally
(the bar we run against). SLAs are what we promise customers (looser, with
some slack in case things go sideways).

### Internal SLOs

| What we measure | Target | Window |
|---|---|---|
| Read API success rate | 99.9% | 30-day rolling |
| Read API latency (point lookup) | p50 ≤ 15 ms, p99 ≤ 80 ms | 30-day rolling |
| Crawl freshness (Tier A) | median lag ≤ 10 min | 7-day rolling |
| Crawl success (HTTP 2xx + parseable) | ≥ 92% | 7-day rolling |
| Classification coverage (≥ 1 topic, real category) | ≥ 85% | 7-day rolling |
| Lost writes after queue ACK | 0 | always |

### Customer-facing SLAs

| What we promise | Value |
|---|---|
| API uptime | 99.5% per month |
| Read latency | p99 < 250 ms |
| Freshness (new URL → queryable) | within 24 h for Tier A/B |

### Error budgets

99.9% read availability is about 43 minutes of allowed downtime per month.
If we burn that 2× faster than expected over a 1-hour window, on-call gets
paged and deploys auto-freeze until we recover.

---

## 5. Costs

A rough monthly bill on GCP at 2B URLs/month. (AWS spot prices are roughly
half this; reserved-but-not-committed is roughly 2×.)

| What | Why it costs that much | Per month |
|---|---|---|
| Tier-A crawl (85%, 1.7B URLs) | ~0.5 vCPU-s per URL × 1.7B | ~$8 k |
| Tier-B crawl (10%, 200M URLs) | Same compute + residential proxy bandwidth | ~$6 k |
| Tier-C crawl (5%, 100M URLs) | Playwright is ~5 s per URL | ~$11 k |
| Raw HTML object store | 160 TB hot + 1.6 PB cold over a year | ~$9 k |
| Metadata lake (Parquet) | 6 TB/month, 1 year retention | ~$1.5 k |
| Hot KV (Bigtable, 3 nodes) | ~$5 k |
| BigQuery queries | Maybe 200 TB scanned/month at $5/TB | ~$1 k |
| Egress / misc | | ~$2 k |
| **Total** | | **~$45 k/month** |

The numbers are illustrative — I'd want to validate them against actual
billing once the PoC is running.

### Where I'd push to cut costs

In order of bang-for-buck:

1. **Don't re-crawl what hasn't changed.** Send `If-Modified-Since` and
   `If-None-Match` headers. Pages that return 304 skip parse entirely.
   30–50% of pages will do this on a typical month. Easy big win.
2. **Run crawl workers on spot/preemptible VMs.** Crawl is idempotent and
   queue-driven, so a worker being killed is free. 60–80% off compute.
3. **Don't escalate every failure to Tier C.** Most failures are 404s or
   DNS errors that won't get better in Playwright. Dead-letter those instead.
4. **Auto-tier object storage.** Hot → Nearline at 30 days → Coldline at 90
   days → Archive at a year. GCS does this with a lifecycle rule.
5. **Cache in front of the hot KV.** Read traffic is super skewed — about
   1% of URLs see 99% of the requests. A 1 TB Redis cluster in front of
   Bigtable hits ~95% and we can shrink the KV.

---

## 6. What breaks, and how I'd handle it

This is the part most worth thinking about in advance:

| What goes wrong | What I'd do |
|---|---|
| A worker OOMs on a huge page | Cap fetch at 5 MB. Reject anything bigger and dead-letter it. |
| A host starts blocking us | Per-host circuit breaker: after 5 consecutive blocks, back off 30 minutes. Move that host to a higher tier. |
| Queue backs up | Auto-scale workers on queue depth. Slack warning at 30 min of backlog, page at 2 hours. |
| Lake corruption | Iceberg gives snapshot isolation. Plus a nightly job that checks every `raw_html_sha256` actually exists in the blob store. |
| A region goes down | Object store is multi-region by default. Workers redeployable to another region in minutes. Read API gracefully falls back to last-known data. |
| A bad classifier deploy ruins recent results | Classifier writes are versioned. To roll back, we just serve the previous version's rows — no re-crawl needed. |
| robots.txt changes | Per-host robots cache with a 6-hour TTL, plus a kill switch to purge a host from the frontier immediately. |

The classifier rollback bit is the one I'd most want to get right. If you
ship a bad model and only realize a day later, re-crawling 2 B URLs to
fix it would be a disaster. Versioning the classifier outputs means the
fix is a config flip.

---

## 7. What to monitor

The four signals I'd put on the wall:

| Signal | How | Where it pages |
|---|---|---|
| Read API latency (p50/p95/p99) | Prometheus + Grafana | PagerDuty if 5 min over SLO |
| Read API error rate | Prometheus | PagerDuty if > 1% over 5 min |
| Crawl queue depth and age | Queue metrics | Slack warn @ 30 min, page @ 2 h |
| Per-host fetch success rate | Prometheus | Slack warn if a top-100 host drops below 80% |

Plus dashboards (not pages) for: parse errors, lake commit lag, per-domain
breakdown, and a cost dashboard rebuilt daily from the billing export.

Every URL gets an OpenTelemetry trace ID that follows it from queue →
fetch → parse → classify → write. Sampled at 1% by default, 100% for
slow tails. That's been the single most useful tool I've had in past
pipelines — when something is slow, you can drill into a specific URL
and see which span ate the time.

---

## 8. Being a good citizen

A real crawler has to be polite or it gets banned:

- Respect `robots.txt`. Cached per host for 6 hours.
- Identify in the User-Agent with a contact URL.
- Default to 4 concurrent connections per host. Higher only for partners.
- Rate-limit adaptively — if a host starts returning 429/503, back off.
- No JS execution in Tier A or B. Less load on the target, fewer surprises.

---

## 9. What this doesn't try to solve

Things I'd deliberately leave for later, so reviewers know they were
considered and not just forgotten:

- **JavaScript-heavy SPAs at full scale.** Tier C handles them but at
  30× cost. The fix is sharing browser contexts across same-domain URLs,
  which is real work.
- **Multi-language classification.** YAKE is English-leaning. For other
  languages I'd run a small zero-shot model on a sample.
- **Sub-minute freshness.** This is a batch design. Real-time crawling
  (under a minute lag) needs a separate streaming path.
