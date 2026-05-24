# BrightEdge Engineering Developer Assignment — Submission

A URL → metadata + topics service, plus a design and PoC plan to scale it to
billions of URLs per month.

## Repository layout

```
submission/
├── app/                      # Part 1 — the working service
│   ├── fetcher.py            #   HTTP fetch (HTTP/2 + retries + UA shaping)
│   ├── extractor.py          #   HTML → metadata (OG, JSON-LD, body)
│   ├── classifier.py         #   page_category + ranked topics
│   └── main.py               #   FastAPI app, GET /classify?url=…
├── tests/smoke.py            # Runs the 3 sample URLs from the assignment
├── sample_outputs/           # Captured JSON responses for the 3 URLs
├── docs/
│   ├── 02-design.md          # Part 2 — scale design, schema, SLOs, monitoring
│   └── 03-poc-plan.md        # Part 3 — PoC plan, risks, release plan
├── deploy/cloud-run.md       # Demo deployment instructions (GCP / AWS)
├── Dockerfile                # Production container
└── requirements.txt
```

## Quick start — run locally

```bash
cd submission
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# CLI smoke test against the 3 URLs from the assignment:
.venv/bin/python -m tests.smoke

# HTTP server:
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
# then in another shell:
curl -s --get 'http://127.0.0.1:8080/classify' \
  --data-urlencode 'url=https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai' \
  | python -m json.tool
```

## Quick start — Docker

```bash
docker build -t brightedge-crawler .
docker run -p 8080:8080 brightedge-crawler
```

## Deploy a public demo

See [deploy/cloud-run.md](deploy/cloud-run.md). One command:

```bash
gcloud run deploy brightedge-crawler-demo --source . --region us-central1 --allow-unauthenticated
```

## What the service does

`GET /classify?url=<URL>` returns JSON containing:

- **Metadata**: title, description, canonical URL, language, author, publish
  date, OpenGraph + Twitter cards, JSON-LD types, H1/H2 headings, word count,
  body excerpt.
- **Topics**: a ranked list combining structured signals (schema.org
  `category`, `articleSection`, `keywords`, breadcrumbs) and unsupervised
  keyphrase extraction (YAKE) over the title + body.
- **Page category**: a coarse label (`product`, `article`, `video`,
  `recipe`, `event`, `organization`, `website`, `other`) derived primarily
  from schema.org `@type` and OpenGraph `og:type`, with URL-pattern fallbacks.
- **Provenance**: final URL after redirects, HTTP status, fetch time.

## Sample results (full JSON in [sample_outputs/](sample_outputs/))

| URL | Category | Confidence | Notes |
|---|---|---|---|
| CNN article on Google AI study | `article` | 1.0 | Full schema.org `NewsArticle` JSON-LD with `articleSection` ⇒ structured topics (`business`, `tech`) plus keyphrase topics (`artificial intelligence`, `Google study`, `tech industry workers`). |
| Amazon Cuisinart toaster product | `product` | 0.65 | Classified correctly via URL pattern (`/dp/`). On a successful fetch we get the real title (`Amazon.com: Cuisinart CPT-122 2-Slice Compact Plastic Toaster…`) and product-feature topics; on a bot-challenge fetch we get the truncated "Click the button" stub. Both outcomes are surfaced honestly — this is exactly the kind of variance the Tier-B/C plan in [docs/02-design.md §2](docs/02-design.md) is designed to absorb. |
| REI blog post | (blocked) | — | **Akamai bot mitigation drops the connection at TLS layer.** Pipeline returns a structured 502 with the error class. This is the real-world Tier-C case (headless browser + residential IPs) described in [docs/02-design.md §2](docs/02-design.md). |

Together, the three URLs sample three points on the difficulty curve:
fully cooperative (CNN), partially defended (Amazon, sometimes serves real
HTML, sometimes serves a challenge), and hard-defended (REI / Akamai). Part 1
handles the first cleanly, the second on a best-effort basis, and surfaces
the third as a known limitation that Part 2 addresses with a Tier-C
headless-browser fallback.

## How Part 1 maps to the assignment

- **Input**: any URL ✅
- **Output**: HTML metadata (title, description, body, etc.) ✅
- **Plus**: topic list + page category, as the assignment also requested
  (*"classify the page, and return a list of relevant topics"*) ✅
- **Language**: Python ✅
- **Cloud demo**: see [deploy/cloud-run.md](deploy/cloud-run.md). The
  container is portable across Cloud Run / App Runner / Container Apps.

## Allowed / not allowed

- Uses 3rd-party libraries for **parsing**: `beautifulsoup4`, `lxml`,
  `trafilatura` for body extraction, `yake` for keyword extraction. ✅
  (Assignment FAQ: *"Can I use external libraries for HTML parsing? Yes."*)
- **Does not** call any 3rd-party service that performs the same end-to-end
  function (e.g. Diffbot, Apify, ScrapingBee). ✅

## AI assistance disclosure

Per the assignment FAQ, here is how AI was used:

- **Claude (Anthropic)** was used to scaffold the Python project structure,
  write the initial drafts of `fetcher.py`, `extractor.py`, `classifier.py`,
  and `main.py`, and to draft the design documents in `docs/`. All code was
  reviewed, edited, and tested by the author.
- AI was specifically helpful for: (1) enumerating the schema.org `@type`
  values to map to coarse categories, (2) drafting the protobuf schema in
  the design doc, (3) producing the cost model table in §5 of the design
  doc as a starting point for the author's own estimates.
- AI was **not** used for fetching, parsing, or classifying pages at
  runtime — the service uses only the libraries listed above.

## Design + PoC documents

- [docs/02-design.md](docs/02-design.md) — full architecture for ingesting
  billions of URLs/month: tiered crawl, dedupe, unified protobuf schema,
  hot KV + analytical lake, SLOs/SLAs, error budgets, cost model,
  reliability, monitoring.
- [docs/03-poc-plan.md](docs/03-poc-plan.md) — 6-week PoC plan with
  workstream breakdown, knowns vs. unknowns vs. risks, evaluation criteria,
  staged release plan, and staffing assumptions.

## What I'd do next (beyond Part 1)

In priority order, if I had another week:

1. Conditional GET (`ETag` / `If-Modified-Since`) — easy 30% cost cut at
   scale, described in §5 of the design doc.
2. Tier-C Playwright fallback wired behind a feature flag, to actually
   handle the REI case end-to-end.
3. Per-host adaptive rate limiter (AIMD on 429/503).
4. A small labeled eval set (~200 URLs) + a `make eval` target that
   measures topic-extraction F1 against it — closes the feedback loop on
   classifier quality changes.
